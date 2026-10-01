from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

METRIC_COLUMNS = {'trade_count': 'num_trades', 'bootstrap_ci_lower': 'ci95_lower'}
PERCENT_METRICS = {'mean_return', 'median_return', 'win_rate', 'expectancy', 'bootstrap_ci_lower'}


def generate_heatmaps(results: pd.DataFrame, root: Path, c: dict) -> int:
    s = c['strategy']
    count = 0
    metrics = c.get('output', {}).get('heatmap_metrics', list(PERCENT_METRICS) + ['profit_factor', 'trade_count'])
    for (period, h), holding in results.groupby(['period_type', 'holding_period']):
        for metric in metrics:
            col = METRIC_COLUMNS.get(metric, metric)
            finite = holding.loc[holding.num_trades.gt(0), col].replace([np.inf, -np.inf], np.nan).dropna()
            if finite.empty:
                if not holding.loc[holding.num_trades.gt(0), col].notna().any():
                    continue
                lo, hi = 0.0, 1.0  # All-infinite Profit Factor still gets a chart.
            else:
                lo, hi = finite.min(), finite.max()
            if metric not in ('win_rate', 'trade_count', 'profit_factor'):
                hi = max(abs(lo), abs(hi), 1e-6)
                lo = -hi
            elif hi == lo:
                hi = lo + max(abs(lo) * .1, 1e-6)
            for (cap, market), group in holding.groupby(['market_cap_group', 'market_segment']):
                if group.num_trades.sum() == 0:
                    continue
                matrix = group.pivot(index='drawdown_threshold', columns='volume_ratio_threshold', values=col).reindex(index=sorted(s['drawdown_thresholds']), columns=sorted(s['volume_ratio_thresholds']))
                counts = group.pivot(index='drawdown_threshold', columns='volume_ratio_threshold', values='num_trades').reindex_like(matrix)
                raw = matrix.to_numpy(float)
                values = np.where(counts.to_numpy() > 0, raw, np.nan)
                values = np.where(np.isposinf(values), hi, values)
                fig, ax = plt.subplots(figsize=(7.5, 5.6))
                cmap = plt.get_cmap('RdYlGn' if lo < 0 else 'YlGnBu').with_extremes(bad='#eeeeee')
                img = ax.imshow(np.ma.masked_invalid(values), cmap=cmap, vmin=lo, vmax=hi, aspect='auto')
                for i in range(len(matrix.index)):
                    for j in range(len(matrix.columns)):
                        n = int(counts.iloc[i, j])
                        value = raw[i, j]
                        label = '—' if not n or np.isnan(value) else ('inf' if np.isinf(value) else (f'{value:.1%}' if metric in PERCENT_METRICS else f'{value:.2f}' if metric != 'trade_count' else str(int(value))))
                        if n and n < c['validation']['minimum_trades']:
                            label += '*'
                        ax.text(j, i, label, ha='center', va='center', fontsize=9)
                ax.set_xticks(range(len(matrix.columns)), [f'{v:g}x' for v in matrix.columns])
                ax.set_yticks(range(len(matrix.index)), [f'-{v:.0%}' for v in matrix.index])
                ax.set_xlabel('Volume / previous average')
                ax.set_ylabel('Drawdown threshold')
                scope = cap if cap != 'ALL' else market
                ax.set_title(f'{period.upper()} | {scope} | {h} trading days\n{metric}')
                colorbar = fig.colorbar(img, ax=ax, shrink=.8)
                if metric in PERCENT_METRICS:
                    colorbar.ax.yaxis.set_major_formatter(PercentFormatter(xmax=1))
                fig.tight_layout(rect=(0, .05, 1, 1))
                fig.text(.5, .012, f'* fewer than {c["validation"]["minimum_trades"]} trades; same scale across groups', ha='center', fontsize=8)
                name = cap if market == 'ALL' else f'market_{market}'
                folder = root / f'results/heatmaps/{period}/{h}d'
                folder.mkdir(parents=True, exist_ok=True)
                fig.savefig(folder / f'{name.lower()}_{metric}.png', dpi=140)
                plt.close(fig)
                count += 1
    return count
