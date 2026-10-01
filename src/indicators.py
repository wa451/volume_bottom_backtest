import numpy as np
import pandas as pd


def calculate_indicators(df: pd.DataFrame, strategy: dict) -> pd.DataFrame:
    out = df.copy()
    out['rolling_high_252'] = out['Adj High'].shift(1).rolling(strategy['rolling_high_days'], min_periods=strategy['rolling_high_days']).max()
    out['drawdown'] = out['Adj Close'] / out['rolling_high_252'] - 1
    out['average_volume_20'] = out['SplitAdjustedVolume'].shift(1).rolling(strategy['volume_average_days'], min_periods=strategy['volume_average_days']).mean()
    out['volume_ratio'] = out['SplitAdjustedVolume'] / out['average_volume_20'].where(out['average_volume_20'].gt(0))
    out[['drawdown', 'volume_ratio']] = out[['drawdown', 'volume_ratio']].replace([np.inf, -np.inf], np.nan)
    return out
