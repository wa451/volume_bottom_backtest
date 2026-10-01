# 日本株・底値出来高急増戦略バックテスト

現在の東証国内普通株（Prime / Standard / Growth）を対象に、過去252営業日高値からの下落と、過去20営業日平均に対する出来高増加を検証する Python CLI です。RSI・業績・財務指標等を売買条件に加えません。

初期値は下落率 20/30/40/50/60%、出来高倍率 1.5/2/3/4/5 倍の **25条件**、保有期間 20/60/120/250 営業日。Primary は各シグナルの Forward Return を比較する **Event Study** です。

**Survivorship Bias が存在します。** 現在の上場企業だけを分析するため、過去の倒産・上場廃止企業が含まれず、とくに長期成績を実際より良く見せる可能性があります。戦略に優位性があるという結論はツール完成とは別に、十分なデータと未使用期間で確認する必要があります。

## セットアップ

Python 3.10 以上。今回の動作確認環境は Python 3.12、macOS です。

```bash
cd '/Users/wataru/Desktop/株/volume_bottom_backtest'
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

作成済み `.venv` を使う場合は `source .venv/bin/activate` だけで開始できます。`uv` も利用可能です。

```bash
uv pip install --python .venv/bin/python -r requirements.txt
```

## 実行

```bash
# JPXマスター更新 + 株価・株式数・任意指数を取得
python main.py download

# キャッシュ済み価格の末尾を取得。新しい配当・分割があれば全履歴を再取得
python main.py download --update

# 保存された失敗銘柄・失敗種類だけ再取得（現在の選択範囲内）
python main.py download --retry-failed

# ネットワークアクセスなしでローカルデータから25条件を検証
python main.py backtest

# CSV、候補、ヒートマップ、品質レポート
python main.py analyze

