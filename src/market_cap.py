from __future__ import annotations
import numpy as np
import pandas as pd


def cap_group(value: float, bins: list[dict]) -> str:
    if not np.isfinite(value):
        return 'missing'
    for b in bins:
        if value >= b['min'] and (b['max'] is None or value < b['max']):
            return b['name']
    return 'missing'


def attach_market_cap(df: pd.DataFrame, shares: pd.DataFrame | None, config: dict) -> pd.DataFrame:
    out = df.copy()
    out['historical_shares'] = np.nan
    out['shares_date'] = pd.NaT
    out['market_cap_quality'] = 'missing'
    out['market_cap_missing_reason'] = 'no_prior_shares'
    if shares is not None and not shares.empty:
        left = pd.DataFrame({'date': out.index})
        right = shares[['historical_shares']].reset_index()
        right.columns = ['shares_date', 'historical_shares']
        merged = pd.merge_asof(left.sort_values('date'), right.sort_values('shares_date'), left_on='date', right_on='shares_date', direction='backward')
        out['historical_shares'] = merged['historical_shares'].to_numpy()
        out['shares_date'] = merged['shares_date'].to_numpy()
        observed = out['historical_shares'].notna()
        out.loc[observed, 'market_cap_missing_reason'] = ''
        max_age = config.get('market_cap', {}).get('max_shares_age_days', 370)
        if max_age is not None:
            stale = (out.index.to_series() - out.shares_date).dt.days.gt(max_age)
            out.loc[stale, 'historical_shares'] = np.nan
            out.loc[stale, 'market_cap_missing_reason'] = 'stale_shares'
        if config.get('market_cap', {}).get('invalidate_shares_across_split', True):
            last_split = pd.Series(pd.NaT, index=out.index, dtype='datetime64[ns]')
            is_split = out['Stock Splits'].fillna(0).ne(0)
            last_split.loc[is_split] = out.index[is_split]
            across = out['shares_date'].lt(last_split.ffill())
            out.loc[across, 'historical_shares'] = np.nan
            out.loc[across, 'market_cap_missing_reason'] = 'shares_before_split'
    out['market_cap'] = out['Raw Close'] * out['historical_shares']
    valid = out.market_cap.gt(0) & np.isfinite(out.market_cap)
    out.loc[~valid, 'market_cap'] = np.nan
    out.loc[out.historical_shares.notna() & ~valid, 'market_cap_missing_reason'] = 'invalid_raw_close'
    out.loc[valid, 'market_cap_quality'] = 'historical_asof'
    exact = valid & out.shares_date.eq(out.index.to_series())
    out.loc[exact, 'market_cap_quality'] = 'historical_exact'
    out['market_cap_group'] = out.market_cap.map(lambda v: cap_group(v, config['market_cap_bins']))
    return out
