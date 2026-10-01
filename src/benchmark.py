from pathlib import Path
import numpy as np
import pandas as pd
from .data_loader import load_prices


def load_benchmarks(root: Path, config: dict) -> dict:
    result = {}
    if config.get('benchmark', {}).get('enabled', True):
        for ticker in config['benchmark']['tickers']:
            path = root / f'data/benchmark/{ticker}.parquet'
            if path.exists():
                try:
                    df = load_prices(path)
                    ratio = df['Adj Close'] / df['Close'].where(df.Close.gt(0))
                    df['Adj Open'] = df['Open'] * ratio
                    result[ticker] = df
                except (ValueError, OSError):
                    continue
    return result


def benchmark_return(benchmarks: dict, entry_date, exit_date):
    # Exact trading dates only: no interpolation and no future as-of price.
    for ticker, df in benchmarks.items():
        if entry_date in df.index and exit_date in df.index:
            entry, exit_ = df.at[entry_date, 'Adj Open'], df.at[exit_date, 'Adj Close']
            if np.isfinite(entry) and entry > 0 and np.isfinite(exit_):
                return ticker, exit_ / entry - 1
    return '', np.nan
