<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

## このFrontendのルール

- 親ディレクトリの `AGENTS.md` に従う。作業後のテスト・コミット・プッシュ方針も継承する。
- Next.js App Router / TypeScript。取得・バックテストは独立Python Workerで行い、Frontendでは計算しない。
- 認証情報はRoute Handlerのサーバー環境変数に限定し、`NEXT_PUBLIC_*` へ公開しない。
- 日本語、プラス赤・マイナス青、欠損と0の区別、件数不足、Train/Testの区別を維持する。