# 取得・バックテスト・分析を一括実行
python main.py all
```

`download` は既存価格キャッシュをスキップします。新しい日付は `--update` を使ってください。途中終了しても、成功した各銘柄は直ちに Parquet と取得マニフェストへ保存するため、同じコマンドで再開できます。全銘柄取得は無料APIの制約により時間がかかります。失敗があっても残りの銘柄を処理し、`results/logs/failed_tickers.csv` に保存します。

少数で確認する場合：

```bash
python main.py all --tickers 7203 6758 8306 4477 130A
python main.py download --limit 10
python main.py backtest --limit 10
```

`--tickers` はJPXマスターに存在する普通株のみ受け付けます。市場分類が過去時点の分類であるとは仮定しません。`--limit` はコード順の先頭から選択する動作確認用です。少数結果を全市場成績として扱わないでください。

実行ごとに `results/` の集計を置き換えます。検証ごとに保存先を分けるには：

```bash
python main.py --root ./runs/experiment1 --config config.yaml all --limit 10
python main.py --root ./runs/experiment1 --config config.yaml analyze
```

設定オプションはサブコマンドの後にも指定できます。`analyze` は `results/run.json` と現在の設定の一致を確認します。設定変更後は `backtest` から実行してください。並行実行によるキャッシュ破損を防ぐため、同じ保存先への処理をロックします。

## データソースとマスター

- 銘柄一覧: [JPX 東証上場銘柄一覧](https://www.jpx.co.jp/markets/statistics-equities/misc/01.html)。最新**公表月末**一覧です。月次公表のため当日現在の新規上場・変更とずれることがあります。
- OHLCV、配当、分割、株式数、指数: [yfinance](https://github.com/ranaroussi/yfinance)。有料APIは使いません。
- 営業日: [exchange_calendars](https://github.com/gerrymanoim/exchange_calendars) の XTKS カレンダー。

JPX のリンクをページから探索し、実ファイルの形式で xls / xlsx を判別します。Prime / Standard / Growth の内国株式カテゴリと普通株の4文字コードを使用し、5文字の優先株・種類株、ETF、ETN、REIT、インフラ、外国株、PRO等を除外します。原本・公表基準日・取得日も保存します。

手動配置は `data/universe/universe.csv` に UTF-8 CSV を置きます：

```csv
code,company_name,market_segment,sector
7203,トヨタ自動車,Prime,輸送用機器
130A,Veritas In Silico,Growth,医薬品
```

```bash
python main.py download --manual-universe
python main.py all --manual-universe
```

手動 CSV は利用者が国内普通株に限定してください。自動更新失敗時には既存CSVを使い、更新失敗をログと品質レポートに表示します。既存CSVもない場合は配置先を案内して終了します。

## キャッシュ・更新

- `data/market/<ticker>.parquet`: Yahooから返された列（Open / High / Low / Close / Adj Close / Volume / Dividends / Stock Splits / Repaired?等）。
- `data/shares/<ticker>.parquet`: 日時付き Historical Shares。取得可能範囲の欠損はそのまま残します。
- `data/benchmark/<ticker>.parquet`: 取得できた指数。
- `data/features/<ticker>.parquet`: 調整OHLC・出来高・高値・下落率・倍率・当時時価総額を銘柄ごとに一度計算。入力ファイルと設定の変更で無効化します。
- `data/download_manifest.json`: 検査済み範囲・最終日・価格基準・部分取得エラー。

分析開始前に初期値550暦日の余裕を設けます。上場後252営業日未満では高値を計算できず、その銘柄はシグナルを出しません。

**分析終了日と取得終了日は異なります。** Yahooは過去の日付を要求しても取得時点の分割調整単位で価格を返すため、当時価格を復元するのに必要な分割履歴を取得時点まで保持します。`data.end_date` は分析対象の上限（当日を含む）です。その後の価格リターンを終了日以前の結果に使用しません。東京時間16時より前は当日の日足を確定済みとして使いません。

更新では14暦日重ねて取得し、重複部分の価格基準変更や新しい配当・分割を検出した場合は全履歴を再取得します。これにより古い調整単位と新しい単位を継ぎ合わせません。遠い過去の修正を全て検知できるとは限りません。完全再取得が必要なら該当価格Parquetを削除して `download` を実行します。

バッチ内の成功銘柄を保存し、未取得銘柄だけ再試行します。初期値50銘柄、最大5回、2秒からの指数バックオフ、yfinance側4スレッドです。株式数はAPIの長期期間制約を考慮して2年ごとに取得します。空の株式数結果もキャッシュし、現在の時価総額から代替しません。

## 価格・出来高・分割の基準

`auto_adjust=False` は「分割前の当時価格をそのまま返す」という意味ではありません。Yahooの Open / Close / Volume は通常、分割調整単位です。これに追加でVolumeを分割倍すると二重補正になります。

初期設定は `price_basis: yahoo_split_adjusted` / `volume_basis: yahoo_split_adjusted`。Stock Splitsから各日に**厳密に後続する**分割比率の累積積 F を求めます。

```text
Raw OHLC = Yahoo OHLC × F
Raw Volume = Yahoo Volume / F
adjustment_ratio = Adj Close / Raw Close
Adj Open/High/Low = Raw Open/High/Low × adjustment_ratio
SplitAdjustedVolume = Raw Volume × F   # Yahoo Volume と一致
```

Raw列は当時の株式単位を復元したものです。元のYahoo列は変更しません。独自に配置した実際の生OHLCVに限り、`price_basis: raw` / `volume_basis: raw` を選べます。yfinance取得では初期設定を使用してください。

分割情報が不明なら生価格・時価総額を欠損にし、Primaryシグナルを除外します。分割日に未補正と疑われる価格断絶が残る場合や出来高補正を無効にした場合も、発生日から少なくとも20営業日（出来高平均窓以上）を除外します。未来の分割発生日を使った事前除外はしません。補正不能数を品質レポートへ記録します。`repair=True` を使いますが、[yfinance公式のrepair説明](https://github.com/ranaroussi/yfinance/wiki/Price-repair)にある通り、修復フラグが付かない調整も存在し、完全な正確性は保証されません。

## シグナル・売買・漏洩防止

```text
rolling_high = Adj High.shift(1).rolling(252).max()
drawdown = Adj Close / rolling_high - 1
average_volume = SplitAdjustedVolume.shift(1).rolling(20).mean()
volume_ratio = SplitAdjustedVolume / average_volume
signal = drawdown <= -threshold AND volume_ratio >= threshold
```

- 当日高値・当日出来高は過去窓に含めません。ウォームアップ不足・欠損は欠損のまま扱います。
- 各銘柄・パラメータ条件ごとに、シグナル後20営業日（t+1〜t+20）の新規シグナルを抑止します。
- 翌東証営業日の始値でEntry。h日保有のExitは **Entryのh営業日後の終値**（entry_index + h）。Entry日を第1日として数える方法とは1営業日違います。
- Yahooの休場日の出来高0行を営業日数から除外します。欠損営業日は補間せずに挿入し、翌日の始値が欠けても次の観測日にEntryをずらしません。
- `entry_price` は当時Raw Openに買いコスト・スリッページを含めた値。
- `exit_price` は調整系列の配当込み近似リターンを**Entry日の生価格単位**へ戻し、売りコストを含めた値。実際のExit当日価格は `raw_exit_price`、比較用の調整価格は `adjusted_exit_price` に別保存します。
- `return = exit_price / entry_price - 1`。`gross_return` はコスト適用前。分割前Entryと分割後Exitの異なる株式単位を割り算しません。
- 末尾の未成熟取引は `incomplete`、不正な約定価格は `invalid_price` として保存し、リターンをNaNにします。
- Trainはシグナル・Entry・Exitが全て訓練期間内の場合のみ採用します。境界をまたぐ取引は `boundary_purged`。Test期間の値がTrain候補選択に入らないよう関数を分離しています。

## Historical Market Cap

Yahooが付けた観測日がシグナル日以前である最新株式数だけを後方as-of結合します。

```text
market_cap = Raw Close × historical_shares
```

未来日付の株式数、現在時価総額への代替、欠損への推測値は使いません。初期設定では370暦日より古い株式数や、株式数観測後に分割が発生して単位が不明になったものも欠損にします。同日で異なる株式数が複数ある日は観測を採用しません。

品質は `historical_exact`（同じ観測日）、`historical_asof`（過去観測）、`missing` として保存します。exactという名前は真の公表時点の完全性を意味しません。**Yahooの観測日は実際に市場へ公表された日時を保証しないため、完全なpoint-in-time株式数ではない**という制約があります。

時価総額が欠損のシグナルはALL・市場別には残し、時価総額別から除外します。`market_cap_missing_reason` に `no_prior_shares` / `stale_shares` / `shares_before_split` / `invalid_raw_close` を記録します。

初期区分は micro（100億円未満）、small（100〜500億円）、small_mid（500〜1,000億円）、mid（1,000〜5,000億円）、large（5,000億〜1兆円）、mega（1兆円以上）。境界値は下限を含み上限を含みません。`market_cap_bins` で変更できます。

## 結果の確認

最初に `results/summary.md` と `results/data_quality_report.md` を読んでください。

| ファイル | 内容 |
| --- | --- |
| `trades.parquet` / `trades.csv` | シグナル・各保有期間の個別データと状態 |
| `parameter_results.csv` | Train/Test × ALL・規模6区分・市場3区分 × 25条件 × 4期間。0件セルも保存 |
| `market_cap_comparison.csv` | 時価総額6区分のみの比較 |
| `market_segment_comparison.csv` | 市場3区分のみの比較 |
| `top_candidates_train.csv` | 最低件数を満たすTrain候補を複数保存 |
| `candidate_test_results.csv` | Train候補に限定したTest評価。Testを見て選び直さない |
| `data_quality_report.md` / `.json` | 取得率・当時時価総額算出率・欠損・分割・除外数 |
| `summary.md` | ALL候補・出力説明・制約 |
| `run.json` | 実行設定、対象コード、実行日時 |
| `logs/failed_tickers.csv` | 失敗したtickerと取得種類・理由 |
| `logs/backtest_ticker_quality.csv` | 銘柄別の分析可能性、欠損、修復等 |
| `heatmaps/train|test/60d/` 等 | パラメータの成績分布 |

時価総額別に見る例：

```python
import pandas as pd
r = pd.read_csv('results/market_cap_comparison.csv')
print(r.query("period_type == 'test' and holding_period == 60")
       [['market_cap_group', 'drawdown_threshold', 'volume_ratio_threshold',
         'num_trades', 'mean_return', 'median_return', 'profit_factor', 'insufficient_sample']])
