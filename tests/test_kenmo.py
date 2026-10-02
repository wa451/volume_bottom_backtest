from copy import deepcopy
import numpy as np
import pandas as pd
import pytest
from src.strategies import REGISTRY
from src.strategy_config import StrategyParameters, parameter_defaults, parameter_grid
from src.strategy_data import load_strategy_data, update_auxiliary
from src.execution import find_exit
from src.portfolio import simulate
from src.data_loader import exchange_sessions


def features(n=280):
    idx = pd.bdate_range('2024-01-02', periods=n).as_unit('ns')
    df = pd.DataFrame({'Adj Open': 100., 'Adj High': 101., 'Adj Low': 99., 'Adj Close': 100., 'Raw Close': 100., 'Volume': 100., 'Stock Splits': 0., 'market_cap': 1e10, 'market_cap_group': 'small', 'split_excluded': False, 'missing_session': False, 'strategy_volume_ratio': 1.}, index=idx)
    return df


def p(strategy='kenmo_breakout', **kwargs):
    values = {**parameter_defaults(strategy), **kwargs}
    return {k: v[0] if isinstance(v, list) and k != 'exit_modes' else v for k, v in values.items()} | {'exit_mode': values['exit_modes'][0]}


def test_breakout_excludes_current_high_and_volume_and_future():
    df = features()
    df.loc[df.index[260], ['Adj Close', 'Adj High', 'Volume']] = [102., 103., 200.]
    df['strategy_volume_ratio'] = df.Volume / df.Volume.shift(1).rolling(20).mean()
    mask = REGISTRY['kenmo_breakout'].entry_signals(df, p(), {})
    assert mask.iloc[260] and not mask.iloc[:252].any()
    future = df.copy()
    future.iloc[261:, future.columns.get_loc('Adj High')] = 10000
    assert mask.iloc[:261].equals(REGISTRY['kenmo_breakout'].entry_signals(future, p(), {}).iloc[:261])
    df.iloc[260, df.columns.get_loc('strategy_volume_ratio')] = 1.4
    assert not REGISTRY['kenmo_breakout'].entry_signals(df, p(), {}).iloc[260]


@pytest.mark.parametrize('timing,offset,signal_pos', [('2024-01-08T13:00:00+09:00', 1, 4), ('2024-01-08T16:00:00+09:00', 1, None), ('2024-01-08T16:00:00+09:00', 2, 5), ('2024-01-08T00:00:00+09:00', 2, 5), ('2024-01-08T16:00:00+09:00', 5, 8)])
def test_earnings_timestamp_reaction_and_entry(timing, offset, signal_pos):
    df = features(20)
    df['Adj Close'] = 105.
    df.iloc[3, df.columns.get_loc('Adj Close')] = 100
    df['strategy_volume_ratio'] = 2.5
    data = {'earnings': [{'released_at': timing, 'timing_known': 'T00:' not in timing}]}
    mask = REGISTRY['kenmo_earnings'].entry_signals(df, p('kenmo_earnings', entry_offset=[offset]), data)
    positions = list(np.flatnonzero(mask))
    assert positions == ([] if signal_pos is None else [signal_pos])
    # Adding an announcement after the last bar never creates past entries.
    data['earnings'].append({'released_at': '2026-12-01T13:00:00+09:00', 'timing_known': True})
    assert list(np.flatnonzero(REGISTRY['kenmo_earnings'].entry_signals(df, p('kenmo_earnings', entry_offset=[offset]), data))) == positions


def test_financials_never_backdate_and_use_timestamp_not_date(tmp_path):
    df = features(12)
    path = tmp_path / 'data/fundamentals/7203.T.parquet'
    path.parent.mkdir(parents=True)
    available = pd.Timestamp(df.index[4]).tz_localize('Asia/Tokyo') + pd.Timedelta(hours=15, minutes=1)
    pd.DataFrame([{'available_at': available, 'revenue_growth': .2, 'earnings_growth': .3, 'roe': .15, 'trailing_eps': 5, 'source': 'yahoo_observed_snapshot', 'fiscal_period': '2020-12-31'}]).to_parquet(path)
    financials = load_strategy_data(tmp_path, '7203.T', df)['fundamentals']
    assert financials.iloc[:5].isna().all().all()
    assert financials.iloc[5].revenue_growth == .2
    assert financials.iloc[5].per == 20
    df.iloc[7, df.columns.get_loc('Stock Splits')] = 2
    split = load_strategy_data(tmp_path, '7203.T', df)['fundamentals']
    assert split.iloc[6].per == 20 and split.iloc[7:].per.isna().all()
    condition = p(mode='fundamentals', high_enabled=False, volume_enabled=False)
    mask = REGISTRY['kenmo_breakout'].entry_signals(df, condition, {'fundamentals': financials})
    assert not mask.iloc[:5].any() and mask.iloc[5]


