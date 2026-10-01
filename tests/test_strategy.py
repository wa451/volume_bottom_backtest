import numpy as np
import pandas as pd
import pytest
from src.universe import to_ticker, normalize_master
from src.corporate_actions import adjust_corporate_actions, future_split_factor
from src.indicators import calculate_indicators
from src.market_cap import attach_market_cap, cap_group
from src.signals import signal_mask, apply_cooldown
from src.backtest import ticker_trades, period_type
from src.data_loader import normalize_shares, align_sessions
from src.utils import validate_config


def features(prices, config):
    return attach_market_cap(calculate_indicators(adjust_corporate_actions(prices, config), config['strategy']), None, config)


@pytest.mark.parametrize('code,ticker', [('7203', '7203.T'), (7203, '7203.T'), (7203.0, '7203.T'), ('130A', '130A.T'), (' 130a ', '130A.T')])
def test_ticker(code, ticker):
    assert to_ticker(code) == ticker


@pytest.mark.parametrize('code', ['25935', '7203.T', '../abc', '', None])
def test_invalid_ticker(code):
    with pytest.raises(ValueError):
        to_ticker(code)


def test_jpx_product_filter():
    df = pd.DataFrame({'コード': ['7203', '130A', '25935', '1306', '8951', '1000'],
                       '銘柄名': ['A', 'B', 'Preferred', 'ETF', 'REIT', 'Foreign'],
                       '市場・商品区分': ['プライム（内国株式）', 'グロース（内国株式）', 'プライム（内国株式）', 'ETF・ETN', 'REIT・ベンチャーファンド・カントリーファンド・インフラファンド', 'プライム（外国株式）'],
                       '33業種区分': ['輸送用機器'] * 6})
    u = normalize_master(df, ['Prime', 'Standard', 'Growth'])
    assert set(u.code) == {'7203', '130A'}


def test_adjusted_ohlc(prices, config):
    prices['Adj Close'] = 80.
    f = adjust_corporate_actions(prices, config)
    assert f['Adj Open'].iloc[0] == 80
    assert f['Adj High'].iloc[0] == 88
    assert f['Adj Low'].iloc[0] == 72


def test_raw_split_volume_and_price(prices, config):
    config['data']['price_basis'] = 'raw'
    config['data']['volume_basis'] = 'raw'
    prices.loc[prices.index[:100], ['Open','High','Low','Close']] *= 2
    prices.loc[prices.index[100:], 'Volume'] *= 2
    prices.loc[prices.index[100], 'Stock Splits'] = 2
    f = adjust_corporate_actions(prices, config)
    assert f['SplitAdjustedVolume'].eq(200).all()
    assert f['Adj Open'].eq(100).all()
    assert f['future_split_factor'].iloc[99] == 2
    assert f['future_split_factor'].iloc[100] == 1
    assert not f.split_adjustment_failed.any()


def test_yahoo_no_double_volume_adjustment(prices, config):
    prices.loc[prices.index[100], 'Stock Splits'] = 2
    f = adjust_corporate_actions(prices, config)
    assert f['SplitAdjustedVolume'].eq(100).all()
    assert f['Raw Close'].iloc[99] == 200
    assert f['Raw Close'].iloc[100] == 100
    assert f['Raw Volume'].iloc[99] == 50
    assert f['Adj Open'].eq(100).all()


def test_split_and_consolidation_factor():
    s = pd.Series([0., 2., 0., .2, 0.])
    np.testing.assert_allclose(future_split_factor(s), [.4, .2, .2, 1, 1])


def test_unknown_actions_are_not_assumed_zero(prices, config):
    prices['Stock Splits'] = np.nan
    f = adjust_corporate_actions(prices, config)
    assert f.split_excluded.all()
    assert f['Raw Close'].isna().all()


def test_failed_split_is_excluded_only_after_known_event(prices, config):
    prices.loc[prices.index[100:], ['Open','High','Low','Close','Adj Close']] /= 2
    prices.loc[prices.index[100], 'Stock Splits'] = 2
    f = adjust_corporate_actions(prices, config)
    assert f.split_adjustment_failed.iloc[100]
    assert not f.split_excluded.iloc[99]
    assert f.split_excluded.iloc[100:121].all()
    assert not f.split_excluded.iloc[121]


def test_rolling_high_and_no_current_high(prices, config):
    prices.loc[prices.index[252], 'High'] = 99999
    f = features(prices, config)
    assert pd.isna(f.rolling_high_252.iloc[251])
    assert f.rolling_high_252.iloc[252] == 110
    assert f.rolling_high_252.iloc[253] == 99999
    assert f.drawdown.iloc[252] == pytest.approx(100/110-1)


