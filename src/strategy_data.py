"""Incremental Yahoo auxiliary caches. Financial observations are never backdated."""
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf
from .utils import atomic_parquet, atomic_json, read_json

FINANCIAL_COLUMNS = ['available_at', 'revenue_growth', 'earnings_growth', 'roe', 'trailing_eps', 'source', 'fiscal_period']


def _growth(statement, names):
    periods = sorted(statement.columns, reverse=True)[:2]
    if len(periods) < 2 or not 300 <= (pd.Timestamp(periods[0]) - pd.Timestamp(periods[1])).days <= 430:
        return np.nan
    for name in names:
        if name not in statement.index:
            continue
        values = pd.to_numeric(statement.loc[name].reindex(periods), errors='coerce')
        if np.isfinite(values).all() and values.iloc[1] > 0:
            return float(values.iloc[0] / values.iloc[1] - 1)
    return np.nan


def fetch_fundamentals(ticker, now):
    company = yf.Ticker(ticker)
    statement = company.get_income_stmt(freq='yearly')
    info = company.get_info()
    if statement is None or statement.empty or not info:
        raise ValueError('Yahoo財務データがありません')
    earnings = _growth(statement, ['DilutedEPS', 'BasicEPS'])
    if not np.isfinite(earnings):
        earnings = _growth(statement, ['NetIncome', 'NetIncomeCommonStockholders'])
    return pd.DataFrame([{'available_at': now, 'revenue_growth': _growth(statement, ['TotalRevenue', 'OperatingRevenue']), 'earnings_growth': earnings,
                          'roe': info.get('returnOnEquity', np.nan), 'trailing_eps': info.get('trailingEps', np.nan),
                          'source': 'yahoo_observed_snapshot', 'fiscal_period': str(max(statement.columns))}])


def fetch_earnings(ticker, initial):
    frame = yf.Ticker(ticker).get_earnings_dates(limit=100 if initial else 12)
    if frame is None:
        raise ValueError('Yahoo決算日データがありません')
    rows = []
    for when, row in frame.iterrows():
        # Exclude forecasts/scheduled announcements, even if a date is in the past.
        reported = row.get('Reported EPS', np.nan)
        if pd.isna(reported):
            continue
        timestamp = pd.Timestamp(when)
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize('Asia/Tokyo')
        timestamp = timestamp.tz_convert('Asia/Tokyo')
        rows.append({'released_at': timestamp.isoformat(), 'timing_known': bool(timestamp.hour or timestamp.minute), 'reported_eps': float(reported), 'source': 'yahoo_reported_earnings_calendar'})
    return pd.DataFrame(rows, columns=['released_at', 'timing_known', 'reported_eps', 'source'])


def update_auxiliary(root: Path, tickers, outcome, retry_failed=False, failures=(), now=None):
    now = pd.Timestamp(now or pd.Timestamp.now(tz='UTC'))
    if now.tzinfo is None:
        now = now.tz_localize('UTC')
    for ticker in dict.fromkeys(tickers):
        for kind, folder, ttl in [('earnings', 'earnings', 1), ('fundamentals', 'fundamentals', 7)]:
            if retry_failed and (ticker, kind) not in failures:
                continue
            path = root / f'data/{folder}/{ticker}.parquet'
            meta_path = path.with_suffix('.json')
            try:
                meta = read_json(meta_path)
                old = pd.read_parquet(path) if path.exists() else None
                fetched = pd.Timestamp(meta['fetched_at']) if meta.get('fetched_at') else None
                if not retry_failed and old is not None and fetched is not None and now - fetched < pd.Timedelta(days=ttl):
                    outcome(ticker, kind, 'cached')
                    continue
                fresh = fetch_earnings(ticker, old is None or fetched is None or now - fetched > pd.Timedelta(days=365)) if kind == 'earnings' else fetch_fundamentals(ticker, now)
                # Acquisition may finish later than it started. Only completion
                # time can establish what was available to an investor.
                if kind == 'fundamentals':
                    observed = max(now, pd.Timestamp.now(tz='UTC'))
                    fresh['available_at'] = observed
                else:
                    fresh = fresh[pd.to_datetime(fresh.released_at, utc=True) <= now]
                merged = pd.concat([old, fresh], ignore_index=True) if old is not None else fresh
                key = 'released_at' if kind == 'earnings' else 'available_at'
                merged = merged.drop_duplicates(key, keep='last').sort_values(key).reset_index(drop=True)
                atomic_parquet(merged, path)
                atomic_json({'fetched_at': now.isoformat(), 'source': 'yahoo', 'initial_window': 100, 'update_window': 12, 'pit_policy': 'financial_observation_time_only'}, meta_path)
                outcome(ticker, kind, 'downloaded')
            except Exception as exc:
                # No successful write occurred: the previous usable cache survives.
                outcome(ticker, kind, 'failed', str(exc))


