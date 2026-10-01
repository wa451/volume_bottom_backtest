# Web版検証記録 — 2026-10-01

## 実行環境と合否

- macOS / Python 3.12、Next.js 16.3.8、React 19.3.0、Node.js 26.7.0。
- Python: `TEST_DATABASE_URL=... .venv/bin/python -m pytest -q` → **86 passed**。
  - 既存Core / Pipeline / CLI 75件の回帰を含む。
  - API / Worker / Storage 10件、PostgreSQL実接続1件を追加。
  - 空キャッシュ・境界除外・FULL結合・当時時価総額・規模選択・PF∞/NaNのJSON・検索/ページング/CSV・再実行・不変設定・二重登録・リース切れ再開・所有権チェックを検証。
  - バックテストのテストではYahoo / JPXのネットワーク呼び出しを禁止。
- PostgreSQL 16.15: localhost55432の専用テストDB・独立スキーマで、4並列の初期化/同一キー登録/ジョブ取得、JSONB、SKIP LOCKED、リース回収、旧Workerの書込拒否を実測。検証後にテストサーバーを停止。常駐サービスは登録していない。
- Frontend: `npm run test` → **8 passed**（金融数値、欠損、東京時間、公開認証）。
- `npm run typecheck` / `npm run build` → 成功。Dashboard / Data / New / History / Job / API proxyを生成。
- Playwright + Chromium + **実API / 独立Worker** → **1 passed**、最終実行約35秒。
  - 新規設定・二重クリックで1件のみ登録・完了まで進捗取得。
  - ヒートマップ・条件詳細・分布・期間/保有/規模の切替。
  - 時価総額/市場比較・ランキング・取引検索・CSV・再実行・履歴・Data画面。
  - ブラウザの未処理例外なし。スクリーンショットで値と表の表示を確認。
- Ruff（新規Pythonの未使用import等） / `git diff --check` → 成功。
- `docker compose config -q` → 成功。Docker daemonが起動していないため、コンテナのimage build / Composeでの実起動は未実施。ローカル実行と実PostgreSQL接続は別途上記で確認。
- Starlette TestClientからhttpx利用に関する依存ライブラリのDeprecationWarningが1件。テスト失敗ではない。

## 実データでの確認（少数銘柄・保存済みキャッシュ）

対象は `130A.T, 4477.T, 6758.T, 7203.T, 8306.T`。バックテストでは保存済み価格/株式数を使い、Yahooから取得し直していない。

| 指標 | 実測 |
|---|---:|
| JPX現在マスター | 3,700銘柄（公表基準日2026-08-31） |
| 既存の有効価格キャッシュ | 5銘柄 / マスター3,700銘柄 |
| 今回の選択範囲の有効価格 | 5/5 = 100% |
| 今回の選択範囲の株式数キャッシュ | 5/5 = 100%（全過去日を保証する値ではない） |
| 保存価格の最終日 | 2026-10-01 |
| 分析期間 | 2010-01-01〜2026-10-01 |
| 条件・保有期間 | 25条件 × 20/60/120/250営業日 |
| unique Signal | 272件 |
| 有効取引 | 3,004件（条件・保有期間による重複あり） |
| Signal時価総額カバー率 | 189/272 = **69.49%** |
| 有効取引の時価総額カバー率 | **71.90%** |
| Train/Test境界除外 | 163件 |
| 保有期間未成熟 | 313件 |
| Entry/Exit不正価格 | 0件 |
| Split検出 | 3件 |
| 価格欠損セル / 欠損東証営業日 | 54セル / 9日 |

この100%は今回の5銘柄の既存yfinance由来キャッシュ検証率であり、Web版での新規Yahoo取得成功率・全市場の取得成功率ではない。全市場3,700銘柄のうち残り3,695銘柄は未取得。Data画面は未取得と実際の取得失敗を分けて表示する。多数銘柄を単なるコード検証目的で取得していない。

更新処理は既存の差分要求・取得済みスキップ・部分失敗・過去範囲補完・分割/配当による再調整・キャッシュ保護テストに加え、Webの更新ジョブ登録と永続失敗履歴からの再試行を検証した。今回のWeb動作確認では不要な新規全市場取得を行っていない。

## 保存と配置

- ジョブ、固定設定、集計、取引Artifact位置、品質メタデータをDBへ保持し、新規・再実行の両結果を再閲覧できる。
- Local Storageの市場バックアップからの復元を実ファイルで検証。
- Supabase StorageのPrivate認証・Upload/Get・APIキャッシュ、S3互換adapterのUpload/Getはモックで契約を検証。実Supabase/S3アカウントへの接続は未検証。
- Render API/Worker、Worker永続ディスク、Vercel Root Directory、Supabase PostgreSQL/Private Bucketの設定・環境変数例を用意。実サービスは未デプロイ。
- ローカルUI <http://127.0.0.1:3000>、API8000、別Workerで確認。プロセスを停止した後は [起動手順](docs/WEB.md) の3コマンドで再開できる。

## 解釈の制約

現在上場株だけのSurvivorship Bias、現在市場区分、無料Yahooの欠損、厳密な公表時点を保証しない株式数、分割/repairの誤り、重複取引・多重比較がある。FULLは境界除外済みTrain/Testを結合した参考値。少数銘柄では最低100件を満たさず候補なしになるセルが多い。株式数欠損を現在値や推測で埋めていない。Event Studyの検証で、売買推奨やPortfolioのCAGR/Sharpeを算出していない。
