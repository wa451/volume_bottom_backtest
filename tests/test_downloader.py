import pandas as pd
import numpy as np
from src.downloader import Downloader
from src.utils import init_dirs, acquisition_start, atomic_parquet, atomic_json


def valid_frame(start='2020-06-01', n=5):
    idx = pd.bdate_range(start, periods=n)
    return pd.DataFrame({'Open':100.,'High':110.,'Low':90.,'Close':100.,'Adj Close':90.,'Volume':1000.,'Dividends':0.,'Stock Splits':0.}, index=idx)


def test_partial_batch_retry_and_cached_skip(config, tmp_path, monkeypatch):
    init_dirs(tmp_path)
    config['download'].update(max_retries=2, retry_backoff_seconds=0)
    d = Downloader(tmp_path, config)
    calls = []
    def request(tickers, start):
        calls.append(tickers)
        if len(calls) == 1:
            return pd.concat({'7203.T': valid_frame()}, axis=1)
        return pd.concat({'130A.T': valid_frame()}, axis=1)
    monkeypatch.setattr(d, '_request', request)
    d.download_prices(['7203.T','130A.T'])
    assert calls == [['7203.T','130A.T'], ['130A.T']]
    assert (tmp_path/'data/market/7203.T.parquet').exists()
    assert (tmp_path/'data/market/130A.T.parquet').exists()
    assert pd.read_csv(tmp_path/'results/logs/failed_tickers.csv').empty
    calls.clear()
    d.download_prices(['7203.T','130A.T'])
    assert calls == []


def test_failure_saved_and_force_retry(config, tmp_path, monkeypatch):
    init_dirs(tmp_path)
    config['download'].update(max_retries=1, retry_backoff_seconds=0)
    d = Downloader(tmp_path, config)
    monkeypatch.setattr(d, '_request', lambda *a: pd.DataFrame())
    d.download_prices(['130A.T'])
    failed = pd.read_csv(tmp_path/'results/logs/failed_tickers.csv')
    assert failed.ticker.tolist() == ['130A.T']
    d2 = Downloader(tmp_path, config)
    monkeypatch.setattr(d2, '_request', lambda *a: pd.concat({'130A.T':valid_frame()}, axis=1))
    d2.download_prices(['130A.T'], force_tickers=['130A.T'])
    assert pd.read_csv(tmp_path/'results/logs/failed_tickers.csv').empty


def test_rebase_triggers_full_history_download(config, tmp_path, monkeypatch):
    init_dirs(tmp_path)
    old = valid_frame()
    atomic_parquet(old, tmp_path/'data/market/7203.T.parquet')
    atomic_json({'price:7203.T': {'requested_start': str(acquisition_start(config).date()), 'checked_through':'2020-06-06'}}, tmp_path/'data/download_manifest.json')
    d = Downloader(tmp_path, config)
    starts = []
    def request(tickers, start):
        starts.append(start)
        new = old.copy(); new['Adj Close'] *= .9
        return pd.concat({'7203.T':new}, axis=1)
    monkeypatch.setattr(d, '_request', request)
    d.download_prices(['7203.T'], update=True)
    assert len(starts) == 2
    assert starts[0] > acquisition_start(config)
    assert starts[1] == acquisition_start(config)
    assert pd.read_parquet(tmp_path/'data/market/7203.T.parquet')['Adj Close'].eq(81).all()


def test_new_split_or_dividend_is_rebase():
    old = valid_frame()
    new = valid_frame(n=6)
    new.iloc[-1,new.columns.get_loc('Stock Splits')] = 2
    assert Downloader._basis_changed(old,new)
    new['Stock Splits'] = 0; new.iloc[-1,new.columns.get_loc('Dividends')] = 1
    assert Downloader._basis_changed(old,new)


def test_shares_missing_is_cached_and_reported(config, tmp_path, monkeypatch):
    init_dirs(tmp_path)
    config['download']['max_retries'] = 1
    class FakeTicker:
        def get_shares_full(self, **kwargs):
            return None
    monkeypatch.setattr('src.downloader.yf.Ticker', lambda t: FakeTicker())
    d = Downloader(tmp_path, config)
    d.download_shares(['7203.T'])
    assert pd.read_parquet(tmp_path/'data/shares/7203.T.parquet').empty
    failed = pd.read_csv(tmp_path/'results/logs/failed_tickers.csv')
    assert failed.kind.tolist() == ['shares']
    assert (tmp_path/'data/download_manifest.json').exists()


def test_download_rejects_wrong_provider_basis(config, tmp_path):
    import pytest
    config['data']['price_basis'] = 'raw'
    with pytest.raises(ValueError, match='yahoo_split_adjusted'):
        Downloader(tmp_path,config)
