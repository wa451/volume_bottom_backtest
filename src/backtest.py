from __future__ import annotations

from itertools import product
from pathlib import Path
import logging
import numpy as np
import pandas as pd
from tqdm import tqdm
from .utils import atomic_parquet, atomic_json, read_json, fingerprint, today, last_completed_date
from .data_loader import load_prices, normalize_shares, PRICE_COLUMNS, align_sessions
from .corporate_actions import adjust_corporate_actions
from .indicators import calculate_indicators
from .market_cap import attach_market_cap
from .signals import apply_cooldown
from .strategies import REGISTRY
from .benchmark import load_benchmarks, benchmark_return

log = logging.getLogger(__name__)
TRADE_COLUMNS = ['code', 'ticker', 'company_name', 'market_segment', 'sector', 'signal_date',
                 'signal_price', 'drawdown_threshold', 'volume_ratio_threshold', 'actual_drawdown', 'actual_volume_ratio',
                 'rolling_high_252', 'average_volume_20', 'entry_date', 'entry_price', 'raw_entry_price',
                 'adjusted_entry_price', 'holding_period', 'exit_date', 'exit_price', 'raw_exit_price',
                 'adjusted_exit_price', 'return', 'gross_return', 'historical_shares', 'shares_date',
                 'market_cap', 'market_cap_group', 'market_cap_quality', 'market_cap_missing_reason',
                 'stock_split_near_signal', 'period_type', 'trade_status', 'price_basis',
                 'benchmark_ticker', 'benchmark_return', 'excess_return']


def period_type(date, c: dict) -> str:
    for name in ('train', 'test'):
        bounds = c[name]
        end = pd.Timestamp(bounds['end']) if bounds['end'] else today()
        if pd.Timestamp(bounds['start']) <= date <= end:
            return name
    return 'outside'


def ticker_trades(features: pd.DataFrame, info: dict, c: dict, benchmarks=None):
    benchmarks = benchmarks or {}
    s = c['strategy']
    end = min(pd.Timestamp(c['data']['end_date']), last_completed_date()) if c['data']['end_date'] else last_completed_date()
    df = features.loc[:end]
    analysis_mask = (df.index >= pd.Timestamp(c['data']['start_date'])) & (df.index <= end)
    valid_bar = df['Adj Close'].gt(0) & df['Volume'].gt(0)
    cap_groups = c.get('analysis', {}).get('market_cap_groups', ['ALL'])
    if 'ALL' not in cap_groups:
        valid_bar = valid_bar & df.market_cap_group.isin(cap_groups)
    rows, excluded = [], 0
    for dd, vr in product(s['drawdown_thresholds'], s['volume_ratio_thresholds']):
        mask = REGISTRY['bottom_volume'].entry_signals(df, {'drawdown_threshold': dd, 'volume_ratio': vr}, {}) & analysis_mask & valid_bar
        excluded += int((mask & df.split_excluded).sum())
        for pos in apply_cooldown(mask & ~df.split_excluded, s['signal_cooldown_days']):
            signal_date = df.index[pos]
            period = period_type(signal_date, c)
            if period == 'outside':
                continue
            signal = df.iloc[pos]
            entry_pos = pos + 1
            entry = df.iloc[entry_pos] if entry_pos < len(df) else None
            entry_date = df.index[entry_pos] if entry is not None else pd.NaT
            for h in s['holding_periods']:
                exit_pos = entry_pos + h
                exit_ = df.iloc[exit_pos] if exit_pos < len(df) else None
                exit_date = df.index[exit_pos] if exit_ is not None else pd.NaT
                status = 'complete'
                if entry is None or exit_ is None:
                    status = 'incomplete'
                elif not all(np.isfinite(v) and v > 0 for v in (entry['Raw Open'], entry['Adj Open'], exit_['Raw Close'], exit_['Adj Close'])) or entry['Volume'] <= 0 or exit_['Volume'] <= 0:
                    status = 'invalid_price'
                period_end = pd.Timestamp(c[period]['end']) if c[period]['end'] else end
                if status == 'complete' and (entry_date > period_end or exit_date > period_end):
                    status = 'boundary_purged'
                raw_entry = entry['Raw Open'] if entry is not None else np.nan
                adj_entry = entry['Adj Open'] if entry is not None else np.nan
                raw_exit = exit_['Raw Close'] if exit_ is not None else np.nan
                adj_exit = exit_['Adj Close'] if exit_ is not None else np.nan
                slip = c['cost']['slippage_rate']
                entry_price = raw_entry * (1 + slip) * (1 + c['cost']['buy_cost_rate'])
                gross, net, exit_price = np.nan, np.nan, np.nan
                bench_ticker, bench_return = '', np.nan
                if status == 'complete':
                    gross = adj_exit / adj_entry - 1
                    # Exit is on the ENTRY-date raw-price unit, including dividend
                    # adjustment, so entry_price and exit_price always share a basis.
                    exit_price = raw_entry * (1 + gross) * (1 - slip) * (1 - c['cost']['sell_cost_rate'])
                    net = exit_price / entry_price - 1
                    bench_ticker, bench_return = benchmark_return(benchmarks, entry_date, exit_date)
                rows.append({**{key: info[key] for key in ('code', 'ticker', 'company_name', 'market_segment', 'sector')},
                             'signal_date': signal_date, 'signal_price': signal['Raw Close'],
                             'drawdown_threshold': dd, 'volume_ratio_threshold': vr,
                             'actual_drawdown': signal.drawdown, 'actual_volume_ratio': signal.volume_ratio,
                             'rolling_high_252': signal.rolling_high_252, 'average_volume_20': signal.average_volume_20,
                             'entry_date': entry_date, 'entry_price': entry_price, 'raw_entry_price': raw_entry,
                             'adjusted_entry_price': adj_entry, 'holding_period': h, 'exit_date': exit_date,
                             'exit_price': exit_price, 'raw_exit_price': raw_exit, 'adjusted_exit_price': adj_exit,
                             'return': net, 'gross_return': gross, 'historical_shares': signal.historical_shares,
                             'shares_date': signal.shares_date, 'market_cap': signal.market_cap,
                             'market_cap_group': signal.market_cap_group, 'market_cap_quality': signal.market_cap_quality,
                             'market_cap_missing_reason': signal.market_cap_missing_reason,
                             'stock_split_near_signal': signal.stock_split_near_signal, 'period_type': period,
                             'trade_status': status, 'price_basis': 'entry_date_raw_equivalent_total_return',
                             'benchmark_ticker': bench_ticker, 'benchmark_return': bench_return,
                             'excess_return': net - bench_return})
    return pd.DataFrame(rows, columns=TRADE_COLUMNS), excluded


