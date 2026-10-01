from copy import deepcopy
import numpy as np
import pandas as pd
import pytest
from src.utils import load_config


@pytest.fixture
def config():
    c = deepcopy(load_config())
    c['validation']['bootstrap_samples'] = 100
    c['benchmark']['enabled'] = False
    c['output']['heatmaps'] = False
    return c


@pytest.fixture
def prices():
    idx = pd.bdate_range('2020-06-01', periods=340).as_unit('ns')
    df = pd.DataFrame({'Open': 100., 'High': 110., 'Low': 90., 'Close': 100., 'Adj Close': 100.,
                       'Volume': 100., 'Dividends': 0., 'Stock Splits': 0.}, index=idx)
    df.index.name = 'Date'
    return df


@pytest.fixture
def info():
    return {'code': '7203', 'ticker': '7203.T', 'company_name': 'Test', 'market_segment': 'Prime', 'sector': 'Test'}
