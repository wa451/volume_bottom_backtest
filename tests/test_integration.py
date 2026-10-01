from copy import deepcopy
from pathlib import Path
import pandas as pd
import numpy as np
import yaml
import pytest
from main import main
from src.utils import ROOT, init_dirs, load_config
from src.data_loader import exchange_sessions, align_sessions
from src.backtest import run_backtest, prepare_features
from src.corporate_actions import adjust_corporate_actions
from src.indicators import calculate_indicators


def test_full_offline_cli_and_config_snapshot(config, tmp_path, monkeypatch):
    init_dirs(tmp_path)
    config['data']['start_date'] = '2023-06-01'
    config['data']['end_date'] = '2023-07-31'
    config['train'] = {'start':'2023-06-01', 'end':'2023-06-30'}
    config['test'] = {'start':'2023-07-01', 'end':'2023-07-31'}
    config['strategy'].update(rolling_high_days=3, volume_average_days=3, drawdown_thresholds=[.2,.3],
                              volume_ratio_thresholds=[2.,3.], holding_periods=[2,5], signal_cooldown_days=2)
    config['validation']['minimum_trades'] = 1
    cfg_path = tmp_path/'config.yaml'
    cfg_path.write_text(yaml.safe_dump(config))
    pd.DataFrame([{'code':'7203','company_name':'Test','market_segment':'Prime','sector':'Test'}]).to_csv(tmp_path/'data/universe/universe.csv', index=False)
    idx = exchange_sessions('2023-05-01','2023-08-31')
    prices = pd.DataFrame({'Open':100.,'High':110.,'Low':90.,'Close':100.,'Adj Close':100.,'Volume':100.,'Dividends':0.,'Stock Splits':0.}, index=idx)
    for date in ['2023-06-08','2023-07-06']:
        prices.loc[date, ['Close','Adj Close']] = 60.
        prices.loc[date, 'Volume'] = 1000.
    monkeypatch.setattr('src.downloader.Downloader._request', lambda self, tickers, start: pd.concat({'7203.T': prices}, axis=1))
    class FakeTicker:
        def get_shares_full(self, start, end):
            if pd.Timestamp(start) <= pd.Timestamp('2023-05-01') < pd.Timestamp(end):
                return pd.Series([1e8], index=pd.to_datetime(['2023-05-01']))
            return None
    monkeypatch.setattr('src.downloader.yf.Ticker', lambda _: FakeTicker())
    args = ['--root', str(tmp_path), '--config', str(cfg_path)]
    assert main(args + ['all','--manual-universe']) == 0
    for name in ['trades.parquet','parameter_results.csv','market_cap_comparison.csv','market_segment_comparison.csv',
                 'top_candidates_train.csv','candidate_test_results.csv','summary.md','data_quality_report.md','data_quality.json','run.json']:
        assert (tmp_path/'results'/name).exists()
    trades = pd.read_parquet(tmp_path/'results/trades.parquet')
    assert set(trades.period_type) == {'train','test'}
    assert set(trades.holding_period) == {2,5}
    assert trades[trades.trade_status=='complete']['return'].notna().all()
    candidates = pd.read_csv(tmp_path/'results/top_candidates_train.csv')
    assert not candidates.empty
    assert candidates.period_type.eq('train').all()
    assert main(args + ['analyze']) == 0
    changed = deepcopy(config); changed['cost']['buy_cost_rate'] = .001
    cfg_path.write_text(yaml.safe_dump(changed))
    assert main(args + ['analyze']) == 1


def test_zero_volume_holidays_are_filtered(prices, config):
    df = prices.iloc[:3].copy()
    df.index = pd.to_datetime(['2023-05-02','2023-05-03','2023-05-08']).as_unit('ns')
    df.iloc[1, df.columns.get_loc('Volume')] = 0
    f = align_sessions(adjust_corporate_actions(df,config))
    assert pd.Timestamp('2023-05-03') not in f.index
    assert f.attrs['nontrading_zero_volume_rows'] == 1


def test_positive_volume_calendar_conflict_rejected(prices, config):
    df = prices.iloc[:3].copy()
    df.index = pd.to_datetime(['2023-05-02','2023-05-03','2023-05-08']).as_unit('ns')
    with pytest.raises(ValueError, match='calendar'):
        align_sessions(adjust_corporate_actions(df,config))


def test_future_split_does_not_change_past_indicators(prices, config):
    before = calculate_indicators(adjust_corporate_actions(prices,config),config['strategy'])
    prices.loc[prices.index[300], 'Stock Splits'] = 5
    after = calculate_indicators(adjust_corporate_actions(prices,config),config['strategy'])
    pd.testing.assert_frame_equal(before[['drawdown','volume_ratio']].iloc[:300],after[['drawdown','volume_ratio']].iloc[:300])


def test_missing_price_cache_still_produces_report_inputs(config, info, tmp_path):
    init_dirs(tmp_path)
    trades = run_backtest(tmp_path, pd.DataFrame([info]), config)
    assert trades.empty
    q = pd.read_csv(tmp_path/'results/logs/backtest_ticker_quality.csv')
    assert q.error.iloc[0] == 'price_cache_missing'
    assert not q.price_success.iloc[0]


def test_manual_master_does_not_claim_stale_jpx_metadata(config, tmp_path):
    from src.universe import load_universe
    from src.utils import atomic_json, read_json
    init_dirs(tmp_path)
    pd.DataFrame([{'code':'7203','company_name':'Test','market_segment':'Prime','sector':'Test'}]).to_csv(tmp_path/'data/universe/universe.csv', index=False)
    atomic_json({'source':'jpx', 'as_of':'20260831','total_domestic_ordinary_stocks':3700},tmp_path/'data/universe/source.json')
    u=load_universe(tmp_path,config,manual=True)
    meta=read_json(tmp_path/'data/universe/source.json')
    assert len(u)==1
    assert meta['source']=='manual_csv'
    assert meta['total_domestic_ordinary_stocks']==1
