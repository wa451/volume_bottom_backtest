# Kenmo型戦略追加

## 現状と境界

- Python 3.10+ / pandas共通Core、FastAPI、DBキュー・独立Worker、Next.js / React。
- JPX普通株マスター、yfinance、Parquet差分キャッシュ、調整価格とHistorical Shares。
- 既存Bottom + VolumeはEvent Study。25条件×4保有期間をTrain/Testで集計し、最低件数と銘柄クラスタBootstrapで評価。
- APIは受付と参照のみ。重い処理はWorker、共有ディスクはロック、結果と設定は試行ごとに不変。
- 既存HTTP取得は制限付き並列。回帰テストと実API/Worker/Playwrightあり。

## 実装方針

1. `src/strategies/` に共通インターフェースと4戦略。Bottomの既存判定を適合させ、既存の単独実行と保存結果を維持。
2. 決算日を差分更新し、財務スナップショットは取得日時以降のみ使用。会計期間末を公表日として使わない。現在ROE/PERを過去へ代入しない。
3. `src/execution.py` と `src/portfolio.py` で売却、資金配分・同時保有数・日次時価評価を定義。資産曲線・CAGR等はこの資金モデルから算出。
4. `src/strategy_runner.py` でパラメータ上限、少数スレッドによる銘柄処理、共有価格の再利用、Train/Testの独立検証、区分別集計、CSV/Parquet保存。
5. 新形式の結果は別Artifactとして保存しDB既存スキーマを変更しない。旧結果画面・旧APIを維持し、新結果用参照API/UIを追加。
6. 戦略を複数指定したジョブは同じ期間・銘柄集合・費用・資金モデルで比較。Trainのみで候補を選びTestは固定評価。

## 主要ファイル

新規: `src/strategies/*`, `src/strategy_data.py`, `src/execution.py`, `src/portfolio.py`, `src/strategy_runner.py`, `backend/app/strategy_results.py`, `frontend/components/strategy-settings.tsx`, `frontend/components/strategy-results.tsx`, 回帰テスト、`docs/KENMO.md`。

変更: 共通CoreのBottom判定接続、Downloader、CLI、APIスキーマ・ルート・Worker、Backup、Frontend戦略選択・取得項目・型・履歴、README/AGENTS。

## 財務データに関する制約

yfinance 1.7.0を調査。財務表は`asOfDate`で並び、取得当時の発表時刻・訂正前の履歴を提供するPITデータセットではない。公式実装の取得範囲コメントは年次約4年・四半期約5期。過去の成長率を会計期間末へ遡及適用しない。保存するスナップショットの`available_at`は取得日時。以後のシグナルのみに後方as-ofで適用し、古い・分割後の単位不明データは欠損にする。

Earningsの時刻不明・引け後発表は翌営業日の反応を確認してから、その次の始値以降でEntry。1営業日後指定は場中発表でその日の反応を確認できた場合のみ有効。履歴のない銘柄はゼロ件・品質警告として継続。上場日を初回キャッシュ日から推測しない。

本人の投資成果・投資法を完全再現したとは表示しない。Survivorship Bias、Yahooデータ欠損、無料API制約、約定近似を明記。

## 検証

高値/出来高のshift、財務・決算時刻の未来不使用、翌日Entry、損切り・利確同時到達と窓開け、Trailing、MA、費用、資金不足・同時保有、曲線指標、探索上限、Train/Test、旧結果互換、差分キャッシュ、少数銘柄実データ/合成データ、APIWorker、Frontend、Playwright。
