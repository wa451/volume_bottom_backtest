from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
import pandas as pd
import numpy as np
import yfinance as yf
from tqdm import tqdm
from .data_loader import normalize_prices, normalize_shares, load_prices, exchange_sessions
from .utils import acquisition_start, today, last_completed_date, read_json, atomic_json, atomic_parquet

log = logging.getLogger(__name__)


@dataclass
class PricePlan:
    ticker: str
    kind: str
    path: Path
    old: pd.DataFrame | None
    start: pd.Timestamp
    coverage_start: pd.Timestamp
    completed_through: pd.Timestamp

    def needs_backfill(self, required_start):
        return self.old is not None and required_start < self.coverage_start


class Downloader:
    """Writes each successful ticker immediately; logs remain valid after interruption."""
    def __init__(self, root: Path, config: dict, progress=None):
        self.root, self.c = root, config
        self.progress = progress
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
        if self.progress:
            self.progress(row, len(self.status))

    def _request(self, tickers: list[str], start: pd.Timestamp, end: pd.Timestamp | None = None) -> pd.DataFrame:
        end = self.end if end is None else end
        return yf.download(tickers=tickers, start=start.date().isoformat(), end=end.date().isoformat(),
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
        if old is not None:
            coverage_start = pd.Timestamp(meta.get('requested_start', old.index[0]))
            completed = min(pd.Timestamp(meta.get('completed_through', min(old.index[-1], today() - pd.Timedelta(days=1)))),
                            self._confirmed_price_date(old))
            needs_backfill = self.start < coverage_start
            if not force and (not update or (not needs_backfill and meta.get('checked_through') == str(self.end.date()) and completed >= self._latest_completed_session())):
                self.outcome(ticker, kind, 'cached')
                return None
            # One final completed bar detects a changed adjustment basis. Include
            # any unfinished tail, without routinely requesting 14 historical days.
            confirmed = old.index[old.index <= completed]
            start = confirmed[-1] if len(confirmed) else old.index[-1]
        else:
            start = self.start
            coverage_start, completed = self.start, pd.Timestamp('1900-01-01')
        return PricePlan(ticker, kind, path, old, start, coverage_start, completed)

    @staticmethod
    def _confirmed_price_date(frame):
        valid = frame.index[(frame.index <= last_completed_date()) & frame.Close.gt(0) & frame['Adj Close'].gt(0)]
        return valid[-1] if len(valid) else pd.Timestamp('1900-01-01')

    @staticmethod
    def _latest_completed_session():
        end = last_completed_date()
        sessions = exchange_sessions(str((end - pd.Timedelta(days=31)).date()), str(end.date()))
        return sessions[-1]

    @staticmethod
    def _basis_changed(old: pd.DataFrame, new: pd.DataFrame, completed_through=None) -> bool:
        common = old.index.intersection(new.index)
        if common.empty:
            return True
        for col in ('Open', 'Close', 'Adj Close', 'Volume', 'Stock Splits', 'Dividends'):
            compare = common
            if completed_through is not None and col not in ('Stock Splits', 'Dividends'):
                compare = compare[compare <= completed_through]
            a = old.loc[compare, col].to_numpy(float)
            b = new.loc[compare, col].to_numpy(float)
            valid = np.isfinite(a) & np.isfinite(b)
            if valid.any() and not np.allclose(a[valid], b[valid], rtol=1e-6, atol=1e-7):
                return True
        tail = new[new.index > old.index[-1]]
        return bool(tail[['Stock Splits', 'Dividends']].fillna(0).ne(0).any().any())

    def download_prices(self, tickers, kind='price', update=True, force_tickers=()):
        plans = [p for t in tickers if (p := self._price_plan(t, kind, update, t in force_tickers)) is not None]
        by_start = {}
        for p in plans:
            by_start.setdefault(p.start, []).append(p)
        batch_size = self.c['download']['batch_size']
        with tqdm(total=len(plans), desc=kind) as bar:
            for start, grouped in by_start.items():
                for offset in range(0, len(grouped), batch_size):
                    pending = grouped[offset:offset + batch_size]
                    errors = {}
                    for attempt in range(self.c['download']['max_retries']):
                        try:
                            response = self._request([p.ticker for p in pending], start)
                        except Exception as e:
                            response = pd.DataFrame()
                            errors.update({p.ticker: str(e) for p in pending})
                        remaining = []
                        for plan in pending:
                            ticker, pkind, path, old = plan.ticker, plan.kind, plan.path, plan.old
                            try:
                                new = self._select(response, ticker)
                                mode = 'initial_full' if old is None else 'incremental'
                                if old is not None and self._basis_changed(old, new, plan.completed_through):
                                    # Refetch, rather than merging incompatible historical units.
                                    log.info('%s: adjustment basis changed; refreshing full history', ticker)
                                    full_start = min(self.start, plan.coverage_start, old.index[0])
                                    new = self._select(self._request([ticker], full_start), ticker)
                                    if new.index[0] > old.index[0] or new.index[-1] < old.index[-1]:
                                        raise ValueError('Full refresh is truncated; preserving previous cache')
                                    old = None
                                    mode = 'rebase_full'
                                elif plan.needs_backfill(self.start):
                                    # Legacy caches and an earlier analysis start only need
                                    # the missing prefix, not a repeat of the cached history.
                                    prefix_anchor = old.index[0]
                                    prefix = self._select(self._request([ticker], self.start, end=prefix_anchor + pd.Timedelta(days=1)), ticker)
                                    prefix = prefix.loc[prefix.index <= prefix_anchor]
                                    if prefix.empty:
                                        raise ValueError('Missing historical prefix; preserving previous cache')
                                    if prefix_anchor in prefix.index and self._basis_changed(old, prefix):
                                        log.info('%s: prefix adjustment basis changed; refreshing full history', ticker)
                                        full_start = min(self.start, plan.coverage_start, old.index[0])
                                        new = self._select(self._request([ticker], full_start), ticker)
                                        if new.index[0] > old.index[0] or new.index[-1] < old.index[-1]:
                                            raise ValueError('Full refresh is truncated; preserving previous cache')
                                        old = None
                                        mode = 'rebase_full'
                                    else:
                                        new = pd.concat([prefix, new])
                                        mode = 'history_backfill'
                                combined = pd.concat([old, new]) if old is not None else new
                                combined = normalize_prices(combined)
                                # An old intraday tail does not become confirmed merely
                                # because the clock passed 16:00: require a fresh bar.
                                completed = self._confirmed_price_date(new)
                                if old is not None:
                                    completed = max(plan.completed_through, completed)
                                completed = min(completed, self._confirmed_price_date(combined))
                                atomic_parquet(combined, path)
                                self.manifest[f'{pkind}:{ticker}'] = {
                                    'requested_start': str(min(self.start, plan.coverage_start).date()), 'checked_through': str(self.end.date()),
                                    'completed_through': str(completed.date()),
                                    'first_bar': str(combined.index[0].date()), 'last_bar': str(combined.index[-1].date()),
                                    'last_download_mode': mode,
                                    'price_basis': 'yahoo_split_adjusted', 'volume_basis': 'yahoo_split_adjusted'}
                                self.save_manifest()
                                self.outcome(ticker, pkind, 'downloaded')
                                bar.update(1)
                            except Exception as e:
                                errors[ticker] = str(e)
                                remaining.append(plan)
                        pending = remaining
                        if not pending:
                            break
                        if attempt + 1 < self.c['download']['max_retries']:
                            time.sleep(self.c['download']['retry_backoff_seconds'] * 2 ** attempt)
                    for p in pending:
                        self.outcome(p.ticker, p.kind, 'failed', errors.get(p.ticker, 'Unknown download failure'))
                        bar.update(1)

    @staticmethod
    def _merge_ranges(ranges):
        merged = []
        for start, end in sorted(ranges):
            if start >= end:
                continue
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        return merged

    def download_shares(self, tickers, update=True, force_tickers=()):
        for ticker in tqdm(tickers, desc='shares'):
            path = self.root / f'data/shares/{ticker}.parquet'
            key = f'shares:{ticker}'
            meta = self.manifest.get(key, {})
            old = None
            if path.exists():
                try:
                    old = normalize_shares(pd.read_parquet(path))
                except Exception as e:
                    log.warning('Invalid shares cache for %s: %s; refetching', ticker, e)
            coverage_start = pd.Timestamp(meta.get('requested_start', old.index[0] if old is not None and not old.empty else self.start))
            if old is None:
                coverage_start = self.start
            failed_ranges = meta.get('failed_ranges', [])
            if not failed_ranges and meta.get('partial_errors'):
                # Migrate error spans produced by the previous manifest format.
                failed_ranges = [
                    {'start': error.split(':', 1)[0],
                     'end': str(min(pd.Timestamp(error.split(':', 1)[0]) + pd.DateOffset(years=self.c['download'].get('shares_chunk_years', 2)), self.end).date()),
                     'error': error}
                    for error in meta['partial_errors']]
            up_to_date = (meta.get('checked_through') == str(self.end.date())
                          and pd.Timestamp(meta.get('completed_through', '1900-01-01')) >= last_completed_date()
                          and self.start >= coverage_start and not failed_ranges)
            if old is not None and ticker not in force_tickers and (not update or up_to_date):
                if old.empty or failed_ranges:
                    self.outcome(ticker, 'shares', 'failed', 'Cached missing/partial historical shares; use --retry-failed')
                else:
                    self.outcome(ticker, 'shares', 'cached')
                continue
            ranges = []
            if old is None or (old.empty and ticker in force_tickers and not failed_ranges):
                ranges.append((self.start, self.end))
            else:
                if self.start < coverage_start:
                    ranges.append((self.start, min(coverage_start, self.end)))
                checked = pd.Timestamp(meta['checked_through']) if meta.get('checked_through') else (old.index[-1] if not old.empty else self.start)
                # Check only newly elapsed dates, or today when refreshing an
                # unfinished same-day snapshot. Sparse share observations do not
                # require requerying every date since the last observation.
                latest_start = min(checked, self.end - pd.Timedelta(days=1))
                ranges.append((latest_start, self.end))
                # Retain known holes when a later analysis start is selected.
                ranges.extend((pd.Timestamp(r['start']), min(self.end, pd.Timestamp(r['end']))) for r in failed_ranges)
            ticker_obj = yf.Ticker(ticker)
            chunks = []
            errors = []
            failures = []
            # Shares API can reject long spans. Split into bounded requests.
            for range_start, range_end in self._merge_ranges(ranges):
                chunk_start = range_start
                while chunk_start < range_end:
                    chunk_end = min(range_end, chunk_start + pd.DateOffset(years=self.c['download'].get('shares_chunk_years', 2)))
                    error = 'Historical shares missing (Yahoo API coverage constraint)'
                    for attempt in range(self.c['download']['max_retries']):
                        try:
                            chunk = normalize_shares(ticker_obj.get_shares_full(start=str(chunk_start.date()), end=str(chunk_end.date())))
                            chunk = chunk.loc[(chunk.index >= chunk_start) & (chunk.index < chunk_end)]
                            chunks.append(chunk)
                            error = ''
                            break
                        except Exception as e:
                            error = str(e)
                            if attempt + 1 < self.c['download']['max_retries']:
                                time.sleep(self.c['download']['retry_backoff_seconds'] * 2 ** attempt)
                    if error:
                        errors.append(f'{chunk_start.date()}: {error}')
                        failures.append({'start': str(chunk_start.date()), 'end': str(chunk_end.date()), 'error': error})
                    chunk_start = chunk_end
            combined = normalize_shares(pd.concat(([old] if old is not None else []) + chunks)) if chunks or old is not None else normalize_shares(None)
            atomic_parquet(combined, path)
            self.manifest[key] = {'requested_start': str(min(self.start, coverage_start).date()), 'checked_through': str(self.end.date()),
                                  'completed_through': str(last_completed_date().date()),
                                  'rows': len(combined), 'partial_errors': errors, 'failed_ranges': failures}
            self.save_manifest()
            if errors or combined.empty:
                self.outcome(ticker, 'shares', 'failed', '; '.join(errors) or 'No historical shares; missing, no current-value fallback')
            else:
                self.outcome(ticker, 'shares', 'downloaded')

    def run(self, universe, update=True, retry_failed=False):
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
