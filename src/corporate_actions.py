from __future__ import annotations
import numpy as np
import pandas as pd


def future_split_factor(splits: pd.Series) -> pd.Series:
    """Product of splits STRICTLY AFTER each row; split-day prices use new units."""
    valid = splits.where(splits.gt(0) & np.isfinite(splits), 1.0)
    return valid.iloc[::-1].cumprod().iloc[::-1] / valid


def adjust_corporate_actions(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    out = df.copy()
    splits = out['Stock Splits']
    factor = future_split_factor(splits)
    out['future_split_factor'] = factor
    # Preserve the returned columns, since Yahoo's 'Close' is NOT the historical
    # raw close on pre-split dates, even with auto_adjust=False.
    price_basis = config['data'].get('price_basis', 'yahoo_split_adjusted')
    volume_basis = config['data'].get('volume_basis', 'yahoo_split_adjusted')
    action_known = splits.notna().all() and not ((splits < 0) | ~np.isfinite(splits)).any()
    for col in ('Open', 'High', 'Low', 'Close'):
        out['Raw ' + col] = out[col] * factor if price_basis == 'yahoo_split_adjusted' else out[col]
        out.loc[out['Raw ' + col].le(0), 'Raw ' + col] = np.nan
    ratio = out['Adj Close'] / out['Raw Close']
    ratio = ratio.where(np.isfinite(ratio) & ratio.gt(0))
    out['adjustment_ratio'] = ratio
    for col in ('Open', 'High', 'Low'):
        out['Adj ' + col] = out['Raw ' + col] * ratio
    if volume_basis == 'yahoo_split_adjusted':
        out['Raw Volume'] = out['Volume'] / factor
    else:
        out['Raw Volume'] = out['Volume']
    if config['split_handling']['adjust_volume']:
        out['SplitAdjustedVolume'] = out['Raw Volume'] * factor
    else:
        out['SplitAdjustedVolume'] = out['Raw Volume']
    out.loc[out.SplitAdjustedVolume.lt(0), 'SplitAdjustedVolume'] = np.nan
    out['split_adjustment_failed'] = False
    # Provider repair might still leave a split-sized price discontinuity. Flag,
    # never infer a correction from future returns or silently change the basis.
    normalized_close = out['Raw Close'] / factor
    jump = normalized_close / normalized_close.shift(1)
    for i in np.flatnonzero(splits.fillna(0).ne(0).to_numpy()):
        split = splits.iloc[i]
        if i and split > 0 and not np.isclose(split, 1):
            ratio_i = jump.iloc[i]
            expected_bad = 1 / split
            if np.isfinite(ratio_i) and abs(np.log(ratio_i / expected_bad)) < 0.15 and abs(np.log(ratio_i)) > 0.25:
                out.iloc[i, out.columns.get_loc('split_adjustment_failed')] = True
        if not config['split_handling']['adjust_volume']:
            out.iloc[i, out.columns.get_loc('split_adjustment_failed')] = True
    if not action_known:
        # Unknown split history prevents reliable raw-price reconstruction.
        out['split_adjustment_failed'] = True
        out['Raw Close'] = np.nan
        out['Raw Open'] = np.nan
    window = config['split_handling']['exclusion_window_days']
    out['stock_split_near_signal'] = False
    out['split_excluded'] = False
    # Use only events known on or BEFORE the signal (no pre-event future mask).
    # Exclusion lasts at least the volume lookback so its window clears.
    recovery = max(window, config['strategy']['volume_average_days'])
    for i in np.flatnonzero(splits.fillna(0).ne(0).to_numpy()):
        out.iloc[i:i + window + 1, out.columns.get_loc('stock_split_near_signal')] = True
        if out['split_adjustment_failed'].iloc[i] and config['split_handling']['exclude_if_adjustment_failed']:
            out.iloc[i:i + recovery + 1, out.columns.get_loc('split_excluded')] = True
    if not action_known and config['split_handling']['exclude_if_adjustment_failed']:
        out['split_excluded'] = True
    return out
