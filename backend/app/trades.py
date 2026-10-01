from dataclasses import dataclass
from datetime import date
from typing import Literal, Annotated
import csv
import io
import duckdb
from fastapi import Query
from .serialization import clean


@dataclass
class TradeFilter:
    period_type: Literal["train", "test", "full"] = "train"
    market_cap_group: str = "ALL"
    market_segment: str = "ALL"
    holding_period: Annotated[int | None, Query(ge=1, le=1250)] = None
    drawdown_threshold: Annotated[float | None, Query(gt=0, lt=1)] = None
    volume_ratio_threshold: Annotated[float | None, Query(gt=0, le=100)] = None
    search: Annotated[str, Query(max_length=128)] = ""
    signal_start: date | None = None
    signal_end: date | None = None
    outcome: Literal["all", "profit", "loss"] = "all"
    trade_status: Literal[
        "complete", "all", "incomplete", "boundary_purged", "invalid_price"
    ] = "complete"

    def where(self):
        parts, args = [], []
        if self.period_type != "full":
            parts.append("period_type = ?")
            args.append(self.period_type)
        for key in ("market_cap_group", "market_segment"):
            if getattr(self, key) != "ALL":
                parts.append(f"{key} = ?")
                args.append(getattr(self, key))
        for key in ("holding_period", "drawdown_threshold", "volume_ratio_threshold"):
            if getattr(self, key) is not None:
                parts.append(f"{key} = ?")
                args.append(getattr(self, key))
        if self.trade_status != "all":
            parts.append("trade_status = ?")
            args.append(self.trade_status)
        if self.search:
            parts.append(
                "(contains(lower(ticker), lower(?)) OR contains(lower(company_name), lower(?)))"
            )
            args.extend([self.search, self.search])
        for key, op in (("signal_start", ">="), ("signal_end", "<=")):
            if getattr(self, key):
                parts.append(f"signal_date {op} ?")
                args.append(getattr(self, key))
        if self.outcome != "all":
            parts.append('"return" > 0' if self.outcome == "profit" else '"return" < 0')
        return (" WHERE " + " AND ".join(parts) if parts else ""), args


def connect():
    return duckdb.connect(config={"threads": 1})


def page(path, filters, limit, offset):
    where, args = filters.where()
    with connect() as db:
        total = db.execute(
            "SELECT count(*) FROM read_parquet(?)" + where, [str(path), *args]
        ).fetchone()[0]
        result = db.execute(
            "SELECT * EXCLUDE (__index_level_0__) FROM read_parquet(?)"
            + where
            + " ORDER BY signal_date DESC, ticker, drawdown_threshold, volume_ratio_threshold, holding_period LIMIT ? OFFSET ?",
            [str(path), *args, limit, offset],
        ).fetchdf()
    return {
        "items": clean(result.to_dict("records")),
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def histogram(path, filters):
    where, args = filters.where()
    where += (" AND " if where else " WHERE ") + 'isfinite("return")'
    with connect() as db:
        count, lo, hi = db.execute(
            'SELECT count(*), min("return"), max("return") FROM read_parquet(?)'
            + where,
            [str(path), *args],
        ).fetchone()
        if not count:
            return {"count": 0, "bins": []}
        if lo == hi:
            lo, hi = lo - 0.01, hi + 0.01
        step = (hi - lo) / 20
        bins = db.execute(
            'SELECT least(19, greatest(0, CAST(floor(("return" - ?) / ?) AS INTEGER))) AS bin, count(*) FROM read_parquet(?)'
            + where
            + " GROUP BY bin ORDER BY bin",
            [lo, step, str(path), *args],
        ).fetchall()
    counts = dict(bins)
    return {
        "count": count,
        "bins": [
            {
                "start": lo + i * step,
                "end": lo + (i + 1) * step,
                "count": counts.get(i, 0),
            }
            for i in range(20)
        ],
    }


def csv_chunks(path, filters):
    where, args = filters.where()
    with connect() as db:
        cursor = db.execute(
            "SELECT * EXCLUDE (__index_level_0__) FROM read_parquet(?)"
            + where
            + " ORDER BY signal_date DESC, ticker",
            [str(path), *args],
        )
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([x[0] for x in cursor.description])
        yield "\ufeff" + buf.getvalue()
        while rows := cursor.fetchmany(1000):
            buf.seek(0)
            buf.truncate(0)
            # Spreadsheet programs must treat ticker/company metadata as text.
            writer.writerows(
                [
                    [
                        "'" + v
                        if isinstance(v, str) and v.startswith(("=", "+", "-", "@"))
                        else v
                        for v in row
                    ]
                    for row in rows
                ]
            )
            yield buf.getvalue()