def test_fundamental_snapshot_expiry_and_missing_never_fallback(tmp_path):
    df = features(12)
    data = load_strategy_data(tmp_path, '7203.T', df)
    assert not REGISTRY['kenmo_breakout'].entry_signals(df, p(mode='fundamentals', high_enabled=False, volume_enabled=False), data).any()
    assert REGISTRY['kenmo_breakout'].entry_signals(df, p(high_enabled=False, volume_enabled=False), data).all()


def test_growth_cap_boundary_and_optional_listing(tmp_path):
    df = features(60)
    df['Adj Close'] = np.arange(60) + 100.
    df.loc[df.index[55], 'market_cap'] = 3e10
    df.loc[df.index[56], 'market_cap'] = 5e9
    data = load_strategy_data(tmp_path, '7203.T', df)
    mask = REGISTRY['kenmo_growth'].entry_signals(df, p('kenmo_growth'), data)
    assert not mask.iloc[55] and mask.iloc[56]
    assert not REGISTRY['kenmo_growth'].entry_signals(df, p('kenmo_growth', listing_enabled=True), data).any()


def test_stop_profit_same_bar_gap_and_next_open_holding():
    df = features(10)
    parameters = p(exit_modes=['fixed'])
    df.iloc[1, df.columns.get_loc('Adj High')] = 150
    df.iloc[1, df.columns.get_loc('Adj Low')] = 80
    exit_ = find_exit(df, 0, parameters)
    assert exit_['exit_price'] == 92 and exit_['exit_reason'] == 'stop_loss'
    df.iloc[1, df.columns.get_loc('Adj Open')] = 70
    assert find_exit(df, 0, parameters)['exit_price'] == 70
    df = features(10)
    df.iloc[1, df.columns.get_loc('Adj High')] = 140
    assert find_exit(df, 0, parameters)['exit_reason'] == 'take_profit'
    assert find_exit(df, 0, parameters)['exit_price'] == 130
    exit_ = find_exit(features(10), 0, p(holding_period=[2]))
    assert exit_['exit_position'] == 2 and exit_['exit_timing'] == 'open'
    assert exit_['holding_days'] == 2


def test_trailing_does_not_raise_stop_with_same_day_high():
    df = features(10)
    df.iloc[0, df.columns.get_loc('Adj High')] = 200
    df.iloc[0, df.columns.get_loc('Adj Low')] = 95
    df.iloc[1, df.columns.get_loc('Adj Open')] = 185
    df.iloc[1, df.columns.get_loc('Adj High')] = 190
    df.iloc[1, df.columns.get_loc('Adj Low')] = 170
    exit_ = find_exit(df, 0, p(exit_modes=['trailing'], trailing_stop=[.1]))
    assert exit_['exit_position'] == 1 and exit_['exit_price'] == 180


def test_ma_exit_is_next_open_and_missing_bar_not_invented():
    df = features(10)
    df.iloc[:5, df.columns.get_loc('Adj Close')] = 110
    exit_ = find_exit(df, 5, p(exit_modes=['ma'], ma_period=[5]))
    assert exit_['exit_position'] == 6 and exit_['exit_timing'] == 'open'
    df.iloc[6, df.columns.get_loc('Adj Low')] = np.nan
    assert find_exit(df, 5, p(holding_period=[5]))['trade_status'] == 'unresolved_data_gap'


def test_parameter_grid_only_active_dimensions_and_guard(config):
    config['strategy_ids'] = ['kenmo_breakout']
    config['strategy_params'] = {'kenmo_breakout': {'high_period': [120, 180, 252], 'volume_ratio': [1, 1.5, 2], 'revenue_growth': [.05, .1, .2], 'stop_loss': [.05, .08], 'exit_modes': ['holding', 'fixed'], 'holding_period': [20, 60], 'take_profit': [.2, .3]}}
    assert len(parameter_grid(config)) == 72  # No unused financial grid in price-only.
    config['strategy_params']['kenmo_breakout'].update(mode='fundamentals', earnings_growth=[.1, .2, .3], roe=[.08, .1, .15])
    with pytest.raises(ValueError, match='256'):
        parameter_grid(config)
    with pytest.raises(ValueError):
        StrategyParameters(stop_loss=[float('nan')])


def candidate(date, ticker='7203.T', exit_date=None, price=110, timing='intraday'):
    return {'ticker': ticker, 'signal_date': date - pd.Timedelta(days=1), 'entry_date': date, 'entry_price': 100., 'exit_date': exit_date, 'exit_price': price, 'exit_timing': timing, 'exit_reason': 'take_profit', 'trade_status': 'complete', 'holding_days': 1}


