from copy import deepcopy
from datetime import date
import re
from pydantic import BaseModel, Field, ConfigDict, model_validator
from src.utils import today, validate_config
from src.strategy_config import StrategyParameters, PortfolioSettings, TradingCosts, parameter_grid, parameter_defaults, portfolio_mode
from src.strategies import REGISTRY


class BacktestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_date: date = date(2010, 1, 1)
    end_date: date = Field(default_factory=lambda: today().date())
    train_start: date = date(2010, 1, 1)
    train_end: date = date(2021, 12, 31)
    test_start: date = date(2022, 1, 1)
    test_end: date = Field(default_factory=lambda: today().date())
    drawdown_thresholds: list[float] = Field(
        default_factory=lambda: [0.2, 0.3, 0.4, 0.5, 0.6], min_length=1, max_length=8
    )
    volume_ratio_thresholds: list[float] = Field(
        default_factory=lambda: [1.5, 2, 3, 4, 5], min_length=1, max_length=8
    )
    holding_periods: list[int] = Field(
        default_factory=lambda: [20, 60, 120, 250], min_length=1, max_length=6
    )
    strategy_ids: list[str] = Field(default_factory=lambda: ['bottom_volume'], min_length=1, max_length=4)
    strategy_params: dict[str, StrategyParameters] = Field(default_factory=dict)
    portfolio: PortfolioSettings = Field(default_factory=PortfolioSettings)
    costs: TradingCosts | None = None
    cooldown: int = Field(20, ge=0, le=1000)
    markets: list[str] = Field(
        default_factory=lambda: ["Prime", "Standard", "Growth"],
        min_length=1,
        max_length=3,
    )
    market_cap_groups: list[str] = Field(
        default_factory=lambda: ["ALL"], min_length=1, max_length=7
    )
    tickers: list[str] = Field(default_factory=list, max_length=5000)

    @model_validator(mode="after")
    def valid(self):
        if not date(1990, 1, 1) <= self.start_date <= self.end_date <= today().date():
            raise ValueError("分析期間は1990年以降・現在日までに設定してください")
        if (
            not self.start_date
            <= self.train_start
            <= self.train_end
            < self.test_start
            <= self.test_end
            <= self.end_date
        ):
            raise ValueError("分析期間内でTrain → Testを重複なく指定してください")
        for values in (
            self.drawdown_thresholds,
            self.volume_ratio_thresholds,
            self.holding_periods,
            self.markets,
            self.market_cap_groups,
            self.tickers,
        ):
            if len(set(values)) != len(values):
                raise ValueError("選択肢の重複があります")
        if not all(0 < x < 1 for x in self.drawdown_thresholds) or not all(
            0 < x <= 100 for x in self.volume_ratio_thresholds
        ):
            raise ValueError("下落率・出来高倍率が範囲外です")
        if not all(0 < x <= 1250 for x in self.holding_periods):
            raise ValueError("保有期間は1〜1250営業日です")
        if not set(self.markets) <= {"Prime", "Standard", "Growth"}:
            raise ValueError("対象市場が不正です")
        self.tickers = [
            t.upper() if t.upper().endswith(".T") else t.upper() + ".T"
            for t in self.tickers
        ]
        if any(
            not re.fullmatch(r"[0-9][0-9A-Z]{3}\.T", t) for t in self.tickers
        ) or len(set(self.tickers)) != len(self.tickers):
            raise ValueError("銘柄コードが不正・重複しています")
        return self

    def engine(self, base):
        c = deepcopy(base)
        if not set(self.market_cap_groups) <= {
            "ALL",
            *(b["name"] for b in c["market_cap_bins"]),
        }:
            raise ValueError("時価総額区分が不正です")
        c["data"].update(
            start_date=self.start_date.isoformat(), end_date=self.end_date.isoformat()
        )
        c["train"] = {
            "start": self.train_start.isoformat(),
            "end": self.train_end.isoformat(),
        }
        c["test"] = {
            "start": self.test_start.isoformat(),
            "end": self.test_end.isoformat(),
        }
        c["strategy"].update(
            drawdown_thresholds=self.drawdown_thresholds,
            volume_ratio_thresholds=self.volume_ratio_thresholds,
            holding_periods=self.holding_periods,
            signal_cooldown_days=self.cooldown,
        )
        c["universe"]["markets"] = self.markets
        c["analysis"] = {
            "market_cap_groups": self.market_cap_groups,
            "tickers": self.tickers,
        }
        if not set(self.strategy_ids) <= REGISTRY.keys() or len(set(self.strategy_ids)) != len(self.strategy_ids):
            raise ValueError("戦略が不正・重複しています")
        if not set(self.strategy_params) <= set(REGISTRY) - {"bottom_volume"}:
            raise ValueError("戦略パラメータの対象が不正です")
        c["strategy_ids"] = self.strategy_ids
        c["strategy_params"] = {key: {**parameter_defaults(key), **value.model_dump(exclude_unset=True)} for key, value in self.strategy_params.items()}
        c["portfolio"] = self.portfolio.model_dump()
        if self.costs is not None:
            c["cost"] = self.costs.model_dump()
        if portfolio_mode(c):
            parameter_grid(c)
        c["output"]["heatmaps"] = False
        validate_config(c)
        return c


class UpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_date: date = date(2010, 1, 1)
    tickers: list[str] = Field(default_factory=list, max_length=5000)
    retry_failed: bool = False
    refresh_universe: bool = True
    include_strategy_data: bool = False

    @model_validator(mode="after")
    def valid(self):
        if not date(1990, 1, 1) <= self.start_date <= today().date():
            raise ValueError("取得開始日が不正です")
        self.tickers = [
            t.upper() if t.upper().endswith(".T") else t.upper() + ".T"
            for t in self.tickers
        ]
        if any(
            not re.fullmatch(r"[0-9][0-9A-Z]{3}\.T", t) for t in self.tickers
        ) or len(set(self.tickers)) != len(self.tickers):
            raise ValueError("銘柄コードが不正・重複しています")
        return self
