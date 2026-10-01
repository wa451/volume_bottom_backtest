from pathlib import Path
import shutil
import numpy as np
import pandas as pd
from .optimizer import aggregate_results, select_candidates, evaluate_candidates
from .visualization import generate_heatmaps
from .utils import read_json, fingerprint, atomic_json

LIMITATIONS = '''- **Survivorship Bias**: 現在上場している国内普通株のみ。過去の倒産・上場廃止銘柄は含まず、長期成績を良く見せる可能性がある。
- JPX は直近公表月末のスナップショット。市場区分・業種は現在マスターの属性で、過去時点の市場区分ではない。
- Yahoo の株式数日時は厳密な公表日時を保証しない。後方 as-of は未来日付を使わないが、完全な point-in-time データではない。
- 生株価は Yahoo の分割調整価格と取得時点までの Stock Splits から復元。分割情報の欠落・誤りや repair の誤補正が残る可能性がある。
- Adj Close による配当込みの近似リターン。配当課税、売買単位、値幅制限、流動性、約定不能は再現しない。
- Event Study なので同時保有・資金配分は仮定せず、CAGR / Portfolio Sharpe / Portfolio Max Drawdown は算出しない。
- 同一銘柄の重複保有期間や市場共通ショック、25条件と複数期間の多重比較がある。銘柄クラスタ Bootstrap でも全ての依存は解消しない。
- 結果は研究用途。サンプル不足のセルは候補から除外し、Test 成績でパラメータを選び直さない。
'''


def percent(n, d):
    return f'{n / d:.2%} ({n:,}/{d:,})' if d else '算出不能（分母0）'


def quality_report(root: Path, trades: pd.DataFrame, c: dict) -> dict:
    q = pd.read_csv(root / 'results/logs/backtest_ticker_quality.csv')
    # One signal may occur in 25 parameter combinations and four horizons.
    events = trades.drop_duplicates(['ticker', 'signal_date'])
    complete = trades[trades.trade_status.eq('complete')]
    source = read_json(root / 'data/universe/source.json')
    shares_count = 0
    for ticker in q.ticker:
        p = root / f'data/shares/{ticker}.parquet'
        if p.exists() and not pd.read_parquet(p).empty:
            shares_count += 1
    cap_count = int(events.market_cap.notna().sum())
    trade_cap_count = int(complete.market_cap.notna().sum())
    quality = {'universe_count': len(q), 'price_success_count': int(q.price_success.sum()),
               'price_failure_or_missing_count': int((~q.price_success).sum()), 'shares_success_count': shares_count,
               'unique_signal_count': len(events), 'market_cap_covered_signals': cap_count,
               'market_cap_signal_coverage': cap_count / len(events) if len(events) else None,
               'completed_trade_count': len(complete), 'market_cap_trade_coverage': trade_cap_count / len(complete) if len(complete) else None,
               'split_events': int(q.split_events.sum()), 'missing_cells': int(q.missing_cells.sum()),
               'missing_sessions': int(q.missing_sessions.sum()),
               'nontrading_zero_volume_rows': int(q.nontrading_zero_volume_rows.sum()),
               'repaired_rows': int(q.repaired_rows.sum()),
               'excluded_signal_parameter_pairs': int(q.excluded_signal_parameter_pairs.sum()),
               'boundary_purged': int(trades.trade_status.eq('boundary_purged').sum()),
               'incomplete': int(trades.trade_status.eq('incomplete').sum())}
    lines = ['# データ品質レポート', '', f'- 対象銘柄数（今回の選択範囲）: {len(q):,}',
             f'- JPX マスター全体: {source.get("total_domestic_ordinary_stocks", "手動CSV / 不明")}',
             f'- JPX 基準日: {source.get("as_of", "不明")}',
             f'- JPX 更新エラー: {source.get("last_refresh_error", "なし")}',
             f'- 価格取得成功率（有効ローカルキャッシュ）: {percent(quality["price_success_count"], len(q))}',
             f'- 価格取得失敗・未取得数: {quality["price_failure_or_missing_count"]:,}',
             f'- 株式数取得成功率（空でないキャッシュ）: {percent(shares_count, len(q))}',
             f'- Historical Market Cap 算出率（重複除去したシグナル）: {percent(cap_count, len(events))}',
             f'- Historical Market Cap 算出率（集計対象取引）: {percent(trade_cap_count, len(complete))}',
             f'- 分割イベント数（取得期間全体）: {quality["split_events"]:,}',
             f'- OHLC / Adj Close / Volume 欠損セル数: {quality["missing_cells"]:,}',
             f'- 東証営業日に価格バーがない日数: {quality["missing_sessions"]:,}（補間せず欠損）',
             f'- 元キャッシュに含まれる休場日の出来高0行: {quality["nontrading_zero_volume_rows"]:,}（指標と営業日数から除外）',
             f'- repair フラグが True の行数: {quality["repaired_rows"]:,}',
             f'- repair フラグ取得銘柄数: {int(q.repair_flag_available.sum()):,}（フラグなしは未修復の証明ではない）',
             f'- 分割調整問題で除外したシグナル・パラメータ組の数（cooldown 前）: {quality["excluded_signal_parameter_pairs"]:,}',
             f'- Train/Test 境界で除外した取引数: {quality["boundary_purged"]:,}',
             f'- 保有期間未成熟の取引数: {quality["incomplete"]:,}',
             f'- 使用可能な価格系列最終日: {q.last_bar.dropna().max() if "last_bar" in q else "なし"}',
             '', '## 欠損理由', '']
    if not events.empty:
        for reason, n in events[events.market_cap.isna()].market_cap_missing_reason.value_counts().items():
            lines.append(f'- {reason}: {n}')
    lines += ['', '株式数が欠損・古すぎる・分割で単位が不明な場合は推測値を使わず、全体評価にのみ残す。',
              '取得失敗ログ: `logs/failed_tickers.csv`。部分取得エラーも download_manifest.json に記録する。', '', '## 制約', '', LIMITATIONS]
    (root / 'results/data_quality_report.md').write_text('\n'.join(lines), encoding='utf-8')
    atomic_json(quality, root / 'results/data_quality.json')
    return quality


