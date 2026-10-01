from __future__ import annotations
import numpy as np
import pandas as pd


def bootstrap_ci(values, samples=2000, seed=42, clusters=None):
    values = np.asarray(values, dtype=float)
    valid = np.isfinite(values)
    values = values[valid]
    if len(values) < 2:
        return np.nan, np.nan
    rng = np.random.default_rng(seed)
    if clusters is not None:
        clusters = np.asarray(clusters)[valid]
        group = pd.DataFrame({'value': values, 'cluster': clusters}).groupby('cluster').value.agg(['sum', 'count'])
        sums, counts = group['sum'].to_numpy(), group['count'].to_numpy()
        if len(sums) < 2:
            return np.nan, np.nan  # A single cluster cannot measure between-stock uncertainty.
    else:
        sums, counts = values, np.ones(len(values))
    n = len(sums)
    means = np.empty(samples)
    block = max(1, min(256, 1_000_000 // n))
    for start in range(0, samples, block):
        end = min(samples, start + block)
        indices = rng.integers(0, n, size=(end - start, n))
        means[start:end] = sums[indices].sum(axis=1) / counts[indices].sum(axis=1)
    return tuple(np.quantile(means, [0.025, 0.975]))


def calculate_metrics(trades: pd.DataFrame, validation: dict) -> dict:
    finite = trades[np.isfinite(trades['return'].to_numpy(dtype=float))]
    r = finite['return'].to_numpy(float)
    n = len(r)
    win, loss = r[r > 0], r[r < 0]
    keys = ['win_rate', 'mean_return', 'median_return', 'average_win', 'average_loss', 'max_profit',
            'max_loss', 'profit_factor', 'expectancy', 'std_return', 'p25', 'p75', 'ci95_lower', 'ci95_upper']
    metrics = {k: np.nan for k in keys}
    if n:
        profit_factor = win.sum() / abs(loss.sum()) if len(loss) else (np.inf if len(win) else np.nan)
        average_win, average_loss = (win.mean() if len(win) else 0.0), (loss.mean() if len(loss) else 0.0)
        clusters = finite['ticker'].to_numpy() if validation.get('bootstrap_unit', 'ticker') == 'ticker' else None
        lower, upper = bootstrap_ci(r, validation.get('bootstrap_samples', 2000), validation.get('bootstrap_seed', 42), clusters)
        metrics.update(win_rate=len(win) / n, mean_return=r.mean(), median_return=np.median(r),
                       average_win=average_win, average_loss=average_loss, max_profit=r.max(), max_loss=r.min(),
                       profit_factor=profit_factor, expectancy=len(win) / n * average_win + len(loss) / n * average_loss,
                       std_return=r.std(ddof=1) if n > 1 else np.nan, p25=np.quantile(r, .25), p75=np.quantile(r, .75),
                       ci95_lower=lower, ci95_upper=upper)
    metrics.update(num_trades=n, num_tickers=int(finite.ticker.nunique()),
                   insufficient_sample=n < validation['minimum_trades'],
                   bootstrap_ci_available=bool(np.isfinite(metrics['ci95_lower'])))
    metrics['num_signals'] = len(finite.drop_duplicates(['ticker', 'signal_date'])) if 'signal_date' in finite else n
    metrics['benchmark_coverage'] = float(finite.benchmark_return.notna().mean()) if n and 'benchmark_return' in finite else np.nan
    metrics['mean_excess_return'] = finite.excess_return.mean() if n and 'excess_return' in finite else np.nan
    return metrics
