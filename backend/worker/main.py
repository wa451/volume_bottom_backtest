"""Independent durable Worker; the API only registers jobs and reads results."""

import argparse
import logging
import threading
import time
import shutil
import pandas as pd
from filelock import FileLock
from sqlalchemy import select, delete
from src.utils import init_dirs, load_config
from src.universe import load_universe
from src.downloader import Downloader
from src.backtest import prepare_features, run_backtest
from src.report import analyze
from backend.app.settings import Settings
from backend.app.db import Database, utcnow
from backend.app.models import Job, Config, Result, TradeArtifact, SystemState
from backend.app.jobs import claim, touch, LeaseLost
from backend.app.storage import Storage
from backend.app.serialization import clean
from backend.app.market import restore_market, backup_market, sync_market

log = logging.getLogger(__name__)
KEYS = (
    "period_type",
    "market_cap_group",
    "market_segment",
    "drawdown_threshold",
    "volume_ratio_threshold",
    "holding_period",
)


class Worker:
    def __init__(self, settings=None, db=None):
        self.c = settings or Settings()
        self.c.validate()
        self.db = db or Database(self.c.database_url)
        self.db.initialize()
        self.storage = Storage(self.c)
        init_dirs(self.c.data_root)

    def import_cache(self):
        with FileLock(str(self.c.data_root / ".run.lock")):
            restore_market(self.c, self.db, self.storage)
            path = self.c.data_root / "data/universe/universe.csv"
            if path.exists():
                c = load_config(self.c.config_path)
                c["universe"]["markets"] = ["Prime", "Standard", "Growth"]
                universe = load_universe(self.c.data_root, c)
                sync_market(self.c, self.db, universe)

    def run_once(self):
        claimed = claim(self.db, self.c.lease_seconds)
        if not claimed:
            return False
        job_id, owner = claimed
        stop, lost = threading.Event(), threading.Event()

        def heartbeat():
            while not stop.wait(max(1, self.c.lease_seconds // 4)):
                try:
                    touch(self.db, job_id, owner, self.c.lease_seconds)
                except Exception:
                    log.exception("Heartbeat failed for %s", job_id)
                    lost.set()
                    return

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()

        def progress(status, done, total, detail, low, high):
            if lost.is_set():
                raise LeaseLost("Heartbeat failed")
            touch(
                self.db,
                job_id,
                owner,
                self.c.lease_seconds,
                status=status,
                processed_items=done,
                total_items=total,
                current_step=detail,
                progress_percent=round(low + (high - low) * done / max(1, total), 1),
            )

        try:
            with self.db.session() as s:
                job, config = s.get(Job, job_id), s.get(Config, job_id)
                kind, request, c = job.kind, config.request, config.engine_config
            run_root = self.c.data_root / "data/web/runs" / job_id / owner
            (run_root / "results/logs").mkdir(parents=True, exist_ok=True)
            # A single shared lock includes CLI use. Heartbeats continue while waiting.
            with FileLock(str(self.c.data_root / ".run.lock")):
                progress(
                    "downloading" if kind == "update" else "preprocessing",
                    0,
                    1,
                    "キャッシュ準備",
                    0,
                    0,
                )
                restore_market(self.c, self.db, self.storage)
                (run_root / "data").symlink_to(
                    self.c.data_root / "data", target_is_directory=True
                )
                if (
                    kind == "backtest"
                    and not (run_root / "data/universe/universe.csv").exists()
                ):
                    raise ValueError(
                        "市場データがありません。先にデータ更新を実行してください"
                    )
                universe = load_universe(
                    run_root,
                    c,
                    refresh=kind == "update" and request.get("refresh_universe", True),
                )
                chosen = request.get("tickers", [])
                if chosen:
                    missing = set(chosen) - set(universe.ticker)
                    if missing:
                        raise ValueError(
                            "現在マスター・選択市場にない銘柄: "
                            + ", ".join(sorted(missing))
                        )
                    universe = universe[universe.ticker.isin(chosen)].reset_index(
                        drop=True
                    )
                artifacts = {}
                if kind == "update":
                    benchmarks = (
                        c.get("benchmark", {}).get("tickers", [])
                        if c.get("benchmark", {}).get("enabled", True)
                        else []
                    )
                    total = len(universe) * 2 + len(benchmarks)
                    prior_failures = (
                        self.c.data_root / "results/logs/failed_tickers.csv"
                    )
                    if prior_failures.exists():
                        shutil.copyfile(
                            prior_failures, run_root / "results/logs/failed_tickers.csv"
                        )
                    dl = Downloader(
                        run_root,
                        c,
                        progress=lambda row, done: progress(
                            "downloading",
                            done,
                            total,
                            row["ticker"] + " / " + row["kind"] + " / " + row["status"],
                            2,
                            85,
                        ),
                    )
                    dl.failure_path = prior_failures
                    if request.get("retry_failed", False):
                        targets = {
                            (t, kind)
                            for t in universe.ticker
                            for kind in ("price", "shares")
                        }
                        targets.update((t, "benchmark") for t in benchmarks)
                        total = len(targets.intersection(dl.failures))
                    states = dl.run(
                        universe, retry_failed=request.get("retry_failed", False)
                    )
                    # Preserve failure history across new update jobs (retry_failed).
                    summary = {
                        "downloaded": sum(x["status"] == "downloaded" for x in states),
                        "cached": sum(x["status"] == "cached" for x in states),
                        "failed": sum(x["status"] == "failed" for x in states),
                        "items": states,
                    }
                    all_c = load_config(self.c.config_path)
                    all_c["universe"]["markets"] = ["Prime", "Standard", "Growth"]
                    sync_market(self.c, self.db, load_universe(run_root, all_c), states)
                    progress("analyzing", 0, 1, "価格・株式数のバックアップ", 86, 95)
                    backup_market(self.c, self.db, self.storage)
                else:
                    failed_features = {}
                    for i, ticker in enumerate(universe.ticker):
                        progress(
                            "preprocessing",
                            i,
                            len(universe),
                            ticker + " / 指標・当時時価総額",
                            2,
                            25,
                        )
                        try:
                            prepare_features(run_root, ticker, c)
                        except (ValueError, OSError, KeyError) as exc:
                            failed_features[ticker] = str(exc)
                    trades = run_backtest(
                        run_root,
                        universe,
                        c,
                        progress=lambda done, total, detail: progress(
                            "backtesting",
                            done,
                            total,
                            detail + " / 全選択条件を評価",
                            25,
                            65,
                        ),
                    )
                    quality = analyze(
                        run_root,
                        c,
                        intersections=True,
                        full=True,
                        progress=lambda done, total, detail: progress(
                            "analyzing", done, total, detail, 65, 92
                        ),
                    )
                    data = pd.read_csv(run_root / "results/parameter_results.csv")
                    candidates = pd.read_csv(
                        run_root / "results/candidate_test_results.csv"
                    )
                    summary = {
                        "quality": quality,
                        "parameter_combinations": len(
                            c["strategy"]["drawdown_thresholds"]
                        )
                        * len(c["strategy"]["volume_ratio_thresholds"]),
                        "holding_periods": c["strategy"]["holding_periods"],
                        "minimum_trades": c["validation"]["minimum_trades"],
                        "candidates": clean(candidates.to_dict("records")),
                        "feature_errors": failed_features,
                        "full_note": "FULLは境界除外済みのTrainとTestの有効取引を結合した参考値です。候補選択はTrainのみ。",
                    }
                    for path in (run_root / "results").iterdir():
                        if path.is_file():
                            key = f"runs/{job_id}/{owner}/{path.name}"
                            artifacts[path.name] = self.storage.put(path, key)
                    progress("analyzing", 1, 1, "結果の保存", 95, 99)
                if lost.is_set():
                    raise LeaseLost("Heartbeat failed")
                # Fence final writes against an expired/reclaimed worker.
                with self.db.session.begin() as s:
                    j = s.scalar(select(Job).where(Job.id == job_id).with_for_update())
                    if j.lease_owner != owner:
                        raise LeaseLost("Worker ownership changed")
                    if kind == "backtest":
                        s.execute(delete(Result).where(Result.job_id == job_id))
                        s.add_all(
                            [
                                Result(
                                    job_id=job_id,
                                    **{k: clean(row[k]) for k in KEYS},
                                    metrics=clean(
                                        {k: v for k, v in row.items() if k not in KEYS}
                                    ),
                                )
                                for row in data.to_dict("records")
                            ]
                        )
                        s.merge(
                            TradeArtifact(
                                job_id=job_id,
                                file_location=artifacts["trades.parquet"],
                                num_rows=len(trades),
                            )
                        )
                    j.status, j.progress_percent, j.current_step = (
                        "completed",
                        100,
                        "完了",
                    )
                    j.summary, j.artifacts, j.completed_at = (
                        clean(summary),
                        artifacts,
                        utcnow(),
                    )
                    j.lease_owner, j.lease_until = None, None
        except LeaseLost:
            log.warning("Lease lost: %s", job_id)
        except Exception as exc:
            log.exception("Job failed: %s", job_id)
            try:
                touch(
                    self.db,
                    job_id,
                    owner,
                    status="failed",
                    error_message=str(exc)[:4000],
                    current_step="処理失敗",
                    completed_at=utcnow(),
                )
            except LeaseLost:
                pass
        finally:
            stop.set()
            thread.join(timeout=3)
        return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--import-cache", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    worker = Worker()
    if args.import_cache:
        worker.import_cache()
        return
    # Only import a pre-existing cache when DB metadata has not been initialized.
    with worker.db.session() as s:
        initialized = s.get(SystemState, "market_status") is not None
    if not initialized:
        worker.import_cache()
    while True:
        worked = worker.run_once()
        if args.once:
            break
        if not worked:
            time.sleep(2)


if __name__ == "__main__":
    main()