def prepare_features(root: Path, ticker: str, c: dict):
    price_path = root / f'data/market/{ticker}.parquet'
    shares_path = root / f'data/shares/{ticker}.parquet'
    feature_path = root / f'data/features/{ticker}.parquet'
    meta_path = feature_path.with_suffix('.json')
    def signature(path):
        return [path.stat().st_size, path.stat().st_mtime_ns] if path.exists() else None
    key = fingerprint({'prices': signature(price_path), 'shares': signature(shares_path),
                       'data': c['data'], 'strategy': c['strategy'], 'splits': c['split_handling'],
                       'bins': c['market_cap_bins'], 'cap': c.get('market_cap', {}), 'version': 4})
    if feature_path.exists() and read_json(meta_path).get('key') == key:
        return pd.read_parquet(feature_path)
    prices = load_prices(price_path)
    shares, shares_error = None, ''
    if shares_path.exists():
        try:
            shares = normalize_shares(pd.read_parquet(shares_path))
        except (ValueError, OSError, KeyError) as e:
            shares_error = str(e)
            log.warning('Invalid shares cache for %s; analyzing without market cap: %s', ticker, e)
    df = attach_market_cap(calculate_indicators(align_sessions(adjust_corporate_actions(prices, c)), c['strategy']), shares, c)
    if shares_error:
        df['market_cap_missing_reason'] = 'invalid_shares_cache'
    df.attrs['shares_cache_error'] = shares_error
    atomic_parquet(df, feature_path)
    atomic_json({'key': key}, meta_path)
    return df


def run_backtest(root: Path, universe: pd.DataFrame, c: dict, progress=None):
    frames, quality = [], []
    benchmarks = load_benchmarks(root, c)
    for number, info in enumerate(tqdm(universe.to_dict('records'), desc='backtest')):
        if progress:
            progress(number, len(universe), info['ticker'])
        ticker = info['ticker']
        q = {**info, 'price_success': False, 'shares_success': False, 'split_events': 0,
             'missing_cells': 0, 'repaired_rows': 0, 'repair_flag_available': False,
             'excluded_signal_parameter_pairs': 0, 'error': '', 'shares_error': ''}
        q['missing_sessions'] = 0
        q['nontrading_zero_volume_rows'] = 0
        path = root / f'data/market/{ticker}.parquet'
        if not path.exists():
            q['error'] = 'price_cache_missing'
            quality.append(q)
            continue
        try:
            df = prepare_features(root, ticker, c)
            q.update(price_success=True, shares_success=bool(df.historical_shares.notna().any()),
                     split_events=int(df['Stock Splits'].fillna(0).ne(0).sum()),
                     missing_cells=int(df[PRICE_COLUMNS].isna().sum().sum()),
                     repaired_rows=int(df['Repaired?'].fillna(False).sum()) if 'Repaired?' in df else 0,
                     repair_flag_available='Repaired?' in df,
                     first_bar=str(df.index[0].date()), last_bar=str(df.index[-1].date()),
                     indicator_ready_rows=int(df.drawdown.notna().sum()))
            q['missing_sessions'] = int(df.missing_session.sum())
            q['shares_error'] = df.attrs.get('shares_cache_error', '')
            q['nontrading_zero_volume_rows'] = df.attrs.get('nontrading_zero_volume_rows', 0)
            trades, excluded = ticker_trades(df, info, c, benchmarks)
            q['excluded_signal_parameter_pairs'] = excluded
            if not trades.empty:
                frames.append(trades)
        except (ValueError, OSError, KeyError) as e:
            q['error'] = str(e)
            log.warning('Cannot analyze %s: %s', ticker, e)
        quality.append(q)
    trades = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=TRADE_COLUMNS)
    if progress:
        progress(len(universe), len(universe), '取引の保存')
    dest = root / 'results'
    atomic_parquet(trades, dest / 'trades.parquet')
    trades.to_csv(dest / 'trades.csv', index=False)
    pd.DataFrame(quality).to_csv(dest / 'logs/backtest_ticker_quality.csv', index=False)
    atomic_json({'config': c, 'config_fingerprint': fingerprint(c), 'created_at': pd.Timestamp.now(tz='Asia/Tokyo').isoformat(),
                 'universe_count': len(universe), 'universe_codes': universe.code.tolist(),
                 'complete_trades': int(trades.trade_status.eq('complete').sum()),
                 'analysis_type': 'event_study', 'benchmark_tickers_available': list(benchmarks)}, dest / 'run.json')
    return trades