def test_portfolio_costs_and_no_future_outcome_selection():
    df = features(4)
    df['Adj Close'] = 110.
    sessions = df.index
    costs = {'buy_cost_rate': .001, 'sell_cost_rate': .002, 'slippage_rate': .005}
    settings = {'initial_capital': 1000., 'max_positions': 1}
    t = candidate(sessions[0], exit_date=sessions[1])
    metrics, curve, trades = simulate([t], {'7203.T': df}, sessions, settings, costs)
    expected = 1.1 * .995 * .998 / (1.005 * 1.001) - 1
    assert trades[0]['return'] == pytest.approx(expected)
    assert metrics['total_return'] == pytest.approx(expected)
    assert metrics['num_trades'] == 1
    future = candidate(sessions[0], exit_date=sessions[-1] + pd.Timedelta(days=20))
    metrics, curve, trades = simulate([future], {'7203.T': df}, sessions, settings, {key: 0 for key in costs})
    assert metrics['num_trades'] == 0 and metrics['num_positions'] == 1
    assert metrics['total_return'] == pytest.approx(.1)
    assert trades[0]['exit_date'] is None and trades[0]['trade_status'] == 'open_at_end'


def test_intraday_exit_cash_not_reused_at_same_open():
    df = features(4)
    sessions = df.index
    entries = [candidate(sessions[0], exit_date=sessions[1]), candidate(sessions[1], '8306.T', sessions[2])]
    settings = {'initial_capital': 1000., 'max_positions': 1}
    costs = {'buy_cost_rate': 0, 'sell_cost_rate': 0, 'slippage_rate': 0}
    metrics, _, trades = simulate(entries, {'7203.T': df, '8306.T': df}, sessions, settings, costs)
    assert len(trades) == 1 and metrics['capacity_or_duplicate'] == 1
    entries[0]['exit_timing'] = 'open'
    assert len(simulate(entries, {'7203.T': df, '8306.T': df}, sessions, settings, costs)[2]) == 2


def test_auxiliary_incremental_cache_skip_and_failure_preserves(tmp_path, monkeypatch):
    calls, states = [], []
    now = pd.Timestamp.now(tz='UTC')
    def fetch_earnings(ticker, initial):
        calls.append(('earnings', initial))
        return pd.DataFrame([{'released_at': (now - pd.Timedelta(days=3)).isoformat(), 'timing_known': False, 'reported_eps': 1., 'source': 'yahoo_reported_earnings_calendar'}])
    def fetch_fundamentals(ticker, when):
        calls.append(('fundamentals', when))
        return pd.DataFrame([{'available_at': when, 'revenue_growth': .1, 'earnings_growth': .2, 'roe': .1, 'trailing_eps': 5., 'source': 'yahoo_observed_snapshot', 'fiscal_period': '2023'}])
    monkeypatch.setattr('src.strategy_data.fetch_earnings', fetch_earnings)
    monkeypatch.setattr('src.strategy_data.fetch_fundamentals', fetch_fundamentals)
    outcome = lambda *args: states.append(args)
    update_auxiliary(tmp_path, ['7203.T'], outcome, now=now)
    assert len(calls) == 2
    update_auxiliary(tmp_path, ['7203.T'], outcome, now=now + pd.Timedelta(hours=1))
    assert len(calls) == 2 and [s[2] for s in states[-2:]] == ['cached', 'cached']
    path = tmp_path / 'data/earnings/7203.T.parquet'
    previous = path.read_bytes()
    def failed(*args):
        raise OSError('timeout')
    monkeypatch.setattr('src.strategy_data.fetch_earnings', failed)
    update_auxiliary(tmp_path, ['7203.T'], outcome, retry_failed=True, failures={('7203.T', 'earnings')}, now=now + pd.Timedelta(days=2))
    assert path.read_bytes() == previous and states[-1][2] == 'failed'
    assert len(calls) == 2


def test_real_yahoo_microsecond_snapshot_precision(tmp_path):
    df = features(12)
    path = tmp_path / 'data/fundamentals/7203.T.parquet'
    path.parent.mkdir(parents=True)
    timestamp = (df.index[4].tz_localize('Asia/Tokyo') + pd.Timedelta(hours=15, minutes=1)).as_unit('us')
    pd.DataFrame([{'available_at': timestamp, 'revenue_growth': .2, 'earnings_growth': .3, 'roe': .15, 'trailing_eps': 5, 'source': 'yahoo_observed_snapshot', 'fiscal_period': '2020'}]).to_parquet(path)
    data = load_strategy_data(tmp_path, '7203.T', df)
    assert not data['errors']
    assert data['fundamentals'].iloc[:5].isna().all().all()
    assert data['fundamentals'].iloc[5].per == 20


def test_open_exit_does_not_depend_on_future_same_day_close():
    df = features(10)
    df.iloc[2, df.columns.get_loc('Adj Close')] = np.nan
    df.iloc[2, df.columns.get_loc('Adj Low')] = np.nan
    exit_ = find_exit(df, 0, p(holding_period=[2]))
    assert exit_['trade_status'] == 'complete' and exit_['exit_position'] == 2
    assert exit_['exit_price'] == 100


