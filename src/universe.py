from __future__ import annotations

from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
import re
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
import logging
import pandas as pd
from .utils import atomic_json, read_json, today

log = logging.getLogger(__name__)
JPX_MARKETS = {'プライム（内国株式）': 'Prime', 'スタンダード（内国株式）': 'Standard', 'グロース（内国株式）': 'Growth'}


def to_ticker(code) -> str:
    text = str(code).strip().upper()
    if re.fullmatch(r'\d{4}\.0', text):
        text = text[:-2]
    if not re.fullmatch(r'[0-9][0-9A-Z]{3}', text):
        raise ValueError(f'Invalid JPX code: {code!r}')
    return text + '.T'


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.links.extend(v for k, v in attrs if k == 'href' and v)


def fetch(url: str) -> bytes:
    req = Request(url, headers={'User-Agent': 'Mozilla/5.0 (JapaneseEquityResearch/1.0)'})
    with urlopen(req, timeout=30) as response:
        return response.read()


def normalize_master(df: pd.DataFrame, markets: list[str]) -> pd.DataFrame:
    if 'コード' in df.columns:
        # A strict allowlist removes ETF/ETN/REIT/foreign/preferred/PRO products.
        df = df[df['市場・商品区分'].isin(JPX_MARKETS)].copy()
        df['market_segment'] = df['市場・商品区分'].map(JPX_MARKETS)
        df = df.rename(columns={'コード': 'code', '銘柄名': 'company_name', '33業種区分': 'sector'})
        # JPX includes five-digit preferred issues (e.g. 25935) in the domestic
        # equity category. They are not the four-character ordinary-stock code.
        ordinary_code = df['code'].astype(str).str.replace(r'\.0$', '', regex=True).str.fullmatch(r'[0-9A-Z]{4}')
        df = df[ordinary_code].copy()
    required = ['code', 'company_name', 'market_segment', 'sector']
    if missing := set(required) - set(df.columns):
        raise ValueError(f'Universe columns missing: {sorted(missing)}')
    df = df.loc[df['market_segment'].isin(markets), required].copy()
    df['ticker'] = df['code'].map(to_ticker)
    df['code'] = df['ticker'].str.removesuffix('.T')
    df['sector'] = df['sector'].replace('-', pd.NA).fillna('unknown')
    if df.empty or df['code'].duplicated().any() or df['company_name'].isna().any():
        raise ValueError('Universe is empty, has duplicates or missing company names')
    return df.sort_values('code').reset_index(drop=True)


def load_universe(root: Path, c: dict, refresh: bool = False, manual: bool = False) -> pd.DataFrame:
    folder = root / 'data/universe'
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / 'universe.csv'
    meta_path = folder / 'source.json'
    meta = read_json(meta_path)
    if manual or (dest.exists() and not refresh):
        if not dest.exists():
            raise FileNotFoundError(f'Place a domestic ordinary-stock CSV at {dest}')
        full = normalize_master(pd.read_csv(dest, dtype={'code': str}), ['Prime', 'Standard', 'Growth'])
        if manual:
            atomic_json({'source': 'manual_csv', 'as_of': '利用者CSV（基準日不明）',
                         'total_domestic_ordinary_stocks': len(full)}, meta_path)
        return full[full.market_segment.isin(c['universe']['markets'])].reset_index(drop=True)
    page = c['universe']['jpx_page']
    try:
        html = fetch(page).decode('utf-8')
        parser = Links()
        parser.feed(html)
        candidates = [urljoin(page, link) for link in parser.links if re.search(r'data_j\.(xlsx?|zip)(?:\?|$)', link, re.I)]
        if not candidates:
            raise ValueError('Latest JPX workbook link not found')
        url = candidates[0]
        if not urlparse(url).hostname.endswith('jpx.co.jp'):
            raise ValueError('Unexpected JPX download host')
        content = fetch(url)
        # File extensions on JPX can lag behind actual XLSX content.
        ext = 'xlsx' if content[:2] == b'PK' else 'xls'
        raw = pd.read_excel(BytesIO(content), engine='openpyxl' if ext == 'xlsx' else 'xlrd')
        df = normalize_master(raw, ['Prime', 'Standard', 'Growth'])
        (folder / f'jpx_source.{ext}').write_bytes(content)
        temp = dest.with_suffix('.tmp.csv')
        df.to_csv(temp, index=False, encoding='utf-8-sig')
        temp.replace(dest)
        atomic_json({'source': page, 'workbook_url': url, 'fetched_date': str(today().date()),
                     'as_of': str(raw['日付'].iloc[0]) if '日付' in raw else None,
                     'total_domestic_ordinary_stocks': len(df)}, meta_path)
        return df[df.market_segment.isin(c['universe']['markets'])].reset_index(drop=True)
    except Exception as e:
        # Never claim a cached master was refreshed after a failed request.
        if dest.exists():
            log.warning('JPX refresh failed: %s; using cached master dated %s', e, meta.get('as_of', 'unknown'))
            atomic_json({**meta, 'last_refresh_error': str(e)}, meta_path)
            return normalize_master(pd.read_csv(dest, dtype={'code': str}), c['universe']['markets'])
        raise RuntimeError(f'JPX acquisition failed ({e}). Place a manual CSV at {dest}') from e
