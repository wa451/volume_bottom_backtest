from datetime import datetime

from sqlalchemy import (
    String,
    Float,
    Integer,
    Boolean,
    DateTime,
    JSON,
    ForeignKey,
    Index,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base, utcnow

Json = JSON().with_variant(JSONB, "postgresql")


class Stock(Base):
    __tablename__ = "stocks"
    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)
    code: Mapped[str] = mapped_column(String(8), index=True)
    company_name: Mapped[str] = mapped_column(String(256))
    market_segment: Mapped[str] = mapped_column(String(16), index=True)
    sector: Mapped[str] = mapped_column(String(128))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class MarketData(Base):
    __tablename__ = "market_data_metadata"
    ticker: Mapped[str] = mapped_column(
        String(16), ForeignKey("stocks.ticker"), primary_key=True
    )
    metadata_json: Mapped[dict] = mapped_column(Json, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SystemState(Base):
    __tablename__ = "system_state"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(Json, default=dict)


class Job(Base):
    __tablename__ = "backtest_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    progress_percent: Mapped[float] = mapped_column(Float, default=0)
    current_step: Mapped[str] = mapped_column(String(512), default="Worker待機中")
    processed_items: Mapped[int] = mapped_column(Integer, default=0)
    total_items: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(String(4000))
    lease_owner: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[dict] = mapped_column(Json, default=dict)
    artifacts: Mapped[dict] = mapped_column(Json, default=dict)


class Config(Base):
    __tablename__ = "backtest_configs"
    job_id: Mapped[str] = mapped_column(
        ForeignKey("backtest_jobs.id", ondelete="CASCADE"), primary_key=True
    )
    request: Mapped[dict] = mapped_column(Json)
    engine_config: Mapped[dict] = mapped_column(Json)


class Result(Base):
    __tablename__ = "backtest_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("backtest_jobs.id", ondelete="CASCADE"), index=True
    )
    period_type: Mapped[str] = mapped_column(String(8))
    market_cap_group: Mapped[str] = mapped_column(String(32))
    market_segment: Mapped[str] = mapped_column(String(16))
    drawdown_threshold: Mapped[float] = mapped_column(Float)
    volume_ratio_threshold: Mapped[float] = mapped_column(Float)
    holding_period: Mapped[int] = mapped_column(Integer)
    metrics: Mapped[dict] = mapped_column(Json)
    __table_args__ = (
        Index(
            "result_scope",
            "job_id",
            "period_type",
            "market_cap_group",
            "market_segment",
            "holding_period",
        ),
    )


class TradeArtifact(Base):
    __tablename__ = "backtest_trades"
    job_id: Mapped[str] = mapped_column(
        ForeignKey("backtest_jobs.id", ondelete="CASCADE"), primary_key=True
    )
    file_location: Mapped[str] = mapped_column(String(512))
    num_rows: Mapped[int] = mapped_column(Integer)