def test_future_prices_do_not_change_indicators(prices, config):
    baseline = features(prices, config)
    prices.loc[prices.index[300:], ['Open','High','Low','Close','Adj Close','Volume']] *= 100
    changed = features(prices, config)
    pd.testing.assert_frame_equal(baseline[['drawdown','volume_ratio']].iloc[:300], changed[['drawdown','volume_ratio']].iloc[:300])


def test_current_volume_excluded_from_average(prices, config):
    prices.loc[prices.index[30], 'Volume'] = 10000
    f = features(prices, config)
    assert f.average_volume_20.iloc[30] == 100
    assert f.volume_ratio.iloc[30] == 100
    assert f.average_volume_20.iloc[31] == 595


def test_zero_average_is_missing(prices, config):
    prices.loc[prices.index[:30], 'Volume'] = 0
    f = features(prices, config)
    assert pd.isna(f.volume_ratio.iloc[30])


def test_signal_threshold_inclusive():
    df = pd.DataFrame({'drawdown': [-.3, -.299, -.5, np.nan], 'volume_ratio': [2., 2., 1.9, 100.]})
    assert signal_mask(df, .3, 2.).tolist() == [True, False, False, False]


def test_cooldown_blocks_exactly_twenty_days():
    assert apply_cooldown(pd.Series([True]*45), 20).tolist() == [0, 21, 42]
    assert apply_cooldown(pd.Series([True]*3), 0).tolist() == [0,1,2]


def test_next_open_holding_and_return(prices, config, info):
    config['strategy'].update(drawdown_thresholds=[.2], volume_ratio_thresholds=[2.], holding_periods=[20])
    prices.loc[prices.index[260], ['Close','Adj Close']] = 70
    prices.loc[prices.index[260], 'Volume'] = 500
    prices.loc[prices.index[261], 'Open'] = 80
    prices.loc[prices.index[281], ['Close','Adj Close']] = 120
    trades, _ = ticker_trades(features(prices, config), info, config)
    t = trades.iloc[0]
    assert t.signal_date == prices.index[260]
    assert t.entry_date == prices.index[261]
    assert t.exit_date == prices.index[281]
    assert t.entry_price == 80
    assert t.exit_price == 120
    assert t['return'] == .5
    assert t.entry_date > t.signal_date


def test_entry_exit_split_same_price_basis(prices, config, info):
    config['strategy'].update(drawdown_thresholds=[.2], volume_ratio_thresholds=[2.], holding_periods=[20])
    prices.loc[prices.index[260], ['Close','Adj Close']] = 70
    prices.loc[prices.index[260], 'Volume'] = 500
    prices.loc[prices.index[261], 'Open'] = 80
    prices.loc[prices.index[270], 'Stock Splits'] = 2
    prices.loc[prices.index[281], ['Close','Adj Close']] = 120
    trades, _ = ticker_trades(features(prices, config), info, config)
    t = trades.iloc[0]
    assert t.raw_entry_price == 160
    assert t.raw_exit_price == 120
    assert t.exit_price == 240
    assert t['return'] == .5
    assert t.exit_price/t.entry_price-1 == t['return']


def test_costs(prices, config, info):
    config['strategy'].update(drawdown_thresholds=[.2], volume_ratio_thresholds=[2.], holding_periods=[20])
    config['cost'].update(buy_cost_rate=.01, sell_cost_rate=.02, slippage_rate=.005)
    prices.loc[prices.index[260], ['Close','Adj Close']] = 70
    prices.loc[prices.index[260], 'Volume'] = 500
    t = ticker_trades(features(prices, config), info, config)[0].iloc[0]
    assert t['return'] == pytest.approx(.995*.98/(1.005*1.01)-1)


def test_asof_and_historical_market_cap(prices, config):
    shares = normalize_shares(pd.Series([1000., 999999.], index=[prices.index[10], prices.index[30]]))
    f = attach_market_cap(adjust_corporate_actions(prices, config), shares, config)
    assert pd.isna(f.market_cap.iloc[9])
    assert f.market_cap.iloc[10] == 100000
    assert f.market_cap_quality.iloc[10] == 'historical_exact'
    assert f.historical_shares.iloc[29] == 1000
    assert f.market_cap_quality.iloc[29] == 'historical_asof'
    assert (f.shares_date.dropna() <= f.shares_date.dropna().index).all()