def table(frame, columns, limit=10):
    if frame.empty:
        return '最低件数を満たす Train 候補はありません。'
    def fmt(v):
        if isinstance(v, (float, np.floating)):
            return f'{v:.4f}' if np.isfinite(v) else str(v)
        return str(v)
    lines = ['| ' + ' | '.join(columns) + ' |', '| ' + ' | '.join(['---'] * len(columns)) + ' |']
    lines += ['| ' + ' | '.join(fmt(v) for v in values) + ' |' for values in frame[columns].head(limit).itertuples(index=False, name=None)]
    return '\n'.join(lines)


def analyze(root: Path, c: dict):
    folder = root / 'results'
    run = read_json(folder / 'run.json')
    if not run or run['config_fingerprint'] != fingerprint(c):
        raise ValueError('Config differs from the saved backtest. Run backtest again before analyze.')
    trades = pd.read_parquet(folder / 'trades.parquet')
    results = aggregate_results(trades, c)
    results.to_csv(folder / 'parameter_results.csv', index=False)
    results[results.market_segment.eq('ALL') & ~results.market_cap_group.eq('ALL')].to_csv(folder / 'market_cap_comparison.csv', index=False)
    results[~results.market_segment.eq('ALL')].to_csv(folder / 'market_segment_comparison.csv', index=False)
    candidates = select_candidates(results, c)
    candidates.to_csv(folder / 'top_candidates_train.csv', index=False)
    evaluated = evaluate_candidates(candidates, results)
    evaluated.to_csv(folder / 'candidate_test_results.csv', index=False)
    # Prevent charts from an earlier configuration appearing beside new results.
    charts = folder / 'heatmaps'
    if charts.exists():
        shutil.rmtree(charts)
    heatmaps = generate_heatmaps(results, root, c) if c.get('output', {}).get('heatmaps', True) else 0
    quality = quality_report(root, trades, c)
    all_candidates = candidates[candidates.market_cap_group.eq('ALL') & candidates.market_segment.eq('ALL')]
    lines = ['# 底値出来高急増戦略 — Event Study', '',
             f'対象: {run["universe_count"]:,} 銘柄。分析設定は `run.json` に保存。リターンは小数表記（0.10 = +10%）。',
             f'有効取引: {quality["completed_trade_count"]:,}。同じシグナルが複数条件・保有期間に含まれるため独立標本数ではない。',
             '訓練・検証期間をまたぐ取引と未成熟取引は平均成績から除外。候補は Train のみで順位付け。',
             '', '## Train Top candidates（ALL）', '',
             table(all_candidates, ['holding_period', 'candidate_rank', 'drawdown_threshold', 'volume_ratio_threshold',
                                    'num_trades', 'mean_return', 'median_return', 'profit_factor', 'ci95_lower', 'robustness_score'], 20),
             '', '全区分の候補は `top_candidates_train.csv`、固定候補の Test 評価は `candidate_test_results.csv`。',
             '平均リターンを主順位とし、隣接8セルのうち最低件数を満たすセル平均を robustness_score として確認する。',
             '95% CI は銘柄単位のクラスタ Bootstrap が初期値。単一銘柄しかないセルの CI は算出不能。',
             '', '## 出力', '', '- `trades.parquet` / `trades.csv`: 各イベント、取引状態、当時株式数、価格基準。',
             '- `parameter_results.csv`: 全体・時価総額別・市場別の全グリッド（0件のセルも保存）。',
             '- `market_cap_comparison.csv` / `market_segment_comparison.csv`: 区分別比較。',
             '- `data_quality_report.md`: 取得・欠損・除外・算出率。',
             f'- `heatmaps/train|test/<holding>d/`: {heatmaps}枚。空の区分は作図省略、* は最低件数未満。',
             '', '## 制約', '', LIMITATIONS]
    (folder / 'summary.md').write_text('\n'.join(lines), encoding='utf-8')
    return quality
