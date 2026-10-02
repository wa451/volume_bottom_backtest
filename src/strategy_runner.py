"""Cached-data strategy comparison, executed only in CLI/independent Worker."""
from concurrent.futures import ThreadPoolExecutor
from itertools import product
import json
import logging
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from .backtest import prepare_features
from .data_loader import exchange_sessions
from .benchmark import load_benchmarks
from .signals import apply_cooldown
from .strategy_data import load_strategy_data
from .strategy_config import parameter_grid, PortfolioSettings, TradingCosts
from .strategies import REGISTRY
from .portfolio import simulate
from .utils import atomic_parquet, atomic_json, fingerprint, last_completed_date

log = logging.getLogger(__name__)
SCOPES = ['strategy_id', 'parameter_id', 'period_type', 'market_cap_group', 'market_segment']
CURVE_SCHEMA = pa.schema([(x, pa.string()) for x in SCOPES] + [('date', pa.timestamp('ns')), ('equity', pa.float64()), ('cash', pa.float64()), ('positions', pa.int64()), ('benchmark', pa.float64()), ('drawdown', pa.float64())])
TRADE_STRINGS = SCOPES + ['code', 'ticker', 'company_name', 'entry_reason', 'exit_reason', 'trade_status', 'exit_timing', 'signal_cap_group', 'signal_market_segment']
TRADE_DATES = ['signal_date', 'entry_date', 'exit_date']
TRADE_NUMBERS = ['entry_price', 'exit_price', 'return', 'pnl', 'unrealized_pnl', 'holding_days', 'invested', 'quantity_adjusted', 'signal_market_cap']
TRADE_SCHEMA = pa.schema([(x, pa.string()) for x in TRADE_STRINGS] + [(x, pa.timestamp('ns')) for x in TRADE_DATES] + [(x, pa.float64()) for x in TRADE_NUMBERS])


def safe_csv(frame, path):
    copy = frame.copy()
    for name in copy.select_dtypes(include=['object', 'string']).columns:
        copy[name] = copy[name].map(lambda x: "'" + x if isinstance(x, str) and x.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else x)
    copy.to_csv(path, index=False)


def _ticker(root, info, c, grids, periods):
    df = prepare_features(root, info['ticker'], c)
    volume = df['SplitAdjustedVolume']
    df['strategy_volume_ratio'] = volume / volume.shift(1).rolling(20, min_periods=20).mean().where(lambda x: x > 0)
    data = load_strategy_data(root, info['ticker'], df)
    quality = {'ticker': info['ticker'], 'financial_available_rows': int((data['fundamentals'].notna().any(axis=1) & (df.index >= pd.Timestamp(c['data']['start_date'])) & (df.index <= min(pd.Timestamp(c['data']['end_date']) if c['data']['end_date'] else last_completed_date(), last_completed_date()))).sum()), 'earnings_releases': len(data['earnings']), 'listing_date_available': False, 'missing_sessions': int(df.missing_session.sum()), 'errors': '; '.join(data['errors'])}
    candidates = {}
    for grid in grids:
        strategy, p = REGISTRY[grid['strategy_id']], grid['parameters']
        mask = strategy.entry_signals(df, p, data)
        valid = df['Adj Close'].gt(0) & df.Volume.gt(0) & ~df.split_excluded
        groups = c.get('analysis', {}).get('market_cap_groups', ['ALL'])
        if 'ALL' not in groups:
            valid &= df.market_cap_group.isin(groups)
        for period, (start, end) in periods.items():
            selected = mask & valid & (df.index >= start) & (df.index <= end)
            truncated = df.loc[:end]
            trades = []
            for pos in apply_cooldown(selected, c['strategy']['signal_cooldown_days']):
                entry = pos + 1
                if entry >= len(truncated):
                    continue
                exit_ = strategy.exit_trade(truncated, entry, p)
                if exit_['trade_status'] == 'invalid_entry':
                    continue
                signal = df.iloc[pos]
                trades.append({**info, **grid, **exit_, 'period_type': period, 'signal_date': df.index[pos], 'entry_date': df.index[entry], 'entry_price': float(df['Adj Open'].iloc[entry]),
                               'entry_reason': strategy.reasons(df, pos, p, data), 'signal_cap_group': str(signal.market_cap_group), 'signal_market_segment': info['market_segment'], 'signal_market_cap': float(signal.market_cap)})
            candidates[grid['parameter_id'], period] = trades
    return df[['Adj Close']].astype(float), candidates, quality


