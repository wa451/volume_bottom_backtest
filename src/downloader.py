from __future__ import annotations

import logging
import time
from pathlib import Path
import pandas as pd
import numpy as np
import yfinance as yf
from tqdm import tqdm
from .data_loader import normalize_prices, normalize_shares, load_prices
from .utils import acquisition_start, today, last_completed_date, read_json, atomic_json, atomic_parquet

log = logging.getLogger(__name__)


class Downloader:
    """Writes each successful ticker immediately; logs remain valid after interruption."""
    def __init__(self, root: Path, config: dict):
        self.root, self.c = root, config
        if any(config['data'].get(k, 'yahoo_split_adjusted') != 'yahoo_split_adjusted' for k in ('price_basis', 'volume_basis')):
            raise ValueError('yfinance download requires yahoo_split_adjusted bases; raw is only for manually imported caches')
        self.manifest_path = root / 'data/download_manifest.json'
        self.manifest = read_json(self.manifest_path)
        self.failure_path = root / 'results/logs/failed_tickers.csv'
        self.failures = {}
        if self.failure_path.exists():
            for row in pd.read_csv(self.failure_path).to_dict('records'):
                self.failures[(row['ticker'], row['kind'])] = row
        self.status = []
        self.start = acquisition_start(config)
        # Yahoo's split-normalized price basis is the present snapshot even for a
        # historical end request. Keep all actions through this snapshot locally.
        self.end = today() + pd.Timedelta(days=1)

    def save_manifest(self):
        atomic_json(self.manifest, self.manifest_path)

    def outcome(self, ticker: str, kind: str, status: str, error: str = ''):
        row = {'ticker': ticker, 'kind': kind, 'status': status, 'error': error,
               'checked_at': pd.Timestamp.now(tz='Asia/Tokyo').isoformat()}
        self.status.append(row)
        key = (ticker, kind)
        if status == 'failed':
            self.failures[key] = row
        else:
            self.failures.pop(key, None)
        self.failure_path.parent.mkdir(parents=True, exist_ok=True)
        cols = ['ticker', 'kind', 'status', 'error', 'checked_at']
        temp = self.failure_path.with_suffix('.tmp.csv')
        pd.DataFrame(list(self.failures.values()), columns=cols).to_csv(temp, index=False)
        temp.replace(self.failure_path)
        atomic_json(self.status, self.root / 'results/logs/download_last_run.json')

    def _request(self, tickers: list[str], start: pd.Timestamp) -> pd.DataFrame:
        return yf.download(tickers=tickers, start=start.date().isoformat(), end=self.end.date().isoformat(),
                           interval='1d', auto_adjust=False, actions=True, repair=self.c['data']['repair'],
                           threads=self.c['download']['threads'], timeout=self.c['download'].get('timeout_seconds', 30),
                           group_by='ticker', progress=False, keepna=True)

    @staticmethod
    def _select(result, ticker):
        if result.empty:
            raise ValueError('Yahoo returned no data (API limit, ticker missing or network failure)')
        if isinstance(result.columns, pd.MultiIndex):
            if ticker in result.columns.get_level_values(0):
                result = result[ticker]
            elif ticker in result.columns.get_level_values(1):
                result = result.xs(ticker, axis=1, level=1)
            else:
                raise ValueError('Ticker absent from batch response')
        return normalize_prices(result.dropna(how='all'))

    def _price_plan(self, ticker, kind, update, force=False):
        folder = 'benchmark' if kind == 'benchmark' else 'market'
        path = self.root / f'data/{folder}/{ticker}.parquet'
        key = f'{kind}:{ticker}'
        meta = self.manifest.get(key, {})
        old = None
        if path.exists():
            try:
                old = load_prices(path)
            except Exception as e:
                log.warning('Invalid cache for %s: %s; refetching', ticker, e)
        needs_backfill = not meta.get('requested_start') or pd.Timestamp(meta['requested_start']) > self.start
        if old is not None and not force and not needs_backfill:
            if not update or (meta.get('checked_through') == str(self.end.date()) and meta.get('completed_through') == str(last_completed_date().date())):
                self.outcome(ticker, kind, 'cached')
                return None
            # A tail overlap detects rebasing of adjusted prices on new actions.
            start = max(self.start, old.index[-1] - pd.Timedelta(days=14))
        else:
            start = self.start
        return ticker, kind, path, old, start

    @staticmethod
    def _basis_changed(old: pd.DataFrame, new: pd.DataFrame) -> bool:
        common = old.index.intersection(new.index)
        if common.empty:
            return True
        for col in ('Open', 'Close', 'Adj Close', 'Volume', 'Stock Splits', 'Dividends'):
            a = old.loc[common, col].to_numpy(float)
            b = new.loc[common, col].to_numpy(float)
            valid = np.isfinite(a) & np.isfinite(b)
            if valid.any() and not np.allclose(a[valid], b[valid], rtol=1e-6, atol=1e-7):
                return True
        tail = new[new.index > old.index[-1]]
        return bool(tail[['Stock Splits', 'Dividends']].fillna(0).ne(0).any().any())

    def download_prices(self, tickers, kind='price', update=False, force_tickers=()):
        plans = [p for t in tickers if (p := self._price_plan(t, kind, update, t in force_tickers)) is not None]
        by_start = {}
        for p in plans:
            by_start.setdefault(p[4], []).append(p)
        batch_size = self.c['download']['batch_size']
        with tqdm(total=len(plans), desc=kind) as bar:
            for start, grouped in by_start.items():
                for offset in range(0, len(grouped), batch_size):
                    pending = grouped[offset:offset + batch_size]
                    errors = {}
                    for attempt in range(self.c['download']['max_retries']):
                        try:
                            response = self._request([p[0] for p in pending], start)
                        except Exception as e:
                            response = pd.DataFrame()
                            errors.update({p[0]: str(e) for p in pending})
                        remaining = []
                        for ticker, pkind, path, old, request_start in pending:
                            try:
                                new = self._select(response, ticker)
                                if old is not None and request_start > self.start and self._basis_changed(old, new):
                                    # Refetch, rather than merging incompatible historical units.
                                    new = self._select(self._request([ticker], self.start), ticker)
                                    old = None
                                if request_start == self.start:
                                    old = None
                                combined = pd.concat([old, new]) if old is not None else new
                                combined = normalize_prices(combined)
                                atomic_parquet(combined, path)
                                self.manifest[f'{pkind}:{ticker}'] = {
                                    'requested_start': str(self.start.date()), 'checked_through': str(self.end.date()),
                                    'completed_through': str(last_completed_date().date()),
                                    'first_bar': str(combined.index[0].date()), 'last_bar': str(combined.index[-1].date()),
                                    'price_basis': 'yahoo_split_adjusted', 'volume_basis': 'yahoo_split_adjusted'}
                                self.save_manifest()
                                self.outcome(ticker, pkind, 'downloaded')
                                bar.update(1)
                            except Exception as e:
                                errors[ticker] = str(e)
                                remaining.append((ticker, pkind, path, old, request_start))
                        pending = remaining
                        if not pending:
                            break
                        if attempt + 1 < self.c['download']['max_retries']:
                            time.sleep(self.c['download']['retry_backoff_seconds'] * 2 ** attempt)
                    for p in pending:
                        self.outcome(p[0], p[1], 'failed', errors.get(p[0], 'Unknown download failure'))
                        bar.update(1)

    def download_shares(self, tickers, update=False, force_tickers=()):
        for ticker in tqdm(tickers, desc='shares'):
            path = self.root / f'data/shares/{ticker}.parquet'
            key = f'shares:{ticker}'
            meta = self.manifest.get(key, {})
            old = pd.read_parquet(path) if path.exists() else None
            backfill = not meta.get('requested_start') or pd.Timestamp(meta['requested_start']) > self.start
            if old is not None and ticker not in force_tickers and not backfill:
                if not update or meta.get('checked_through') == str(self.end.date()):
                    if old.empty:
                        self.outcome(ticker, 'shares', 'failed', 'Cached missing historical shares; use --retry-failed')
                    else:
                        self.outcome(ticker, 'shares', 'cached')
                    continue
                start = max(self.start, pd.Timestamp(meta.get('checked_through', self.start)) - pd.Timedelta(days=7))
            else:
                start, old = self.start, None
            ticker_obj = yf.Ticker(ticker)
            chunks = []
            chunk_start = start
            errors = []
            # Shares API can reject long spans. Split into bounded requests.
            while chunk_start < self.end:
                chunk_end = min(self.end, chunk_start + pd.DateOffset(years=self.c['download'].get('shares_chunk_years', 2)))
                error = 'Historical shares missing (Yahoo API coverage constraint)'
                for attempt in range(self.c['download']['max_retries']):
                    try:
                        chunk = normalize_shares(ticker_obj.get_shares_full(start=str(chunk_start.date()), end=str(chunk_end.date())))
                        chunk = chunk.loc[(chunk.index >= chunk_start) & (chunk.index < chunk_end)]
                        # An empty historical span is normal; retrying cannot create coverage.
                        chunks.append(chunk)
                        error = ''
                        break
                    except Exception as e:
                        error = str(e)
                        if attempt + 1 < self.c['download']['max_retries']:
                            time.sleep(self.c['download']['retry_backoff_seconds'] * 2 ** attempt)
                if error:
                    errors.append(f'{chunk_start.date()}: {error}')
                chunk_start = chunk_end
            combined = normalize_shares(pd.concat(([old] if old is not None else []) + chunks)) if chunks or old is not None else normalize_shares(None)
            atomic_parquet(combined, path)
            self.manifest[key] = {'requested_start': str(self.start.date()), 'checked_through': str(self.end.date()),
                                  'rows': len(combined), 'partial_errors': errors}
            self.save_manifest()
            if errors or combined.empty:
                self.outcome(ticker, 'shares', 'failed', '; '.join(errors) or 'No historical shares; missing, no current-value fallback')
            else:
                self.outcome(ticker, 'shares', 'downloaded')

    def run(self, universe, update=False, retry_failed=False):
        tickers = universe.ticker.tolist()
        failed = set(self.failures)
        prices = [t for t in tickers if not retry_failed or (t, 'price') in failed]
        shares = [t for t in tickers if not retry_failed or (t, 'shares') in failed]
        self.download_prices(prices, update=update, force_tickers=prices if retry_failed else ())
        self.download_shares(shares, update=update, force_tickers=shares if retry_failed else ())
        if self.c.get('benchmark', {}).get('enabled', True):
            benchmarks = self.c['benchmark']['tickers']
            if retry_failed:
                benchmarks = [t for t in benchmarks if (t, 'benchmark') in failed]
            self.download_prices(benchmarks, kind='benchmark', update=update, force_tickers=benchmarks if retry_failed else ())
        return self.status
