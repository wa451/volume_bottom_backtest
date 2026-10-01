import pandas as pd
import numpy as np
from src.downloader import Downloader
from src.utils import init_dirs, acquisition_start, atomic_parquet, atomic_json


def valid_frame(start='2020-06-01', n=5):
    idx = pd.bdate_range(start, periods=n).as_unit('ns')
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


def seed_prices(tmp_path, config, frame=None, metadata=True):
    frame = valid_frame() if frame is None else frame
    atomic_parquet(frame, tmp_path/'data/market/7203.T.parquet')
    if metadata:
        atomic_json({'price:7203.T': {'requested_start': str(acquisition_start(config).date()),
                                     'checked_through':'2020-06-06', 'completed_through':'2020-06-05'}},
                    tmp_path/'data/download_manifest.json')
    return frame


def test_default_download_only_requests_latest_tail(config, tmp_path, monkeypatch):
    init_dirs(tmp_path)
    old = seed_prices(tmp_path, config)
    d = Downloader(tmp_path, config)
    calls = []
    new = valid_frame('2020-06-05', n=3)
    def request(tickers, start):
        calls.append((tickers, start))
        return pd.concat({'7203.T':new}, axis=1)
    monkeypatch.setattr(d, '_request', request)
    d.download_prices(['7203.T'])
    assert calls == [(['7203.T'], old.index[-1])]
    combined = pd.read_parquet(tmp_path/'data/market/7203.T.parquet')
    pd.testing.assert_frame_equal(combined.loc[old.index], old, check_names=False, check_freq=False)
    assert combined.index[-1] == new.index[-1]
    assert d.manifest['price:7203.T']['last_download_mode'] == 'incremental'


def test_retry_failed_price_preserves_cache_and_stays_incremental(config, tmp_path, monkeypatch):
    init_dirs(tmp_path)
    old = seed_prices(tmp_path, config)
    config['download'].update(max_retries=1, retry_backoff_seconds=0)
    d = Downloader(tmp_path, config)
    monkeypatch.setattr(d, '_request', lambda *a: pd.DataFrame())
    d.download_prices(['7203.T'])
    pd.testing.assert_frame_equal(pd.read_parquet(tmp_path/'data/market/7203.T.parquet'), old, check_freq=False)
    resumed = Downloader(tmp_path, config)
    calls = []
    def request(tickers, start):
        calls.append(start)
        return pd.concat({'7203.T':valid_frame('2020-06-05',n=3)},axis=1)
    monkeypatch.setattr(resumed, '_request', request)
    resumed.download_prices(['7203.T'],force_tickers=['7203.T'])
    assert calls == [old.index[-1]]
    assert pd.read_csv(tmp_path/'results/logs/failed_tickers.csv').empty
    assert pd.read_parquet(tmp_path/'data/market/7203.T.parquet').index[0] == old.index[0]


def test_no_update_explicitly_skips_existing_prices(config, tmp_path, monkeypatch):
    init_dirs(tmp_path)
    seed_prices(tmp_path, config)
    d = Downloader(tmp_path, config)
    monkeypatch.setattr(d, '_request', lambda *a: (_ for _ in ()).throw(AssertionError('network call')))
    d.download_prices(['7203.T'],update=False)
    assert d.status[-1]['status'] == 'cached'


def test_legacy_cache_only_backfills_missing_prefix(config, tmp_path, monkeypatch):
    init_dirs(tmp_path)
    config['data']['start_date']='2020-01-01'
    old = seed_prices(tmp_path, config, metadata=False)
    d = Downloader(tmp_path, config)
    calls = []
    prefix = valid_frame('2019-12-30',n=3)
    prefix = pd.concat([prefix, old.iloc[:1]])
    def request(tickers, start, end=None):
        calls.append((start, end))
        return pd.concat({'7203.T':prefix if end is not None else valid_frame('2020-06-05',n=3)},axis=1)
    monkeypatch.setattr(d,'_request',request)
    d.download_prices(['7203.T'])
    assert calls == [(old.index[-1],None),(d.start,old.index[0]+pd.Timedelta(days=1))]
    combined=pd.read_parquet(tmp_path/'data/market/7203.T.parquet')
    assert combined.index[0] == prefix.index[0]
    pd.testing.assert_frame_equal(combined.loc[old.index],old,check_names=False,check_freq=False)
    assert d.manifest['price:7203.T']['last_download_mode']=='history_backfill'