def run_strategies(root, universe, c, progress=None):
    grids = parameter_grid(c)
    settings = PortfolioSettings(**c.get('portfolio', {})).model_dump()
    costs = TradingCosts(**c['cost']).model_dump()
    end = min(pd.Timestamp(c['data']['end_date']) if c['data']['end_date'] else last_completed_date(), last_completed_date())
    start = pd.Timestamp(c['data']['start_date'])
    periods = {name: (max(start, pd.Timestamp(c[name]['start'])), min(end, pd.Timestamp(c[name]['end']) if c[name]['end'] else end)) for name in ('train', 'test')}
    periods['full'] = (start, end)
    sessions = {name: exchange_sessions(str(a.date()), str(b.date())) if a <= b else pd.DatetimeIndex([]) for name, (a, b) in periods.items()}
    if any(len(s) == 0 for s in sessions.values()):
        raise ValueError('Train / Testに完了済み営業日が必要です')
    prices, candidates, quality = {}, {}, []
    infos = universe.to_dict('records')
    # At most four ticker tasks in flight. Each writes only its own feature cache;
    # Yahoo is never called here and the caller holds the shared cache lock.
    workers = min(4, max(1, c['download'].get('threads', 4)))
    candidate_count = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for offset in range(0, len(infos), workers):
            batch = [(info, pool.submit(_ticker, root, info, c, grids, periods)) for info in infos[offset:offset + workers]]
            for info, future in batch:
                if progress:
                    progress(len(quality), len(infos) + len(grids), info['ticker'] + ' / 戦略判定')
                try:
                    quote, trades, q = future.result()
                    prices[info['ticker']] = quote
                    quality.append(q)
                    for key, rows in trades.items():
                        candidates.setdefault(key, []).extend(rows)
                        candidate_count += len(rows)
                    if candidate_count > 2_000_000:
                        raise MemoryError('候補取引が200万件を超えました。期間・銘柄・パラメータを絞ってください')
                except (ValueError, KeyError, OSError, TypeError) as exc:
                    quality.append({'ticker': info['ticker'], 'errors': str(exc)})
                    log.warning('Strategy preprocessing failed for %s: %s', info['ticker'], exc)
    if not prices:
        raise ValueError('利用可能な価格キャッシュがありません。データ更新を先に実行してください')
    benchmarks = load_benchmarks(root, c)
    benchmark = benchmarks.get(settings['benchmark'])
    dest = root / 'results'
    dest.mkdir(parents=True, exist_ok=True)
    caps = ['ALL'] + [b['name'] for b in c['market_cap_bins'] if 'ALL' in c.get('analysis', {}).get('market_cap_groups', ['ALL']) or b['name'] in c['analysis']['market_cap_groups']]
    markets = ['ALL'] + c['universe']['markets']
    rows = []
    total_trades, curve_rows = 0, 0
    curve_path, trade_path = dest / 'strategy_curves.parquet', dest / 'trades.parquet'
    curve_tmp, trade_tmp = curve_path.with_suffix('.tmp.parquet'), trade_path.with_suffix('.tmp.parquet')
    with pq.ParquetWriter(curve_tmp, CURVE_SCHEMA, compression='zstd') as cw, pq.ParquetWriter(trade_tmp, TRADE_SCHEMA, compression='zstd') as tw:
        for number, grid in enumerate(grids):
            if progress:
                progress(len(infos) + number, len(infos) + len(grids), REGISTRY[grid['strategy_id']].name + ' / 資金配分・集計')
            for period, (cap, market) in product(periods, product(caps, markets)):
                scope = {**{k: grid[k] for k in ('strategy_id', 'parameter_id')}, 'period_type': period, 'market_cap_group': cap, 'market_segment': market}
                entries = [t for t in candidates.get((grid['parameter_id'], period), []) if (cap == 'ALL' or t['signal_cap_group'] == cap) and (market == 'ALL' or t['signal_market_segment'] == market)]
                metrics, curve, trades = simulate(entries, prices, sessions[period], settings, costs, benchmark)
                row = {**scope, **metrics, 'parameters': json.dumps(grid['parameters'], ensure_ascii=False, sort_keys=True), 'num_signals': len(entries), 'insufficient_sample': metrics['num_trades'] < c['validation']['minimum_trades']}
                rows.append(row)
                # Flat scopes need no enormous duplicated daily artifact. The API
                # exposes their metrics; ALL has a chart even without signals.
                if entries or (cap == 'ALL' and market == 'ALL'):
                    curve = curve.assign(**scope)
                    curve_rows += len(curve)
                    if curve_rows > 15_000_000:
                        raise ValueError('資産曲線が1500万行を超えました。探索範囲を絞ってください')
                    cw.write_table(pa.Table.from_pandas(curve, schema=CURVE_SCHEMA, preserve_index=False))
                if trades:
                    export = pd.DataFrame(trades).assign(**scope).reindex(columns=TRADE_SCHEMA.names)
                    for key in TRADE_DATES:
                        export[key] = pd.to_datetime(export[key])
                    tw.write_table(pa.Table.from_pandas(export, schema=TRADE_SCHEMA, preserve_index=False))
                    total_trades += len(export)
    curve_tmp.replace(curve_path)
    trade_tmp.replace(trade_path)
    results = pd.DataFrame(rows)
    # Train-only candidate IDs, fixed when looking at Test. A favorable Test
    # result can never promote a parameter into this set.
    selected = set()
    eligible = results[(results.period_type == 'train') & ~results.insufficient_sample & results.metrics_valid & results.cagr.notna()]
    for _, scope in eligible.groupby(['strategy_id', 'market_cap_group', 'market_segment']):
        selected.update(scope.sort_values(['cagr', 'max_drawdown', 'parameter_id'], ascending=[False, False, True]).head(c['validation'].get('top_candidates', 5)).apply(lambda r: (r.strategy_id, r.parameter_id, r.market_cap_group, r.market_segment), axis=1))
    results['train_selected'] = results.apply(lambda r: (r.strategy_id, r.parameter_id, r.market_cap_group, r.market_segment) in selected, axis=1)
    atomic_parquet(results, dest / 'strategy_results.parquet')
    safe_csv(results, dest / 'strategy_results.csv')
    quality_frame = pd.DataFrame(quality)
    safe_csv(quality_frame, dest / 'strategy_quality.csv')
    summary = {'analysis_mode': 'portfolio', 'parameter_combinations': len(grids), 'minimum_trades': c['validation']['minimum_trades'], 'portfolio': settings, 'costs': costs,
               'quality': {'stock_count': len(universe), 'price_success_count': len(prices), 'financial_observed_rows': int(quality_frame.get('financial_available_rows', pd.Series(dtype=float)).fillna(0).sum()), 'earnings_releases': int(quality_frame.get('earnings_releases', pd.Series(dtype=float)).fillna(0).sum())},
               'trade_artifact_rows': total_trades, 'benchmark_available': benchmark is not None, 'benchmark_ticker': settings['benchmark'],
               'warnings': ['kenmo氏本人の投資法・成果を完全再現するものではありません。', '財務データは取得完了時点以後だけ有効。過去の公表時点・改訂前値は再現できません。', '財務の成長率は取得時点の年次YoY。個別四半期決算との対応付けは保証しません。', 'Yahoo決算カレンダーは完全な公表履歴ではなく、日時の正確性・収録範囲に制約があります。', '現在取得可能な銘柄を利用しているため、生存者バイアスが存在する可能性があります。', '資金配分は均等予算・端株の理論モデル。100株単位、流動性・値幅制限・配当入金日は再現しません。', 'FULLは期間全体の独立した参考検証。Train/Testは別資金で開始し、境界では未決済のまま評価。', '保有中の価格欠損は曲線を参考値とし、CAGR等の指標を無効にします。'],
               'full_note': 'Trainのみで候補選択。Testは同一設定の確認。期間末未決済は評価損益に含むが勝率・PFの取引数には含めません。'}
    if quality_frame.get('errors', pd.Series(dtype=str)).fillna('').ne('').any():
        summary['warnings'].append('一部銘柄のキャッシュ・財務が利用できません。データ品質CSVで銘柄別の理由を確認してください。')
    if summary['quality']['financial_observed_rows'] == 0 and any(g['parameters'].get('mode') == 'fundamentals' for g in grids):
        summary['warnings'].append('この期間に利用可能な財務観測がありません。財務条件ONの設定は無取引です。')
    if any(g['strategy_id'] == 'kenmo_earnings' for g in grids) and summary['quality']['earnings_releases'] == 0:
        summary['warnings'].append('決算日の履歴キャッシュがありません。決算モメンタムは無取引です。市場データ画面で決算日取得を選択してください。')
    if benchmark is None:
        summary['warnings'].append('選択したベンチマークのキャッシュがありません。グラフを捏造せず欠損として表示します。')
    atomic_json({'config': c, 'config_fingerprint': fingerprint(c), 'summary': summary, 'universe_codes': universe.code.tolist()}, dest / 'run.json')
    atomic_json(summary, dest / 'strategy_summary.json')
    (dest / 'summary.md').write_text('# 戦略比較\n\n' + '\n\n'.join(summary['warnings']) + '\n\n' + summary['full_note'], encoding='utf-8')
    if progress:
        progress(len(infos) + len(grids), len(infos) + len(grids), '戦略結果保存完了')
    return summary