def load_strategy_data(root, ticker, frame):
    f = pd.DataFrame(np.nan, index=frame.index, columns=['revenue_growth', 'earnings_growth', 'roe', 'per'])
    earnings = []
    errors = []
    fp = root / f'data/fundamentals/{ticker}.parquet'
    ep = root / f'data/earnings/{ticker}.parquet'
    if fp.exists():
        try:
            snapshots = pd.read_parquet(fp)
            snapshots['available_at'] = pd.to_datetime(snapshots.available_at, utc=True).astype('datetime64[ns, UTC]')
            if not snapshots.source.eq('yahoo_observed_snapshot').all():
                raise ValueError('財務キャッシュの公表時点・出所を検証できません')
            snapshots = snapshots.dropna(subset=['available_at']).sort_values('available_at').drop_duplicates('available_at', keep='last')
            # Tokyo close moved to 15:30 on 2024-11-05. Never truncate to date.
            close = pd.Series(frame.index.tz_localize('Asia/Tokyo').tz_convert('UTC'), index=frame.index)
            close += pd.to_timedelta(np.where(frame.index >= pd.Timestamp('2024-11-05'), 930, 900), unit='m')
            joined = pd.merge_asof(pd.DataFrame({'close_time': close}), snapshots, left_on='close_time', right_on='available_at', direction='backward')
            joined.index = frame.index
            valid = (joined.close_time - joined.available_at).le(pd.Timedelta(days=366))
            for column in ('revenue_growth', 'earnings_growth', 'roe'):
                f[column] = pd.to_numeric(joined[column], errors='coerce').replace([np.inf, -np.inf], np.nan).where(valid)
            # EPS is a per-share quantity. A split since observation invalidates it.
            split_dates = pd.Series(frame.index.where(frame['Stock Splits'].fillna(0).ne(0)), index=frame.index).ffill()
            split_at = pd.to_datetime(split_dates).dt.tz_localize('Asia/Tokyo').dt.tz_convert('UTC')
            valid &= split_at.isna() | split_at.le(joined.available_at)
            eps = pd.to_numeric(joined.trailing_eps, errors='coerce')
            f['per'] = (frame['Raw Close'] / eps.where(eps.gt(0))).where(valid)
        except (ValueError, KeyError, OSError, TypeError) as exc:
            f.loc[:, :] = np.nan
            errors.append('fundamentals: ' + str(exc))
    if ep.exists():
        try:
            cache = pd.read_parquet(ep)
            cache = cache[cache.reported_eps.notna() & cache.source.eq('yahoo_reported_earnings_calendar')]
            released = pd.to_datetime(cache.released_at, utc=True, errors='coerce')
            if released.isna().any():
                errors.append('earnings: 決算日時が不正な行を除外')
            cache = cache.loc[released.notna()].copy()
            cache['released_at'] = released.loc[released.notna()].map(lambda t: t.isoformat())
            cache['timing_known'] = cache.timing_known.fillna(False).eq(True)
            earnings = cache.to_dict('records')
        except (ValueError, KeyError, OSError, TypeError) as exc:
            errors.append('earnings: ' + str(exc))
    return {'fundamentals': f, 'earnings': earnings, 'listing_date': None, 'errors': errors}