def test_earlier_start_backfills_without_downloading_cached_middle(config, tmp_path, monkeypatch):
    init_dirs(tmp_path)
    old=seed_prices(tmp_path,config)
    manifest={'price:7203.T':{'requested_start':'2015-01-01','checked_through':'2020-06-06','completed_through':'2020-06-05'}}
    atomic_json(manifest,tmp_path/'data/download_manifest.json')
    d=Downloader(tmp_path,config)
    calls=[]
    prefix=pd.concat([valid_frame('2010-01-04'),old.iloc[:1]])
    def request(tickers,start,end=None):
        calls.append((start,end))
        return pd.concat({'7203.T':prefix if end is not None else valid_frame('2020-06-05',n=3)},axis=1)
    monkeypatch.setattr(d,'_request',request)
    d.download_prices(['7203.T'])
    assert len(calls)==2
    assert calls[0][0] == old.index[-1]
    assert calls[1] == (d.start,old.index[0]+pd.Timedelta(days=1))
    assert d.manifest['price:7203.T']['requested_start']==str(d.start.date())


def test_unfinished_bar_revision_does_not_trigger_full_refetch(config,tmp_path,monkeypatch):
    init_dirs(tmp_path)
    old=seed_prices(tmp_path,config)
    meta={'price:7203.T':{'requested_start':str(acquisition_start(config).date()),'checked_through':'2020-06-06','completed_through':'2020-06-04'}}
    atomic_json(meta,tmp_path/'data/download_manifest.json')
    d=Downloader(tmp_path,config)
    new=old.loc['2020-06-04':].copy()
    new.iloc[-1,new.columns.get_loc('Close')]=105
    new.iloc[-1,new.columns.get_loc('Adj Close')]=94.5
    new.iloc[-1,new.columns.get_loc('Volume')]=2000
    calls=[]
    def request(tickers,start):
        calls.append(start)
        return pd.concat({'7203.T':new},axis=1)
    monkeypatch.setattr(d,'_request',request)
    d.download_prices(['7203.T'])
    assert calls==[pd.Timestamp('2020-06-04')]
    assert d.manifest['price:7203.T']['last_download_mode']=='incremental'


def test_failed_rebase_preserves_existing_cache(config,tmp_path,monkeypatch):
    init_dirs(tmp_path)
    old=seed_prices(tmp_path,config)
    config['download'].update(max_retries=1,retry_backoff_seconds=0)
    d=Downloader(tmp_path,config)
    calls=[]
    def request(tickers,start):
        calls.append(start)
        if len(calls)==1:
            tail=old.iloc[-1:].copy();tail['Adj Close']*=.9
            return pd.concat({'7203.T':tail},axis=1)
        return pd.DataFrame()
    monkeypatch.setattr(d,'_request',request)
    d.download_prices(['7203.T'])
    pd.testing.assert_frame_equal(pd.read_parquet(tmp_path/'data/market/7203.T.parquet'),old,check_freq=False)
    assert d.status[-1]['status']=='failed'
    assert calls==[old.index[-1],d.start]


def seed_shares(tmp_path,config,failed_ranges=None):
    old=pd.DataFrame({'historical_shares':[1000.]},index=pd.DatetimeIndex(['2020-06-01'],name='Date'))
    atomic_parquet(old,tmp_path/'data/shares/7203.T.parquet')
    atomic_json({'shares:7203.T':{'requested_start':str(acquisition_start(config).date()),'checked_through':'2020-06-06',
                                 'completed_through':'2020-06-05','failed_ranges':failed_ranges or []}},
                tmp_path/'data/download_manifest.json')
    return old


def test_shares_incremental_from_checked_period_not_last_observation(config,tmp_path,monkeypatch):
    init_dirs(tmp_path)
    old=seed_shares(tmp_path,config)
    d=Downloader(tmp_path,config);d.end=pd.Timestamp('2020-06-10')
    calls=[]
    class FakeTicker:
        def get_shares_full(self,start,end):
            calls.append((start,end))
            return pd.Series([1100.],index=pd.to_datetime(['2020-06-08']))
    monkeypatch.setattr('src.downloader.yf.Ticker',lambda _:FakeTicker())
    d.download_shares(['7203.T'])
    assert calls==[('2020-06-06','2020-06-10')]
    combined=pd.read_parquet(tmp_path/'data/shares/7203.T.parquet')
    assert combined.loc[old.index[0],'historical_shares']==1000
    assert combined.loc[pd.Timestamp('2020-06-08'),'historical_shares']==1100


def test_shares_failed_ranges_only_are_retried_and_old_data_kept(config,tmp_path,monkeypatch):
    init_dirs(tmp_path)
    old=seed_shares(tmp_path,config,failed_ranges=[{'start':'2019-01-01','end':'2019-02-01','error':'timeout'}])
    d=Downloader(tmp_path,config);d.end=pd.Timestamp('2020-06-10')
    calls=[]
    class FakeTicker:
        def get_shares_full(self,start,end):
            calls.append((start,end))
            if start=='2019-01-01':
                return pd.Series([900.],index=pd.to_datetime(['2019-01-10']))
            return pd.Series([1100.],index=pd.to_datetime(['2020-06-08']))
    monkeypatch.setattr('src.downloader.yf.Ticker',lambda _:FakeTicker())
    d.download_shares(['7203.T'],force_tickers=['7203.T'])
    assert calls==[('2019-01-01','2019-02-01'),('2020-06-06','2020-06-10')]
    combined=pd.read_parquet(tmp_path/'data/shares/7203.T.parquet')
    assert len(combined)==3
    assert combined.loc[old.index[0],'historical_shares']==1000
    assert d.manifest['shares:7203.T']['failed_ranges']==[]


