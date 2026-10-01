from itertools import product
import numpy as np
import pandas as pd
from .metrics import calculate_metrics

PARAMETERS = ['drawdown_threshold', 'volume_ratio_threshold', 'holding_period']
GROUP_KEYS = ['period_type', 'market_cap_group', 'market_segment']


def aggregate_results(trades: pd.DataFrame, c: dict, *, intersections=False, full=False, progress=None) -> pd.DataFrame:
    eligible = trades[trades.trade_status.eq('complete')].copy()
    scopes = [('ALL', 'ALL', eligible)]
    scopes += [(b['name'], 'ALL', eligible[eligible.market_cap_group.eq(b['name'])]) for b in c['market_cap_bins']]
    scopes += [('ALL', m, eligible[eligible.market_segment.eq(m)]) for m in c['universe']['markets']]
    if intersections:
        scopes += [(b['name'], m, eligible[eligible.market_cap_group.eq(b['name']) & eligible.market_segment.eq(m)])
                   for b in c['market_cap_bins'] for m in c['universe']['markets']]
    rows = []
    s = c['strategy']
    periods = ('train', 'test', 'full') if full else ('train', 'test')
    total = len(scopes) * len(periods) * len(s['drawdown_thresholds']) * len(s['volume_ratio_thresholds']) * len(s['holding_periods'])
    for cap, market, scoped in scopes:
        grouped = {key: frame for key, frame in scoped.groupby(['period_type'] + PARAMETERS)}
        for period, dd, vr, h in product(periods, s['drawdown_thresholds'], s['volume_ratio_thresholds'], s['holding_periods']):
            subset = pd.concat([grouped.get((p, dd, vr, h), eligible.iloc[:0]) for p in ('train', 'test')]) if period == 'full' else grouped.get((period, dd, vr, h), eligible.iloc[:0])
            rows.append({'period_type': period, 'market_cap_group': cap, 'market_segment': market,
                         'drawdown_threshold': dd, 'volume_ratio_threshold': vr, 'holding_period': h,
                         **calculate_metrics(subset, c['validation'])})
            if progress and (len(rows) % 25 == 0 or len(rows) == total):
                progress(len(rows), total, f'{period} / {cap} / {market}')
    return add_robustness(pd.DataFrame(rows), c)


def add_robustness(results: pd.DataFrame, c: dict) -> pd.DataFrame:
    out = results.copy()
    out['robustness_score'] = np.nan
    out['robustness_neighbor_count'] = 0
    dds = sorted(c['strategy']['drawdown_thresholds'])
    vrs = sorted(c['strategy']['volume_ratio_thresholds'])
    for _, frame in out.groupby(GROUP_KEYS + ['holding_period']):
        cells = {(row.drawdown_threshold, row.volume_ratio_threshold): row for row in frame.itertuples()}
        for row in frame.itertuples():
            i, j = dds.index(row.drawdown_threshold), vrs.index(row.volume_ratio_threshold)
            neighbors = []
            for di, dj in product((-1, 0, 1), repeat=2):
                if (di or dj) and 0 <= i + di < len(dds) and 0 <= j + dj < len(vrs):
                    neighbor = cells[(dds[i + di], vrs[j + dj])]
                    if not neighbor.insufficient_sample and np.isfinite(neighbor.mean_return):
                        neighbors.append(neighbor.mean_return)
            if neighbors:
                out.at[row.Index, 'robustness_score'] = np.mean(neighbors)
                out.at[row.Index, 'robustness_neighbor_count'] = len(neighbors)
    return out


def select_candidates(results: pd.DataFrame, c: dict) -> pd.DataFrame:
    # Critical boundary: selection never reads Test outcomes.
    train = results[results.period_type.eq('train') & ~results.insufficient_sample & results.mean_return.notna()]
    parts = []
    for _, group in train.groupby(['market_cap_group', 'market_segment', 'holding_period']):
        selected = group.sort_values(['mean_return', 'median_return', 'profit_factor', 'ci95_lower', 'robustness_score'], ascending=False, na_position='last').head(c['validation'].get('top_candidates', 5)).copy()
        selected['candidate_rank'] = np.arange(1, len(selected) + 1)
        parts.append(selected)
    if not parts:
        return pd.DataFrame(columns=list(results.columns) + ['candidate_rank'])
    return pd.concat(parts, ignore_index=True)


def evaluate_candidates(candidates: pd.DataFrame, results: pd.DataFrame) -> pd.DataFrame:
    keys = ['market_cap_group', 'market_segment'] + PARAMETERS
    test = results[results.period_type.eq('test')]
    metrics = [col for col in results.columns if col not in keys + ['period_type']]
    merged = candidates.merge(test[keys + metrics], on=keys, how='left', suffixes=('_train', '_test'), validate='one_to_one')
    return merged
