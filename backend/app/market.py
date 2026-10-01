import shutil
from uuid import uuid4
import pandas as pd
from sqlalchemy import select, update
from src.data_loader import load_prices, normalize_shares
from src.utils import read_json
from .db import utcnow
from .models import Stock, MarketData, SystemState, Job
from .serialization import clean


def restore_market(settings, db, storage):
    with db.session() as s:
        state = s.get(SystemState, "market_backup")
        files = state.value.get("files", {}) if state else {}
    for relative, meta in files.items():
        dest = settings.data_root / relative
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(storage.get(meta["key"]), dest)


def backup_market(settings, db, storage):
    # Persist market snapshots independently from result files. Immutable keys
    # prevent API/Worker caches from serving a previous object under a new basis.
    with db.session() as s:
        old = s.get(SystemState, "market_backup")
        files = dict(old.value.get("files", {})) if old else {}
    root = settings.data_root
    paths = list((root / "data/universe").glob("*.csv")) + list(
        (root / "data/universe").glob("*.json")
    )
    paths += [root / "data/download_manifest.json"]
    paths += [root / "results/logs/failed_tickers.csv"]
    for folder in ("market", "shares", "benchmark"):
        paths += list((root / "data" / folder).glob("*.parquet"))
    for path in paths:
        if not path.exists():
            continue
        rel = path.relative_to(root).as_posix()
        signature = [path.stat().st_size, path.stat().st_mtime_ns]
        if files.get(rel, {}).get("signature") == signature:
            continue
        key = f"market/{uuid4().hex}/{rel}"
        storage.put(path, key)
        files[rel] = {"key": key, "signature": signature}
    with db.session.begin() as s:
        s.merge(SystemState(key="market_backup", value={"files": files}))


def sync_market(settings, db, universe, download_status=None):
    root = settings.data_root
    manifest = read_json(root / "data/download_manifest.json")
    failures_path = root / "results/logs/failed_tickers.csv"
    failures = (
        pd.read_csv(failures_path).to_dict("records") if failures_path.exists() else []
    )
    statuses = {(x["ticker"], x["kind"]): x for x in failures + (download_status or [])}
    rows = []
    for info in universe.to_dict("records"):
        ticker = info["ticker"]
        price = root / f"data/market/{ticker}.parquet"
        shares = root / f"data/shares/{ticker}.parquet"
        m = {
            "price_valid": False,
            "shares_valid": False,
            "price_rows": 0,
            "shares_rows": 0,
            "latest_date": None,
            "split_events": 0,
            "price_error": "",
            "shares_error": "",
            "download_mode": manifest.get("price:" + ticker, {}).get(
                "last_download_mode"
            ),
        }
        try:
            p = load_prices(price)
            m.update(
                price_valid=True,
                price_rows=len(p),
                latest_date=str(p.index[-1].date()),
                first_date=str(p.index[0].date()),
                split_events=int(p["Stock Splits"].fillna(0).ne(0).sum()),
            )
        except (ValueError, OSError, KeyError) as exc:
            # Missing and failed acquisitions are different quality measures.
            m["price_error"] = "" if not price.exists() else str(exc)
        if shares.exists():
            try:
                sh = normalize_shares(pd.read_parquet(shares))
                m.update(shares_valid=not sh.empty, shares_rows=len(sh))
            except (ValueError, OSError, KeyError) as exc:
                m["shares_error"] = str(exc)
        for kind in ("price", "shares"):
            outcome = statuses.get((ticker, kind))
            if outcome and outcome["status"] == "failed":
                m[kind + "_error"] = outcome["error"]
        partial = manifest.get("shares:" + ticker, {}).get("partial_errors", [])
        if partial:
            m["shares_error"] = "; ".join(partial)
        rows.append((info, m))
    with db.session.begin() as s:
        s.execute(update(Stock).values(active=False))
        for info, m in rows:
            s.merge(Stock(**info, active=True))
        s.flush()
        for info, m in rows:
            s.merge(
                MarketData(ticker=info["ticker"], metadata_json=m, updated_at=utcnow())
            )
        source = read_json(root / "data/universe/source.json")
        s.merge(
            SystemState(
                key="market_status",
                value={"checked_at": utcnow().isoformat() + "Z", "source": source},
            )
        )


def market_status(db):
    with db.session() as s:
        records = s.execute(
            select(Stock, MarketData)
            .outerjoin(MarketData)
            .where(Stock.active.is_(True))
        ).all()
        items = [
            {
                **{
                    k: getattr(stock, k)
                    for k in ("code", "ticker", "company_name", "market_segment")
                },
                **(meta.metadata_json if meta else {}),
            }
            for stock, meta in records
        ]
        state = s.get(SystemState, "market_status")
        latest = s.scalar(
            select(Job)
            .where(Job.kind == "backtest", Job.status == "completed")
            .order_by(Job.completed_at.desc())
            .limit(1)
        )
        quality = latest.summary.get("quality", {}) if latest else {}
    count = len(items)
    return clean(
        {
            "stock_count": count,
            "price_success_count": sum(bool(x.get("price_valid")) for x in items),
            "price_missing_count": sum(not x.get("price_valid") for x in items),
            "failure_count": sum(
                bool(x.get("price_error") or x.get("shares_error")) for x in items
            ),
            "shares_success_count": sum(bool(x.get("shares_valid")) for x in items),
            "shares_coverage": sum(bool(x.get("shares_valid")) for x in items) / count
            if count
            else None,
            "latest_date": max(
                (x["latest_date"] for x in items if x.get("latest_date")), default=None
            ),
            "split_events": sum(x.get("split_events", 0) for x in items),
            "last_backtest_market_cap_coverage": quality.get(
                "market_cap_signal_coverage"
            ),
            "last_backtest_id": latest.id if latest else None,
            "last_backtest_stock_count": quality.get("universe_count"),
            "checked_at": state.value.get("checked_at") if state else None,
            "source": state.value.get("source", {}) if state else {},
            "items": items,
        }
    )
