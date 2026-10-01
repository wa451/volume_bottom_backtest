from itertools import product
import numpy as np
import pandas as pd
import pytest
from src.metrics import calculate_metrics, bootstrap_ci
from src.optimizer import add_robustness, select_candidates, aggregate_results, evaluate_candidates
from src.backtest import TRADE_COLUMNS
from src.visualization import generate_heatmaps
from src.benchmark import benchmark_return


def test_profit_factor_expectancy(config):
    trades = pd.DataFrame({'return': [.1, .2, -.1, 0], 'ticker': ['A','B','C','D']})
    m = calculate_metrics(trades, config['validation'])
    assert m['profit_factor'] == pytest.approx(3)
    assert m['expectancy'] == pytest.approx(.05)
    assert m['mean_return'] == pytest.approx(.05)
    assert m['win_rate'] == .5
    assert m['average_loss'] == -.1
    assert m['std_return'] == pytest.approx(np.std([.1,.2,-.1,0], ddof=1))
    assert m['insufficient_sample']


@pytest.mark.parametrize('values,pf', [([.1,.2], np.inf), ([-.1,-.2], 0)])
def test_no_wins_or_losses(values, pf, config):
    m = calculate_metrics(pd.DataFrame({'return': values, 'ticker': ['A','B']}), config['validation'])
    assert m['profit_factor'] == pf
    assert m['expectancy'] == pytest.approx(np.mean(values))


def test_bootstrap_deterministic_and_bounds():
    a = bootstrap_ci(np.arange(100)/100, samples=500, seed=12)
    b = bootstrap_ci(np.arange(100)/100, samples=500, seed=12)
    assert a == b
    assert a[0] < .495 < a[1]
    assert 0 <= a[0] <= a[1] <= .99
    assert np.isnan(bootstrap_ci([1])[0])


def test_cluster_bootstrap():
    low, high = bootstrap_ci([.1,.1,.3,.3], samples=500, seed=1, clusters=['A','A','B','B'])
    assert low == pytest.approx(.1)
    assert high == pytest.approx(.3)
    assert np.isnan(bootstrap_ci([.1,.2], clusters=['A','A'])[0])


def result_grid(config):
    config['strategy'].update(drawdown_thresholds=[.2,.3,.4], volume_ratio_thresholds=[2.,3.,4.], holding_periods=[20])
    return pd.DataFrame([{'period_type': p, 'market_cap_group': 'ALL', 'market_segment': 'ALL',
                         'drawdown_threshold': d, 'volume_ratio_threshold': v, 'holding_period': 20,
                         'num_trades': 100, 'mean_return': i/100, 'median_return': .1,
                         'profit_factor': 2., 'ci95_lower': -.1, 'insufficient_sample': False}
                         for p in ('train','test') for i,(d,v) in enumerate(product([.2,.3,.4],[2.,3.,4.]))])


def test_robustness_neighbor_only(config):
    r = result_grid(config)
    out = add_robustness(r, config)
    center = out[(out.period_type=='train') & (out.drawdown_threshold==.3) & (out.volume_ratio_threshold==3.)].iloc[0]
    assert center.robustness_neighbor_count == 8
    assert center.robustness_score == pytest.approx(np.mean([0,.01,.02,.03,.05,.06,.07,.08]))
    corner = out.iloc[0]
    assert corner.robustness_neighbor_count == 3
    assert corner.robustness_score == pytest.approx(np.mean([.01,.03,.04]))


def test_robustness_skips_insufficient(config):
    r = result_grid(config)
    r.loc[1, 'insufficient_sample'] = True
    r.loc[1, 'mean_return'] = 1000
    out = add_robustness(r, config)
    assert out.iloc[0].robustness_neighbor_count == 2
    assert out.iloc[0].robustness_score == pytest.approx(.035)


def test_test_data_cannot_change_selection(config):
    r = add_robustness(result_grid(config), config)
    before = select_candidates(r, config)
    r.loc[r.period_type.eq('test'), ['mean_return','median_return','profit_factor','ci95_lower','robustness_score']] = 999
    after = select_candidates(r, config)
    pd.testing.assert_frame_equal(before, after)
    evaluated = evaluate_candidates(before, r)
    assert evaluated.mean_return_test.eq(999).all()


def test_empty_full_grid_and_no_candidates(config):
    empty = pd.DataFrame(columns=TRADE_COLUMNS)
    r = aggregate_results(empty, config)
    assert len(r) == 2*10*25*4
    assert r.num_trades.eq(0).all()
    assert r.insufficient_sample.all()
    assert select_candidates(r, config).empty
    assert evaluate_candidates(select_candidates(r, config), r).empty


def test_missing_cap_only_excluded_from_cap_scopes(config):
    config['strategy'].update(drawdown_thresholds=[.2], volume_ratio_thresholds=[2.], holding_periods=[20])
    t = pd.DataFrame([{'ticker': 'A', 'period_type': 'train', 'drawdown_threshold': .2, 'volume_ratio_threshold': 2.,
                       'holding_period': 20, 'trade_status': 'complete', 'return': .1, 'market_cap_group': 'missing', 'market_segment': 'Prime'}])
    r = aggregate_results(t, config)
    train = r[r.period_type.eq('train')]
    assert train[(train.market_cap_group=='ALL') & (train.market_segment=='ALL')].num_trades.iloc[0] == 1
    assert train[(train.market_cap_group!='ALL')].num_trades.sum() == 0
    assert train[(train.market_segment=='Prime')].num_trades.iloc[0] == 1


def test_benchmark_exact_dates_and_fallback():
    idx = pd.to_datetime(['2020-01-06','2020-01-07'])
    b = pd.DataFrame({'Adj Open': [100.,110.], 'Adj Close': [105.,120.]}, index=idx)
    ticker, ret = benchmark_return({'^N225': b}, idx[0], idx[1])
    assert ticker == '^N225'
    assert ret == pytest.approx(.2)
    assert np.isnan(benchmark_return({'^N225': b}, idx[0], pd.Timestamp('2020-01-08'))[1])


def test_heatmap_file(config, tmp_path):
    config['output']['heatmap_metrics'] = ['mean_return']
    r = result_grid(config)
    n = generate_heatmaps(r, tmp_path, config)
    assert n == 2
    assert (tmp_path/'results/heatmaps/train/20d/all_mean_return.png').stat().st_size > 1000
