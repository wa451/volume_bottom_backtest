"""Validated, frozen strategy grids shared by API, CLI and Worker."""
from itertools import product
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .utils import fingerprint
from .strategies import REGISTRY


class StrategyParameters(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    mode: str = 'price_only'
    high_enabled: bool = True
    volume_enabled: bool = True
    revenue_enabled: bool = True
    earnings_enabled: bool = True
    roe_enabled: bool = True
    per_enabled: bool = True
    high_period: list[int] = Field(default_factory=lambda: [252], min_length=1, max_length=3)
    volume_ratio: list[float] = Field(default_factory=lambda: [1.5], min_length=1, max_length=3)
    revenue_growth: list[float] = Field(default_factory=lambda: [.1], min_length=1, max_length=3)
    earnings_growth: list[float] = Field(default_factory=lambda: [.2], min_length=1, max_length=3)
    roe: list[float] = Field(default_factory=lambda: [.1], min_length=1, max_length=3)
    per_min: float = Field(10, ge=0, le=100)
    per_max: list[float] = Field(default_factory=lambda: [40], min_length=1, max_length=3)
    entry_offset: list[int] = Field(default_factory=lambda: [2], min_length=1, max_length=4)
    reaction_rate: list[float] = Field(default_factory=lambda: [.03], min_length=1, max_length=3)
    cap_min: float = Field(5e9, ge=0, le=1e14)
    cap_max: float = Field(3e10, gt=0, le=1e15)
    listing_enabled: bool = False
    listing_years: float = Field(5, gt=0, le=100)
    stop_loss: list[float] = Field(default_factory=lambda: [.08], min_length=1, max_length=4)
    exit_modes: list[str] = Field(default_factory=lambda: ['holding'], min_length=1, max_length=4)
    take_profit: list[float] = Field(default_factory=lambda: [.3], min_length=1, max_length=4)
    holding_period: list[int] = Field(default_factory=lambda: [60], min_length=1, max_length=4)
    trailing_stop: list[float] = Field(default_factory=lambda: [.15], min_length=1, max_length=3)
    ma_period: list[int] = Field(default_factory=lambda: [20], min_length=1, max_length=3)
    maximum_holding: int = Field(252, ge=1, le=1250)

    @model_validator(mode='after')
    def valid(self):
        if self.mode not in ('price_only', 'fundamentals'):
            raise ValueError('データ版が不正です')
        if not set(self.exit_modes) <= {'fixed', 'holding', 'trailing', 'ma'}:
            raise ValueError('売却方式が不正です')
        for key in ('high_period', 'volume_ratio', 'revenue_growth', 'earnings_growth', 'roe', 'per_max', 'entry_offset', 'reaction_rate', 'stop_loss', 'exit_modes', 'take_profit', 'holding_period', 'trailing_stop', 'ma_period'):
            values = getattr(self, key)
            if len(set(values)) != len(values):
                raise ValueError(f'{key}: 重複があります')
        allowed = {'high_period': {120, 180, 252}, 'entry_offset': {1, 2, 3, 5}, 'ma_period': {5, 20, 50}}
        for key, values in allowed.items():
            if not set(getattr(self, key)) <= values:
                raise ValueError(f'{key}: 候補が不正です')
        for key in ('stop_loss', 'trailing_stop'):
            if not all(0 < x < 1 for x in getattr(self, key)):
                raise ValueError(f'{key}: 0〜1の範囲で指定してください')
        for key in ('revenue_growth', 'earnings_growth', 'roe', 'reaction_rate', 'take_profit'):
            if not all(0 <= x <= 10 for x in getattr(self, key)):
                raise ValueError(f'{key}: 範囲外です')
        if not all(0 < x <= 100 for x in self.volume_ratio) or not all(self.per_min < x <= 1000 for x in self.per_max):
            raise ValueError('出来高またはPERが範囲外です')
        if self.cap_min >= self.cap_max or not all(1 <= x <= 1250 for x in self.holding_period):
            raise ValueError('時価総額または保有期間が範囲外です')
        return self


class PortfolioSettings(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    initial_capital: float = Field(1_000_000, ge=10_000, le=1e12)
    max_positions: int = Field(5, ge=1, le=50)
    benchmark: str = '^N225'
    @model_validator(mode='after')
    def valid(self):
        if self.benchmark not in ('^N225', '^TOPX'):
            raise ValueError('ベンチマークが不正です')
        return self


class TradingCosts(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    buy_cost_rate: float = Field(0, ge=0, le=.05)
    sell_cost_rate: float = Field(0, ge=0, le=.05)
    slippage_rate: float = Field(0, ge=0, le=.05)


def parameter_defaults(strategy_id):
    overrides = {'kenmo_earnings': {'volume_ratio': [2], 'high_enabled': False}, 'kenmo_growth': {'per_max': [30], 'high_enabled': False, 'volume_enabled': False}}
    return StrategyParameters(**overrides.get(strategy_id, {})).model_dump()


def portfolio_mode(c):
    return c.get('strategy_ids', ['bottom_volume']) != ['bottom_volume']


def parameter_grid(c):
    ids = c.get('strategy_ids', ['bottom_volume'])
    if not ids or len(set(ids)) != len(ids) or not set(ids) <= REGISTRY.keys():
        raise ValueError('戦略を1〜4種類選択してください')
    if not set(c.get('strategy_params', {})) <= set(REGISTRY) - {'bottom_volume'}:
        raise ValueError('戦略パラメータの対象が不正です')
    grids = []
    for strategy_id in ids:
        if strategy_id == 'bottom_volume':
            s = c['strategy']
            variants = [{'drawdown_threshold': dd, 'volume_ratio': vr, 'holding_period': h, 'exit_mode': 'legacy_close', 'stop_loss': 0, 'maximum_holding': h} for dd, vr, h in product(s['drawdown_thresholds'], s['volume_ratio_thresholds'], s['holding_periods'])]
        else:
            p = StrategyParameters(**{**parameter_defaults(strategy_id), **c.get('strategy_params', {}).get(strategy_id, {})}).model_dump()
            keys = []
            if strategy_id == 'kenmo_breakout' and p['high_enabled']:
                keys.append('high_period')
            if strategy_id in ('kenmo_breakout', 'kenmo_earnings') and p['volume_enabled']:
                keys.append('volume_ratio')
            if strategy_id == 'kenmo_earnings':
                keys.extend(['entry_offset', 'reaction_rate'])
            if p['mode'] == 'fundamentals':
                keys.extend(key for key in ('revenue_growth', 'earnings_growth', 'roe', 'per_max') if p[{'revenue_growth': 'revenue_enabled', 'earnings_growth': 'earnings_enabled', 'roe': 'roe_enabled', 'per_max': 'per_enabled'}[key]])
            keys.append('stop_loss')
            bases = [{**{k: v[0] if isinstance(v, list) and k != 'exit_modes' else v for k, v in p.items()}, **dict(zip(keys, values))} for values in product(*(p[key] for key in keys))]
            variants = []
            for base in bases:
                for mode in p['exit_modes']:
                    exit_key = {'fixed': 'take_profit', 'holding': 'holding_period', 'trailing': 'trailing_stop', 'ma': 'ma_period'}[mode]
                    for value in p[exit_key]:
                        variants.append({**base, 'exit_mode': mode, exit_key: value})
                        if len(variants) > 256:
                            raise ValueError('探索は合計256組み合わせ以下にしてください')
        for p in variants:
            grids.append({'strategy_id': strategy_id, 'parameter_id': fingerprint({'strategy': strategy_id, 'p': p})[:16], 'parameters': p})
        if len(grids) > 256:
            raise ValueError('探索は合計256組み合わせ以下にしてください')
    return grids
