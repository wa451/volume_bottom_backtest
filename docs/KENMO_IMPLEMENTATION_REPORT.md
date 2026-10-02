# Kenmo型戦略追加・実装報告（2026-10-02）

## 1. 変更したファイル

- `AGENTS.md`
- `README.md`
- `backend/app/main.py`
- `backend/app/market.py`
- `backend/app/schemas.py`
- `backend/worker/main.py`
- `frontend/app/backtest/new/page.tsx`
- `frontend/app/data/page.tsx`
- `frontend/app/globals.css`
- `frontend/app/layout.tsx`
- `frontend/components/common.tsx`
- `frontend/components/job.tsx`
- `frontend/lib/types.ts`
- `frontend/tests/e2e/market-cap.spec.ts`
- `frontend/tests/e2e/multi-cap.spec.ts`
- `main.py`
- `requirements.txt`
- `src/backtest.py`
- `src/downloader.py`
- `tests/test_web.py`

## 2. 新しく追加したファイル

- `KENMO_IMPLEMENTATION_PLAN.md`
- `backend/app/strategy_results.py`
- `config.kenmo.yaml`
- `docs/KENMO.md`
- `docs/KENMO_IMPLEMENTATION_REPORT.md`
- `frontend/components/strategy-results.tsx`
- `frontend/components/strategy-settings.tsx`
- `frontend/lib/strategy.ts`
- `frontend/tests/e2e/kenmo.spec.ts`
- `frontend/tests/strategy.test.ts`
- `src/execution.py`
- `src/portfolio.py`
- `src/strategies/__init__.py`
- `src/strategies/base.py`
- `src/strategies/bottom_volume.py`
- `src/strategies/kenmo_breakout.py`
- `src/strategies/kenmo_earnings.py`
- `src/strategies/kenmo_growth.py`
- `src/strategy_config.py`
- `src/strategy_data.py`
- `src/strategy_runner.py`
- `tests/test_kenmo.py`

## 3. 各戦略の条件

Breakoutは当日を除く高値更新・20日出来高倍率、Earningsは公表済み決算への価格／出来高反応、Growthは当時時価総額と成長条件。価格版／財務版を分け、Growth価格版は50日MAの代理条件。財務フィルターは売上・EPS/利益・ROE・PERを個別ON/OFF。既存Bottomは共通契約へ接続し、単独Event Studyを維持。本人の投資法・成果の完全再現とは表示していません。

## 4. UIで追加した項目

4戦略の複数選択、価格／財務版、関連パラメータだけの表示、ON/OFF、折りたたみ売却・費用・資金設定、256組み合わせガード。Train候補の横並び比較、CAGR/Sharpe/PF/最大DD/Expectancyソート、資産・DD・指数曲線、個別取引理由、CSV。現在区分と金額帯のガイドを再利用。市場データ更新へ決算・財務オプション、キャッシュ件数／エラーを追加。

## 5. 売買ルール

翌営業日調整始値Entry、終値でのMA判断と保有期限は次の始値Exit。Stop・利確は日中判定、両方到達はStop優先、窓開けは不利な始値を反映。Trailingは前日までの高値。最大保有数・前日資産に対する均等予算・現金制約・費用・スリッページを定義。期間末は未決済評価で架空売却を作らない。保有OHLC欠損は未解決・関連資産指標を無効化。Bottom比較は旧N営業日後終値Exitを維持。

## 6. ルックアヘッドへの対応

指標はprior-only、財務は取得完了時刻以前へ遡及しない後方as-of、Historical Sharesと当時Raw Closeを再利用。分割後EPSの単位不明はPERを欠損化。引け後／不明時刻の決算は翌日の反応確認→次の始値。未来の完了／損益でEntryを事前選別しない。Train/Testを別資金で実行し、Train候補をTestで選び直さない。Test価格や欠損を書き換えてもTrain結果・候補が同一という回帰テストあり。

## 7. yfinanceとモデルの制約

完全なPIT財務・改訂履歴は無料Yahooから再現できません。財務は年次YoYの最新観測であり、特定の四半期決算との対応付けを保証しません。過去財務版が無取引になる場合があります。決算カレンダー日時・収録範囲の保証もありません。上場日条件は任意で、信頼できる日付がなければ無取引。現在マスターによる生存者バイアス、端株・調整価格による理論約定、出来高容量・値幅制限・100株単位・配当入金未再現を明記。

## 8. テストと実データ検証

- Python: `pytest -q` **122 passed / 1 skipped**。skipはPostgreSQL専用検証の接続先未指定。既存のStarlette/httpx非推奨警告あり。
- Frontend: Vitest **11 passed**、typecheckとproduction build成功。
- Playwright: **5 passed**（既存4フロー＋新Kenmoフロー）を実API/独立Workerで検証。新フローは実取引理由・API成功・画面エラーなし・曲線・CSV・再実行も確認。
- CLIも隔離キャッシュで同じ4銘柄・2025年・5設定を実行し、終了コード0と成果物保存を確認。
- 共通設定の検証にPydanticを使用するため、CLIのrequirements.txtにも明示。
- `git diff --check` 成功。
- Yahoo実取得: 7203.T決算履歴 **89行**、財務観測 **1行**。取得完了時刻2026-10-02を保存し、2025年の財務条件へ適用しないことを確認。
- 少数実バックテスト: **4477 / 6758 / 7203 / 8306、2025年1月〜12月、Train 1〜6月 / Test 7〜12月、5パラメータ設定**。既存価格・株式数・指数キャッシュだけで実行。
- 実ジョブ `9dcc53e8-349c-4340-bb42-690179114e68` 完了、4銘柄の品質エラーなし、日経平均カバー率100%。

|設定|Train決済数|Test決済数|
|---|---:|---:|
|Bottom / 20営業日後終値|5|3|
|Breakout / 保有20日|5|4|
|Breakout / Trailing15%|4|2|
|Earnings / 保有20日|1|0|
|Growth / 保有20日|0|0|

Growthの無取引は4銘柄の2025年時価総額が50〜300億円の指定帯外だったため。全銘柄とも当時時価総額は243営業日分あることを確認。Earningsの決算キャッシュはこの実検証では7203のみ。全市場の成績・十分なサンプル数を検証したものではなく、全設定が既定の最低100取引未満。

## 9. 実行方法

Web: 市場データ更新→必要なら決算・財務チェック→新規バックテストで戦略選択→比較結果。「同じ条件で再実行」は固定設定を引き継ぐ。

```bash
.venv/bin/python main.py download --tickers 7203 6758 8306 --strategy-data
.venv/bin/python main.py backtest --config config.kenmo.yaml --tickers 7203 6758 8306
```

CLIの既存configとBottom実行は従来と同じ。新戦略は`config.kenmo.yaml`を例に期間・候補を設定。結果は不変Artifactとして保存し、DBスキーマ変更なし。詳細は[KENMO.md](KENMO.md)。

## 10. 今後の改善候補

公表・訂正時点を持つ財務ソース、四半期決算との対応付け、信頼できる上場日と当時Universe／上場廃止履歴、Validation / Walk-Forward、100株単位・配当現金入金・流動性／売買制限。現時点で実装済みとは扱っていません。