def test_annual_growth_requires_same_consecutive_fiscal_periods():
    from src.strategy_data import _growth
    statement = pd.DataFrame({'2024-03-31': [120.], '2023-03-31': [100.]}, index=['TotalRevenue'])
    assert _growth(statement, ['TotalRevenue']) == pytest.approx(.2)
    statement = pd.DataFrame({'2024-03-31': [120.], '2022-03-31': [100.]}, index=['TotalRevenue'])
    assert np.isnan(_growth(statement, ['TotalRevenue']))


def test_missing_benchmark_is_not_rebased_later():
    df = features(4)
    benchmark = df.iloc[1:].copy()
    settings = {'initial_capital': 1000., 'max_positions': 1}
    costs = {'buy_cost_rate': 0, 'sell_cost_rate': 0, 'slippage_rate': 0}
    metrics, curve, _ = simulate([candidate(df.index[0], exit_date=df.index[2])], {'7203.T': df}, df.index, settings, costs, benchmark)
    assert curve.benchmark.isna().all() and metrics['benchmark_coverage'] == 0


def test_missing_held_price_invalidates_portfolio_statistics():
    df = features(4)
    df.iloc[1, df.columns.get_loc('Adj Close')] = np.nan
    settings = {'initial_capital': 1000., 'max_positions': 1}
    costs = {'buy_cost_rate': 0, 'sell_cost_rate': 0, 'slippage_rate': 0}
    t = candidate(df.index[0], exit_date=df.index[-1] + pd.Timedelta(days=10))
    metrics, curve, _ = simulate([t], {'7203.T': df}, df.index, settings, costs)
    assert not metrics['metrics_valid'] and metrics['cagr'] is None
    assert metrics['data_gap_marks'] == 1


def test_earnings_cache_merges_new_releases_without_removing_history(tmp_path, monkeypatch):
    states, initial_flags = [], []
    now = pd.Timestamp.now(tz='UTC')
    old = pd.DataFrame([{'released_at': (now - pd.Timedelta(days=1000)).isoformat(), 'timing_known': False, 'reported_eps': 1., 'source': 'yahoo_reported_earnings_calendar'}])
    path = tmp_path / 'data/earnings/7203.T.parquet'
    path.parent.mkdir(parents=True)
    old.to_parquet(path)
    from src.utils import atomic_json
    atomic_json({'fetched_at': (now - pd.Timedelta(days=2)).isoformat()}, path.with_suffix('.json'))
    def fetched(ticker, initial):
        initial_flags.append(initial)
        return pd.DataFrame([{'released_at': (now - pd.Timedelta(days=1)).isoformat(), 'timing_known': True, 'reported_eps': 2., 'source': 'yahoo_reported_earnings_calendar'}])
    monkeypatch.setattr('src.strategy_data.fetch_earnings', fetched)
    update_auxiliary(tmp_path, ['7203.T'], lambda *args: states.append(args), retry_failed=True, failures={('7203.T', 'earnings')}, now=now)
    assert initial_flags == [False]
    assert len(pd.read_parquet(path)) == 2
    assert states[-1][2] == 'downloaded'


def test_old_financial_observation_expires(tmp_path):
    df = features(12)
    path = tmp_path / 'data/fundamentals/7203.T.parquet'
    path.parent.mkdir(parents=True)
    pd.DataFrame([{'available_at': pd.Timestamp('2021-01-01', tz='UTC'), 'revenue_growth': .2, 'earnings_growth': .3, 'roe': .15, 'trailing_eps': 5, 'source': 'yahoo_observed_snapshot', 'fiscal_period': '2020'}]).to_parquet(path)
    data = load_strategy_data(tmp_path, '7203.T', df)
    assert not data['errors'] and data['fundamentals'].isna().all().all()


def test_runner_uses_common_split_adjusted_volume(tmp_path, monkeypatch, config, info):
    from src.strategy_runner import _ticker
    df = features(80)
    df['SplitAdjustedVolume'] = 100.
    df.iloc[35, df.columns.get_loc('Volume')] = 1000.
    # An imported raw-volume change is not a real split-adjusted volume spike.
    monkeypatch.setattr('src.strategy_runner.prepare_features', lambda *args: df.copy())
    config['data'].update(start_date=str(df.index[30].date()), end_date=str(df.index[-1].date()))
    config['strategy_ids'] = ['kenmo_breakout']
    config['strategy_params'] = {'kenmo_breakout': {'high_enabled': False}}
    _, candidates, _ = _ticker(tmp_path, info, config, parameter_grid(config), {'train': (df.index[30], df.index[-1])})
    assert not next(iter(candidates.values()))
