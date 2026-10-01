# 実装・実接続検証（2026-10-01 / 日本時間）

要件定義書に沿った Version 1 の CLI / Event Study を実装しました。既存 stock_app と demoTrade は変更していません。

## 実装済み

JPX普通株マスター、英字証券コード、yfinance日足・株式数・任意指数、Parquetキャッシュ、バッチと再試行、失敗種類ごとの再開、更新時の調整基準変更検出、分割・併合と出来高基準、過去のみの指標、25条件、翌日始値、4保有期間、Historical Shares後方as-of、時価総額6区分・市場3区分、Train/Test境界除外、Trainだけの候補選択、銘柄クラスタBootstrap、Robustness、CSV・ヒートマップ・品質レポート。

## 実接続の範囲と結果

- JPX取得: 成功。公式ページに2026年8月末として掲載された最新公表マスター。国内普通株 3,700銘柄。
- 試験対象: 130A / 4477 / 6758 / 7203 / 8306 の5銘柄。**全市場データは未取得・未検証です。**
- 価格取得: 5/5 = 100%。
- Historical Sharesキャッシュ: 5/5 = 100%。全過去日付に株式数があるという意味ではありません。
- 重複除去したシグナル: 272件。
- Historical Market Cap算出率（シグナル単位）: 189/272 = 69.49%。
- Historical Market Cap算出率（有効取引行）: 71.90%。
- 有効取引行: 3,004。25条件・4保有期間による重複を含み、独立取引数ではありません。
- Train/Test境界除外: 163行。未成熟: 313行。
- 分割: 3イベント。欠損営業日: 9、元データの休場日0出来高行: 69。
- ^N225: 取得成功。^TOPX: Yahooで取得失敗、failed_tickers.csvへ記録。Primaryは継続。
- 最低100件を満たすTrain候補なし。候補CSVは見出しだけで出力し、最高条件を推測・選出していません。

実データでもEntry > Signal、Exit > Entry、Shares日 <= Signal、TrainのExit <= 2021-12-31、未確定当日不使用、Entry/Exit同一価格基準の数値一致を確認しました。

`7203.T`の2021年5分割付近も確認し、Yahoo Volumeを二重補正せず、Raw CloseとRaw Volumeを当時の単位で復元しています。

## 検証コマンド

```bash
.venv/bin/python -m pytest -q
.venv/bin/python main.py download --tickers 7203 6758 8306 4477 130A
.venv/bin/python main.py download --tickers 7203 6758 8306 4477 130A --retry-failed
.venv/bin/python main.py backtest --tickers 7203 6758 8306 4477 130A
.venv/bin/python main.py analyze
```

自動テストは60件。未来データ不使用、株式数欠損・分割・Train漏洩、再開、実行設定の保存、オフラインCLIを含みます。実行結果はTEST_RESULTS.txtに保存します。

検証環境の依存バージョンは requirements.lock.txt に保存しました（Python 3.12用の記録）。他のPythonバージョンは requirements.txt から適合する依存を解決してください。

## 生成物と参照先

- README.md: インストール・全銘柄実行・設定・時価総額比較方法・データの価格基準。
- results/summary.md: 少数試験の集計概要。
- results/data_quality_report.md / data_quality.json: 取得率・算出率・欠損理由。
- results/parameter_results.csv / market_cap_comparison.csv / market_segment_comparison.csv。
- results/trades.parquet / trades.csv、top_candidates_train.csv、candidate_test_results.csv。
- results/heatmaps/train|test/<holding>d/*.png。

## 制約

現在上場企業のみのSurvivorship Bias、現在市場属性、Yahoo株式数日時の公表時点非保証、欠損・事後修正・修復誤差、約定可能性・売買単位・配当税等の未再現、取引依存と多重比較が残ります。Portfolioの資金シミュレーションは第2段階として未実装です。

詳細は README.md とデータ品質レポートに明記しました。この少数試験から戦略の優位性は判断できません。