```

ヒートマップの例は `results/heatmaps/train/60d/micro_mean_return.png` / `all_mean_return.png` / `market_prime_mean_return.png`。区分間で同じ色スケールを使います。* は最低件数未満、空の区分は作図を省略しますがCSVには残します。

リターン・勝率・CIはCSVで小数表記（0.10は10%）。件数、平均・中央値、平均利益・損失、最大利益・損失、Profit Factor、Expectancy、標準偏差、25/75パーセンタイル、95% CIを出します。損失が0で利益があるProfit Factorは `inf` です。

CIは初期値で**銘柄クラスタ単位のBootstrap 2,000回**。乱数seedを固定し、1銘柄しかないセルのCIはNaNとします。`bootstrap_unit: trade` に変更すると単純な取引単位Bootstrapになりますが、取引間依存を無視するため注意が必要です。

Trainの平均リターンを主順位、中央値・Profit Factor・CI下限・Robustnessを副順位とし、区分・保有期間ごとに上位5候補を保存します。Robustnessは隣接8セル（上下・左右・斜め）のうち最低件数を満たすセルの平均リターンで、対象セル自身を含みません。有効隣接セル数も保存します。最低件数100未満は `insufficient_sample=true` として候補から除外します。

## 既知の制約

- 現在上場銘柄のSurvivorship Bias、市場・業種の現在属性による分類が残ります。
- Yahoo APIの欠損・レート制限・誤り・修復の誤補正、過去株式数の限定的なカバレッジがあります。
- 分割履歴が欠けると当時価格を完全には復元できません。出来高基準の異常を全て自動識別できるとは限りません。
- 株式数の観測日は厳密な公表日を保証しません。過去データの事後修正も含まれ得ます。
- 同一銘柄内の保有期間重複、市場全体の相関、多重パラメータ比較が残り、Bootstrap CIだけで戦略の優位性を確定できません。
- 当日始値で約定できると仮定します。値幅制限、売買単位、出来高制約、配当課税等は扱いません。
- 指数は `^TOPX`→`^N225` の順で利用可能なものを使用し、正確なEntry/Exit日が両方ある場合だけ比較します。指数取得失敗でPrimaryは停止しません。
- Portfolio Backtestは第2段階の拡張対象で、V1には含めません。資金曲線・CAGR・Sharpe等は出しません。

## テスト

```bash
python -m pytest -q
```

コード変換、商品除外、調整OHLC、分割・併合、出来高の二重補正防止、過去窓、未来データ不使用、シグナル・Cooldown、翌日始値、保有期間、価格基準、コスト、株式数as-of、欠損と規模境界、Train境界除外、Test情報不使用、PF・Expectancy・Bootstrap・Robustness、バッチ途中失敗・再開・調整基準更新、ヒートマップを検証します。外部APIアクセス不要です。

実銘柄の少数試験の取得率・算出率は `VERIFICATION.md` と生成レポートに記録します。全市場のバックテスト成績と区別してください。
