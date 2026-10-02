from contextlib import asynccontextmanager
from copy import deepcopy
import secrets
import json
import httpx
from botocore.exceptions import BotoCoreError, ClientError
from typing import Annotated
from fastapi import FastAPI, Depends, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select, func
from src.utils import load_config, fingerprint
from .settings import Settings
from .db import Database
from .models import Job, Config, Result
from .jobs import enqueue, job_dict
from .analysis import analysis_request, latest_analysis
from .schemas import BacktestRequest, UpdateRequest
from .storage import Storage
from .market import market_status
from .trades import TradeFilter, page, histogram, csv_chunks
from . import strategy_results as portfolios
from src.strategies import metadata
from src.strategy_config import parameter_defaults

SORTS = {
    "num_signals",
    "num_trades",
    "mean_return",
    "median_return",
    "win_rate",
    "profit_factor",
    "expectancy",
    "ci95_lower",
    "robustness_score",
}


def create_app(settings=None):
    c = settings or Settings()
    c.validate()
    db, storage = Database(c.database_url), Storage(c)
    base = load_config(c.config_path)

    @asynccontextmanager
    async def lifespan(app):
        db.initialize()
        yield
        db.engine.dispose()

    app = FastAPI(title="底値出来高研究 API", version="1.0.0", lifespan=lifespan)
    app.state.db, app.state.settings, app.state.storage = db, c, storage

    def authenticate(authorization: Annotated[str | None, Header()] = None):
        if c.api_token and not secrets.compare_digest(
            authorization or "", "Bearer " + c.api_token
        ):
            raise HTTPException(401, "認証が必要です")

    def job(s, job_id, completed=False, backtest=False):
        j = s.get(Job, job_id)
        if not j or (backtest and j.kind != "backtest"):
            raise HTTPException(404, "ジョブが見つかりません")
        if completed and j.status != "completed":
            raise HTTPException(409, "ジョブはまだ完了していません")
        return j

    def artifact(job_id, name, legacy=False):
        with db.session() as s:
            j = job(s, job_id, completed=True, backtest=True)
            if legacy and j.summary.get("analysis_mode") == "portfolio":
                raise HTTPException(409, "Portfolio結果はstrategy-results / strategy-trades APIで参照してください")
            key = j.artifacts.get(name)
        if not key:
            raise HTTPException(404, "ファイルが見つかりません")
        try:
            return storage.get(key)
        except (
            OSError,
            ValueError,
            httpx.HTTPError,
            BotoCoreError,
            ClientError,
        ) as exc:
            raise HTTPException(503, "保存ファイルを取得できません") from exc

    @app.get("/health")
    def health():
        with db.session() as s:
            s.execute(select(1))
        return {"status": "ok"}

    auth = [Depends(authenticate)]

    @app.get("/api/defaults", dependencies=auth)
    def defaults():
        value = BacktestRequest().model_dump(mode="json")
        value.update(
            start_date=base["data"]["start_date"],
            train_start=base["train"]["start"],
            train_end=base["train"]["end"],
            test_start=base["test"]["start"],
            drawdown_thresholds=base["strategy"]["drawdown_thresholds"],
            volume_ratio_thresholds=base["strategy"]["volume_ratio_thresholds"],
            holding_periods=base["strategy"]["holding_periods"],
            cooldown=base["strategy"]["signal_cooldown_days"],
            markets=base["universe"]["markets"],
        )
        return {
            "config": {**value, "costs": base["cost"]},
            "strategies": metadata(),
            "strategy_defaults": {key: parameter_defaults(key) for key in ("kenmo_breakout", "kenmo_earnings", "kenmo_growth")},
            "market_cap_bins": base["market_cap_bins"],
            "minimum_trades": base["validation"]["minimum_trades"],
        }

    @app.get("/api/market-data/status", dependencies=auth)
    def status():
        return market_status(db)

    @app.post("/api/market-data/update", status_code=202, dependencies=auth)
    def update_data(
        body: UpdateRequest, idempotency_key: Annotated[str | None, Header()] = None
    ):
        config = deepcopy(base)
        config["data"]["start_date"] = body.start_date.isoformat()
        return {
            "job_id": enqueue(
                db, "update", body.model_dump(mode="json"), config, idempotency_key
            )
        }

    @app.post("/api/backtests", status_code=202, dependencies=auth)
    def backtest(
        body: BacktestRequest, idempotency_key: Annotated[str | None, Header()] = None
    ):
        try:
            engine = body.engine(base)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {
            "job_id": enqueue(
                db, "backtest", body.model_dump(mode="json"), engine, idempotency_key
            )
        }

    @app.get("/api/jobs", dependencies=auth)
    @app.get("/api/backtests", dependencies=auth)
    def history(
        request: Request,
        limit: int = Query(30, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ):
        with db.session() as s:
            q = select(Job).where(Job.kind != "analysis")
            count = select(func.count()).select_from(Job).where(Job.kind != "analysis")
            if request.url.path.endswith("/backtests"):
                q, count = (
                    q.where(Job.kind == "backtest"),
                    count.where(Job.kind == "backtest"),
                )
            jobs = s.scalars(
                q.order_by(Job.created_at.desc()).offset(offset).limit(limit)
            ).all()
            return {
                "items": [job_dict(s, j) for j in jobs],
                "total": s.scalar(count),
                "limit": limit,
                "offset": offset,
            }

    @app.get("/api/jobs/{job_id}", dependencies=auth)
    @app.get("/api/backtests/{job_id}", dependencies=auth)
    def get_job(job_id: str):
        with db.session() as s:
            return job_dict(s, job(s, job_id))

    @app.post("/api/backtests/{job_id}/rerun", status_code=202, dependencies=auth)
    def rerun(job_id: str, idempotency_key: Annotated[str | None, Header()] = None):
        with db.session() as s:
            old = job(s, job_id, backtest=True)
            cfg = s.get(Config, old.id)
            body, engine = cfg.request, cfg.engine_config
        return {"job_id": enqueue(db, "backtest", body, engine, idempotency_key)}

    @app.post("/api/backtests/{job_id}/analysis", status_code=202, dependencies=auth)
    def start_analysis(job_id: str, retry: bool = False):
        body = analysis_request(job_id, c)
        with db.session() as s:
            job(s, job_id, completed=True, backtest=True)
            engine = s.get(Config, job_id).engine_config
            old = latest_analysis(s, body)
            if old and (old.status != "failed" or not retry):
                return {"job_id": old.id}
            previous = old.id if old else "first"
        key = "analysis-" + fingerprint({**body, "previous": previous})
        return {"job_id": enqueue(db, "analysis", body, engine, key)}

    @app.get("/api/backtests/{job_id}/analysis", dependencies=auth)
    def get_analysis(job_id: str):
        with db.session() as s:
            job(s, job_id, completed=True, backtest=True)
            found = latest_analysis(s, analysis_request(job_id, c))
            if not found:
                return {"status": "not_started", "report": None}
            result = {
                "job_id": found.id,
                "status": found.status,
                "progress_percent": found.progress_percent,
                "error_message": found.error_message,
                "report": None,
            }
            key = (
                found.artifacts.get("analysis.json")
                if found.status == "completed"
                else None
            )
        if key:
            try:
                result["report"] = json.loads(
                    storage.get(key).read_text(encoding="utf-8")
                )
            except (
                OSError,
                ValueError,
                httpx.HTTPError,
                BotoCoreError,
                ClientError,
            ) as exc:
                raise HTTPException(503, "分析ファイルを取得できません") from exc
        return result

    @app.get("/api/backtests/{job_id}/results", dependencies=auth)
    def results(
        job_id: str,
        period_type: str = "train",
        market_cap_group: str = "ALL",
        market_segment: str = "ALL",
        holding_period: int | None = None,
        drawdown_threshold: float | None = None,
        volume_ratio_threshold: float | None = None,
        sort: str = "mean_return",
        descending: bool = True,
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ):
        if sort not in SORTS or period_type not in ("train", "test", "full"):
            raise HTTPException(422, "並び順・期間が不正です")
        with db.session() as s:
            j = job(s, job_id, completed=True, backtest=True)
            if j.summary.get("analysis_mode") == "portfolio":
                raise HTTPException(409, "Portfolio結果はstrategy-results APIで参照してください")
            q = select(Result).where(
                Result.job_id == job_id, Result.period_type == period_type
            )
            for field, value in (
                ("market_cap_group", market_cap_group),
                ("market_segment", market_segment),
                ("holding_period", holding_period),
                ("drawdown_threshold", drawdown_threshold),
                ("volume_ratio_threshold", volume_ratio_threshold),
            ):
                if value is not None and value != "*":
                    q = q.where(getattr(Result, field) == value)
            rows = s.scalars(q).all()
        items = [
            {
                **{
                    k: getattr(r, k)
                    for k in (
                        "period_type",
                        "market_cap_group",
                        "market_segment",
                        "drawdown_threshold",
                        "volume_ratio_threshold",
                        "holding_period",
                    )
                },
                **r.metrics,
            }
            for r in rows
        ]

        def score(item):
            if sort == "profit_factor" and item.get("profit_factor_infinite"):
                return float("inf")
            return item.get(sort)

        valid = [x for x in items if score(x) is not None]
        valid.sort(key=lambda x: (score(x), x.get("num_trades", 0)), reverse=descending)
        items = valid + [x for x in items if score(x) is None]
        return {
            "items": items[offset : offset + limit],
            "total": len(items),
            "limit": limit,
            "offset": offset,
        }

    @app.get("/api/backtests/{job_id}/trades", dependencies=auth)
    def trades(
        job_id: str,
        filters: Annotated[TradeFilter, Depends()],
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ):
        return page(artifact(job_id, "trades.parquet", legacy=True), filters, limit, offset)

    @app.get("/api/backtests/{job_id}/distribution", dependencies=auth)
    def distribution(job_id: str, filters: Annotated[TradeFilter, Depends()]):
        return histogram(artifact(job_id, "trades.parquet", legacy=True), filters)

    @app.get("/api/backtests/{job_id}/trades.csv", dependencies=auth)
    def trades_csv(job_id: str, filters: Annotated[TradeFilter, Depends()]):
        return StreamingResponse(
            csv_chunks(artifact(job_id, "trades.parquet", legacy=True), filters),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="trades.csv"'},
        )

    @app.get("/api/backtests/{job_id}/strategy-results", dependencies=auth)
    def strategy_results(job_id: str, filters: Annotated[portfolios.StrategyFilter, Depends()],
                         sort: str = "cagr", descending: bool = True,
                         limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
        if sort not in portfolios.SORTS:
            raise HTTPException(422, "並び順が不正です")
        return portfolios.result_page(artifact(job_id, "strategy_results.parquet"), filters, sort, descending, limit, offset)

    @app.get("/api/backtests/{job_id}/strategy-curves", dependencies=auth)
    def strategy_curves(job_id: str, filters: Annotated[portfolios.StrategyFilter, Depends()],
                        limit: int = Query(10000, ge=1, le=20000), offset: int = Query(0, ge=0)):
        if filters.parameter_id is None or filters.strategy_id is None:
            raise HTTPException(422, "曲線は戦略とパラメータを指定してください")
        return portfolios.artifact_page(artifact(job_id, "strategy_curves.parquet"), filters, limit, offset, curve=True)

    @app.get("/api/backtests/{job_id}/strategy-trades", dependencies=auth)
    def strategy_trades(job_id: str, filters: Annotated[portfolios.StrategyFilter, Depends()],
                        limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
        return portfolios.artifact_page(artifact(job_id, "trades.parquet"), filters, limit, offset)

    @app.get("/api/backtests/{job_id}/strategy-trades.csv", dependencies=auth)
    def strategy_trades_csv(job_id: str, filters: Annotated[portfolios.StrategyFilter, Depends()]):
        return StreamingResponse(portfolios.trade_csv(artifact(job_id, "trades.parquet"), filters),
            media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="strategy-trades.csv"'})

    @app.get("/api/backtests/{job_id}/files/{name}", dependencies=auth)
    def file(job_id: str, name: str):
        allowed = {
            "parameter_results.csv",
            "strategy_results.csv",
            "strategy_quality.csv",
            "strategy_summary.json",
            "market_cap_comparison.csv",
            "market_segment_comparison.csv",
            "top_candidates_train.csv",
            "candidate_test_results.csv",
            "data_quality_report.md",
            "run.json",
            "summary.md",
        }
        if name not in allowed:
            raise HTTPException(404, "ファイルが見つかりません")
        return FileResponse(artifact(job_id, name), filename=name)

    return app


app = create_app()
