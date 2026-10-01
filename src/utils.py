from __future__ import annotations

import hashlib
import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]


def today() -> pd.Timestamp:
    return pd.Timestamp(datetime.now(ZoneInfo('Asia/Tokyo')).date())


def last_completed_date() -> pd.Timestamp:
    now = datetime.now(ZoneInfo('Asia/Tokyo'))
    day = pd.Timestamp(now.date())
    return day if now.hour >= 16 else day - pd.Timedelta(days=1)


def dates(index) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(pd.to_datetime(index))
    # Keep exchange-local dates rather than shifting midnight to UTC.
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    return idx.normalize().as_unit('ns')


def atomic_parquet(df: pd.DataFrame, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp.parquet')
    df.to_parquet(temp, index=True)
    temp.replace(path)


def atomic_json(value, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp.json')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    temp.replace(path)


def read_json(path: Path, default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else (default if default is not None else {})


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def load_config(path: Path | str = ROOT / 'config.yaml') -> dict:
    with open(path, encoding='utf-8') as f:
        config = yaml.safe_load(f)
    validate_config(config)
    return config


def validate_config(c: dict):
    if c['data']['provider'] != 'yfinance' or c['data']['interval'] != '1d':
        raise ValueError('Only yfinance daily data is supported')
    for key in ('price_basis', 'volume_basis'):
        if c['data'].get(key, 'yahoo_split_adjusted') not in ('raw', 'yahoo_split_adjusted'):
            raise ValueError(f'Invalid {key}')
    s = c['strategy']
    for key in ('rolling_high_days', 'volume_average_days'):
        if not isinstance(s[key], int) or s[key] < 1:
            raise ValueError(f'{key} must be a positive integer')
    for key in ('drawdown_thresholds', 'volume_ratio_thresholds', 'holding_periods'):
        values = s[key]
        if not values or len(set(values)) != len(values) or any(not np.isfinite(v) or v <= 0 for v in values):
            raise ValueError(f'Invalid {key}')
    if any(v >= 1 for v in s['drawdown_thresholds']):
        raise ValueError('Drawdown thresholds must be between 0 and 1')
    if any(not isinstance(v, int) for v in s['holding_periods']):
        raise ValueError('Holding periods must be integers')
    if s['signal_cooldown_days'] < 0 or not isinstance(s['signal_cooldown_days'], int):
        raise ValueError('Cooldown must be a nonnegative integer')
    if not c['universe']['ordinary_stocks_only']:
        raise ValueError('V1 only supports domestic ordinary stocks')
    if not set(c['universe']['markets']).issubset({'Prime', 'Standard', 'Growth'}):
        raise ValueError('Invalid markets')
    if pd.Timestamp(c['train']['end']) >= pd.Timestamp(c['test']['start']):
        raise ValueError('Train/Test must not overlap')
    for section in ('train', 'test'):
        if c[section]['end'] and pd.Timestamp(c[section]['start']) > pd.Timestamp(c[section]['end']):
            raise ValueError(f'Invalid {section} dates')
    if c['data']['end_date'] and pd.Timestamp(c['data']['start_date']) > pd.Timestamp(c['data']['end_date']):
        raise ValueError('Invalid analysis dates')
    for key in ('buy_cost_rate', 'sell_cost_rate', 'slippage_rate'):
        if not 0 <= c['cost'][key] < 1:
            raise ValueError(f'Invalid {key}')
    for key in ('batch_size', 'max_retries', 'threads', 'timeout_seconds', 'shares_chunk_years'):
        if c['download'].get(key, 1) <= 0:
            raise ValueError(f'{key} must be positive')
    if c['download']['retry_backoff_seconds'] < 0:
        raise ValueError('Backoff must be nonnegative')
    v = c['validation']
    if v['minimum_trades'] < 1 or v.get('bootstrap_samples', 2000) < 2:
        raise ValueError('Invalid validation settings')
    if v.get('bootstrap_unit', 'ticker') not in ('ticker', 'trade'):
        raise ValueError('Bootstrap unit must be ticker or trade')
    bins = c['market_cap_bins']
    if not bins or len({b['name'] for b in bins}) != len(bins):
        raise ValueError('Invalid market cap bins')
    previous = 0
    for i, b in enumerate(bins):
        if b['name'] in ('ALL', 'missing') or b['min'] != previous:
            raise ValueError('Market cap bins must be contiguous from zero, with distinct names')
        upper = b['max']
        if upper is None:
            if i != len(bins) - 1:
                raise ValueError('Only the last cap bin can be open-ended')
        elif upper <= b['min']:
            raise ValueError('Invalid cap bin bounds')
        previous = upper
    if bins[-1]['max'] is not None:
        raise ValueError('Last market cap bin must be open-ended')


def acquisition_start(c: dict) -> pd.Timestamp:
    days = max(c['data'].get('warmup_calendar_days', 550), int(c['strategy']['rolling_high_days'] * 1.7) + 90)
    return pd.Timestamp(c['data']['start_date']) - pd.Timedelta(days=days)


def init_dirs(root: Path):
    for folder in ('data/universe', 'data/market', 'data/shares', 'data/benchmark', 'data/features', 'results/logs'):
        (root / folder).mkdir(parents=True, exist_ok=True)
