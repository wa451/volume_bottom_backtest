#!/usr/bin/env python3
from __future__ import annotations
import argparse
import logging
from pathlib import Path
import sys
from filelock import FileLock, Timeout
from src.utils import ROOT, load_config, init_dirs
from src.universe import load_universe
from src.downloader import Downloader
from src.backtest import run_backtest
from src.report import analyze


def parser():
    p = argparse.ArgumentParser(description='Japanese stock volume-bottom event study')
    p.add_argument('--config', type=Path, default=ROOT / 'config.yaml')
    p.add_argument('--root', type=Path, default=ROOT, help='Isolated data/results directory')
    sub = p.add_subparsers(dest='command', required=True)
    for name in ('download', 'backtest', 'analyze', 'all'):
        cmd = sub.add_parser(name)
        # Accept common options before or after the command.
        cmd.add_argument('--config', type=Path, default=argparse.SUPPRESS)
        cmd.add_argument('--root', type=Path, default=argparse.SUPPRESS)
        if name != 'analyze':
            cmd.add_argument('--limit', type=int, help='Small deterministic smoke-test universe')
            cmd.add_argument('--tickers', nargs='+', help='Codes or Yahoo .T tickers from master')
            cmd.add_argument('--manual-universe', action='store_true', help='Use local CSV; do not fetch JPX')
        if name in ('download', 'all'):
            cmd.add_argument('--update', action='store_true')
            cmd.add_argument('--retry-failed', action='store_true')
            cmd.add_argument('--refresh-universe', action='store_true')
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    c = load_config(args.config.resolve())
    root = args.root.resolve()
    init_dirs(root)
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s', handlers=[logging.StreamHandler(), logging.FileHandler(root / 'results/logs/run.log', encoding='utf-8')])
    try:
        with FileLock(root / '.run.lock', timeout=0):
            if args.command == 'analyze':
                quality = analyze(root, c)
                print(quality)
                return 0
            download = args.command in ('download', 'all')
            u = load_universe(root, c, refresh=download, manual=args.manual_universe)
            if args.tickers:
                requested = {t.upper().removesuffix('.T') for t in args.tickers}
                unknown = requested - set(u.code)
                if unknown:
                    raise ValueError(f'Tickers absent from JPX domestic ordinary-stock master: {sorted(unknown)}')
                u = u[u.code.isin(requested)].reset_index(drop=True)
            if args.limit is not None:
                if args.limit < 1:
                    raise ValueError('--limit must be positive')
                u = u.head(args.limit)
            print(f'Selected universe: {len(u)} stocks')
            if download:
                status = Downloader(root, c).run(u, update=args.update, retry_failed=args.retry_failed)
                for kind in ('price', 'shares', 'benchmark'):
                    selected = [r for r in status if r['kind'] == kind]
                    failed = sum(r['status'] == 'failed' for r in selected)
                    print(f'{kind}: {len(selected) - failed}/{len(selected)} available, {failed} failures')
            if args.command in ('backtest', 'all'):
                trades = run_backtest(root, u, c)
                print(f'Trade rows: {len(trades)}; complete: {trades.trade_status.eq("complete").sum()}')
            if args.command == 'all':
                print(analyze(root, c))
            print(f'Outputs: {root / "results"}')
            return 0
    except (ValueError, RuntimeError, FileNotFoundError, Timeout) as e:
        logging.error('%s', e)
        return 1


if __name__ == '__main__':
    sys.exit(main())
