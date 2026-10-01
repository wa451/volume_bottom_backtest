from pathlib import Path
from functools import lru_cache
import numpy as np
import pandas as pd
from .utils import dates

PRICE_COLUMNS = ['Open', 'High', 'Low', 'Close', 'Adj Close', 'Volume']


def normalize_prices(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        raise ValueError('No price data returned')
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        raise ValueError('Select one ticker before normalizing prices')
    if missing := set(PRICE_COLUMNS) - set(df.columns):
        raise ValueError(f'Missing price columns: {sorted(missing)}')
    df.index = dates(df.index)
    df.index.name = 'Date'
    df = df[~df.index.duplicated(keep='last')].sort_index()
    # Drop action-only/nontrading rows, but preserve partially missing bars.
    df = df[df[PRICE_COLUMNS].notna().any(axis=1)]
    for col in PRICE_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    for col in ('Dividends', 'Stock Splits'):
        if col not in df:
            df[col] = np.nan  # Unknown action data is not silently zero-filled.
        else:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    if df.empty or not (df['Close'] > 0).any():
        raise ValueError('No valid closing prices')
    return df


def load_prices(path: Path) -> pd.DataFrame:
    return normalize_prices(pd.read_parquet(path))


@lru_cache(maxsize=8)
def exchange_sessions(start: str, end: str) -> pd.DatetimeIndex:
    import exchange_calendars as xc
    # Cover warmup ranges explicitly instead of the library's default horizon.
    cal = xc.get_calendar('XTKS', start=start, end=end)
    # Requested bounds may be holidays, before/after this calendar's first/last
    # session. Filter directly instead of parsing them as in-bounds sessions.
    sessions = dates(cal.sessions)
    return sessions[(sessions >= pd.Timestamp(start)) & (sessions <= pd.Timestamp(end))]


def align_sessions(df: pd.DataFrame) -> pd.DataFrame:
    sessions = exchange_sessions(str(df.index[0].date()), str(df.index[-1].date()))
    extra = df.loc[~df.index.isin(sessions)]
    if extra['Volume'].fillna(0).gt(0).any():
        raise ValueError('Positive-volume bar conflicts with Tokyo trading calendar')
    # Yahoo sometimes returns carried-forward, zero-volume bars on holidays.
    # Keep them in the source cache, but exclude them from business-day counts.
    out = df.reindex(sessions).copy()
    out.index.name = 'Date'
    out['missing_session'] = ~out.index.isin(df.index)
    out.attrs['nontrading_zero_volume_rows'] = len(extra)
    for col in ('split_excluded', 'split_adjustment_failed', 'stock_split_near_signal', 'Repaired?'):
        if col in out:
            out[col] = out[col].fillna(False).astype(bool)
    out.loc[out.missing_session, ['Stock Splits', 'Dividends']] = 0.0
    return out


def normalize_shares(series) -> pd.DataFrame:
    if series is None or len(series) == 0:
        return pd.DataFrame({'historical_shares': pd.Series(dtype=float)}, index=pd.DatetimeIndex([], name='Date'))
    df = series.to_frame('historical_shares') if isinstance(series, pd.Series) else series.copy()
    df.index = dates(df.index)
    df.index.name = 'Date'
    df['historical_shares'] = pd.to_numeric(df['historical_shares'], errors='coerce')
    df = df[df.historical_shares.gt(0)]
    # Conflicting same-day observations cannot safely be resolved by choosing one.
    conflicts = df.groupby(level=0).historical_shares.nunique()
    df = df[~df.index.isin(conflicts[conflicts > 1].index)]
    return df[~df.index.duplicated(keep='last')].sort_index()