def test_shares_failure_is_saved_for_range_retry(config,tmp_path,monkeypatch):
    init_dirs(tmp_path)
    old=seed_shares(tmp_path,config)
    config['download'].update(max_retries=1,retry_backoff_seconds=0)
    d=Downloader(tmp_path,config);d.end=pd.Timestamp('2020-06-10')
    class FakeTicker:
        def get_shares_full(self,**kwargs):
            raise TimeoutError('timeout')
    monkeypatch.setattr('src.downloader.yf.Ticker',lambda _:FakeTicker())
    d.download_shares(['7203.T'])
    pd.testing.assert_frame_equal(pd.read_parquet(tmp_path/'data/shares/7203.T.parquet'),old,check_index_type=False)
    assert d.manifest['shares:7203.T']['failed_ranges']==[{'start':'2020-06-06','end':'2020-06-10','error':'timeout'}]


def test_benchmarks_also_only_update_latest_tail(config,tmp_path,monkeypatch):
    init_dirs(tmp_path)
    old=valid_frame()
    atomic_parquet(old,tmp_path/'data/benchmark/^N225.parquet')
    atomic_json({'benchmark:^N225':{'requested_start':str(acquisition_start(config).date()),'checked_through':'2020-06-06','completed_through':'2020-06-05'}},tmp_path/'data/download_manifest.json')
    d=Downloader(tmp_path,config)
    calls=[]
    def request(tickers,start):
        calls.append((tickers,start))
        return pd.concat({'^N225':valid_frame('2020-06-05',n=3)},axis=1)
    monkeypatch.setattr(d,'_request',request)
    d.download_prices(['^N225'],kind='benchmark')
    assert calls==[(['^N225'],old.index[-1])]
    assert d.manifest['benchmark:^N225']['last_download_mode']=='incremental'


def test_default_cli_updates_and_no_update_is_explicit():
    from main import parser
    for command in ('download','all'):
        assert parser().parse_args([command]).update
        assert parser().parse_args([command,'--update']).update
        assert not parser().parse_args([command,'--no-update']).update


def test_shares_up_to_date_skips_api(config,tmp_path,monkeypatch):
    from src.utils import today,last_completed_date,read_json
    init_dirs(tmp_path)
    seed_shares(tmp_path,config)
    meta=read_json(tmp_path/'data/download_manifest.json')
    meta['shares:7203.T'].update(checked_through=str((today()+pd.Timedelta(days=1)).date()),completed_through=str(last_completed_date().date()))
    atomic_json(meta,tmp_path/'data/download_manifest.json')
    monkeypatch.setattr('src.downloader.yf.Ticker',lambda _:(_ for _ in ()).throw(AssertionError('network call')))
    d=Downloader(tmp_path,config)
    d.download_shares(['7203.T'])
    assert d.status[-1]['status']=='cached'


def test_truncated_rebase_does_not_replace_historical_cache(config,tmp_path,monkeypatch):
    init_dirs(tmp_path)
    old=seed_prices(tmp_path,config)
    config['download'].update(max_retries=1,retry_backoff_seconds=0)
    d=Downloader(tmp_path,config)
    tail=old.iloc[-1:].copy();tail['Adj Close']*=.9
    monkeypatch.setattr(d,'_request',lambda *a:pd.concat({'7203.T':tail},axis=1))
    d.download_prices(['7203.T'])
    pd.testing.assert_frame_equal(pd.read_parquet(tmp_path/'data/market/7203.T.parquet'),old,check_freq=False)
    assert d.status[-1]['status']=='failed'
    assert 'truncated' in d.status[-1]['error']


def test_later_analysis_start_does_not_forget_older_failed_shares_range(config,tmp_path,monkeypatch):
    init_dirs(tmp_path)
    seed_shares(tmp_path,config,failed_ranges=[{'start':'2019-01-01','end':'2019-02-01','error':'timeout'}])
    config['data']['start_date']='2022-01-01'
    config['download'].update(max_retries=1,retry_backoff_seconds=0)
    d=Downloader(tmp_path,config);d.end=pd.Timestamp('2022-06-10')
    calls=[]
    class FakeTicker:
        def get_shares_full(self,start,end):
            calls.append((start,end))
            if start=='2019-01-01':
                raise TimeoutError('still unavailable')
            return None
    monkeypatch.setattr('src.downloader.yf.Ticker',lambda _:FakeTicker())
    d.download_shares(['7203.T'])
    assert calls[0]==('2019-01-01','2019-02-01')
    assert calls[1][0]=='2020-06-06'
    assert d.manifest['shares:7203.T']['failed_ranges']==[{'start':'2019-01-01','end':'2019-02-01','error':'still unavailable'}]