def test_no_prior_shares_no_current_fallback(prices, config):
    shares = normalize_shares(pd.Series([999999.], index=[prices.index[-1] + pd.Timedelta(days=1)]))
    f = attach_market_cap(adjust_corporate_actions(prices, config), shares, config)
    assert f.market_cap.isna().all()
    assert f.market_cap_quality.eq('missing').all()


def test_stale_and_pre_split_shares_missing(prices, config):
    config['market_cap']['max_shares_age_days'] = 5
    shares = normalize_shares(pd.Series([1000.], index=[prices.index[0]]))
    prices.loc[prices.index[3], 'Stock Splits'] = 2
    f = attach_market_cap(adjust_corporate_actions(prices, config), shares, config)
    assert pd.isna(f.market_cap.iloc[3])
    assert f.market_cap_missing_reason.iloc[3] == 'shares_before_split'
    prices['Stock Splits'] = 0
    f = attach_market_cap(adjust_corporate_actions(prices, config), shares, config)
    assert f.market_cap_missing_reason.iloc[10] == 'stale_shares'


def test_market_cap_boundary(config):
    bins = config['market_cap_bins']
    assert cap_group(1e10 - 1, bins) == 'micro'
    assert cap_group(1e10, bins) == 'small'
    assert cap_group(1e12, bins) == 'mega'
    assert cap_group(np.nan, bins) == 'missing'


def test_conflicting_shares_observations_excluded():
    s = pd.Series([100., 200., 300.], index=pd.to_datetime(['2020-01-01','2020-01-01','2020-01-02']))
    out = normalize_shares(s)
    assert len(out) == 1
    assert out.historical_shares.iloc[0] == 300


def test_train_test_and_boundary_purge(prices, config, info):
    signal = prices.index[260]
    config['train']['end'] = str(prices.index[270].date())
    config['test']['start'] = str(prices.index[271].date())
    config['strategy'].update(drawdown_thresholds=[.2], volume_ratio_thresholds=[2.], holding_periods=[20])
    prices.loc[signal, ['Close','Adj Close']] = 70
    prices.loc[signal, 'Volume'] = 500
    t = ticker_trades(features(prices, config), info, config)[0].iloc[0]
    assert t.trade_status == 'boundary_purged'
    assert t.period_type == 'train'
    assert pd.isna(t['return'])
    assert period_type(prices.index[271], config) == 'test'


def test_incomplete_trade_saved(prices, config, info):
    config['strategy'].update(drawdown_thresholds=[.2], volume_ratio_thresholds=[2.], holding_periods=[250])
    prices.loc[prices.index[260], ['Close','Adj Close']] = 70
    prices.loc[prices.index[260], 'Volume'] = 500
    t = ticker_trades(features(prices, config), info, config)[0].iloc[0]
    assert t.trade_status == 'incomplete'
    assert pd.isna(t['return'])


def test_missing_session_not_skipped(prices, config, info):
    idx = pd.to_datetime(['2023-06-05','2023-06-07','2023-06-08','2023-06-09']).as_unit('ns')
    p = prices.iloc[:4].copy(); p.index = idx
    config['strategy'].update(drawdown_thresholds=[.2], volume_ratio_thresholds=[2.], holding_periods=[1])
    f = align_sessions(adjust_corporate_actions(p, config))
    f['drawdown'] = [-.3, np.nan, 0, 0, 0]
    f['volume_ratio'] = [3, np.nan, 1, 1, 1]
    f['rolling_high_252'] = 150.; f['average_volume_20'] = 100.
    f = attach_market_cap(f, None, config)
    t = ticker_trades(f, info, config)[0].iloc[0]
    assert t.entry_date == pd.Timestamp('2023-06-06')
    assert t.exit_date == pd.Timestamp('2023-06-07')
    assert t.trade_status == 'invalid_price'
    assert pd.isna(t['return'])


def test_bad_config_rejected(config):
    config['test']['start'] = config['train']['end']
    with pytest.raises(ValueError):
        validate_config(config)


def test_partial_current_day_not_used(prices, config, info, monkeypatch):
    config['strategy'].update(drawdown_thresholds=[.2], volume_ratio_thresholds=[2.], holding_periods=[20])
    cutoff = prices.index[259]
    monkeypatch.setattr('src.backtest.last_completed_date', lambda: cutoff)
    prices.loc[prices.index[260], ['Close','Adj Close']] = 70
    prices.loc[prices.index[260], 'Volume'] = 500
    trades, _ = ticker_trades(features(prices, config), info, config)
    assert trades.empty
