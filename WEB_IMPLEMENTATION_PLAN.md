# Web版実装計画

既存の `src/` と CLI を維持し、Next.js / FastAPI / 独立Worker / DB / Artifact Storage を追加する。

1. Core に任意の進捗通知、Signal当日の生価格、規模と市場の同時集計を追加。既存テストで互換性を確認。
2. PostgreSQL互換のSQLAlchemyモデル、永続ジョブキュー、リース・再開・冪等キーを実装。ローカル単体起動はSQLiteも許容。
3. FastAPIの設定・ジョブ・結果・取引検索・分布・CSV・品質API。
4. 独立Worker。データ取得とバックテストを分離し、ジョブごとに結果を保持。価格の共有キャッシュは既存CLIと同じロックで保護。
5. Local / Supabase Storage / S3 のストレージ境界。APIとWorkerのディスクが別でも結果を取得可能にする。
6. Next.js画面（Dashboard / Data / New / History / Job）。Heatmap、比較、ランキング、詳細、取引、CSV、再実行。
7. Docker Compose、Render Blueprint、Vercel設定、環境変数例、README。
8. Core / API / Queue / Worker / Frontend / E2Eを検証し、コミット・プッシュ。

## デフォルトと制約

- バックテストはネットワークを使わずキャッシュのみ。データ更新は別ジョブ。
- 初期値25条件、4保有期間。市場・時価総額の選択に対応し、ALLと区分別を同時集計する。
- FULLは参考表示のためTrain/Testの有効取引を結合し、Train境界除外は解除しない。候補選択はTrainのみ。
- 一意のIdempotency-Keyで二重送信を防ぎ、異なる設定の同一キーを拒否する。
- DBキューを別Workerが消費。処理中はハートビートし、異常終了後はリース期限で再開する。
- 公開用の認証・ストレージ・DB設定は環境変数。実サービスの認証情報がない場合は配置ファイルと手順を完成させ、未デプロイと明記する。
- UIは日本語、表中心、プラス赤・マイナス青。欠損や最低件数不足は表示し、Survivorship Biasの注意を残す。

## 完了記録

全8項目の実装とローカル検証を完了。Python 86件（実PostgreSQL含む）、Frontend 8件、実API/WorkerのPlaywright、型検査、本番ビルド、Compose設定検査に成功。実測は `WEB_VERIFICATION.md`、運用・配置は `docs/WEB.md`。クラウドの認証情報がなく実デプロイは未実施。
