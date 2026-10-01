import numpy as np
import pandas as pd


def signal_mask(df: pd.DataFrame, drawdown: float, volume: float) -> pd.Series:
    return df.drawdown.le(-drawdown) & df.volume_ratio.ge(volume)


def apply_cooldown(mask: pd.Series, days: int) -> np.ndarray:
    positions = []
    last = -days - 1
    for i in np.flatnonzero(mask.fillna(False).to_numpy()):
        # A signal at t suppresses exactly t+1 through t+days.
        if i - last > days:
            positions.append(i)
            last = i
    return np.asarray(positions, dtype=int)
