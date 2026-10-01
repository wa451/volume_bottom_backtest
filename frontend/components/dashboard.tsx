"use client";
import Link from "next/link";
import { useApi } from "@/lib/api";
import { Market, Job, Page } from "@/lib/types";
import { dateTime, number, pct } from "@/lib/format";
import { ErrorBox, Stat, JobsTable, Empty, Notice } from "./common";
export default function Dashboard() {
  const market = useApi<Market>("market-data/status", 15000);
  const jobs = useApi<Page<Job>>("jobs?limit=8", 5000);
  const m = market.data;
  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">RESEARCH OVERVIEW</div>
          <h1>Dashboard</h1>
          <p className="subtitle">
            底値と出来高の組み合わせから、日本株のリターンを検証する。
          </p>
        </div>
        <Link className="button primary" href="/backtest/new">
          ＋ 新規バックテスト
        </Link>
      </div>
      <ErrorBox error={market.error || jobs.error} />
      <div className="stats">
        <Stat
          label="価格データ最終日"
          value={m?.latest_date || "—"}
          detail={"確認: " + dateTime(m?.checked_at || null)}
        />
        <Stat
          label="価格キャッシュ / 対象銘柄"
          value={number(m?.price_success_count)}
          detail={"対象 " + number(m?.stock_count) + "銘柄"}
        />
        <Stat
          label="実行履歴"
          value={number(jobs.data?.total)}
          detail="データ更新・バックテスト"
        />
        <Stat
          label="Historical Shares取得率"
          value={pct(m?.shares_coverage, false)}
          detail={
            "空でないキャッシュ " + number(m?.shares_success_count) + "銘柄"
          }
        />
      </div>
      <div className="panel">
        <div className="panel-head">
          <h2>最近の実行</h2>
          <Link href="/backtests">検証履歴をすべて見る ↗</Link>
        </div>
        {jobs.data?.items.length ? (
          <JobsTable jobs={jobs.data.items} />
        ) : (
          <Empty>
            {jobs.loading
              ? "読み込み中…"
              : "まだジョブがありません。市場データを確認し、検証を始めてください。"}
          </Empty>
        )}
      </div>
      <div className="detail-grid">
        <div className="panel">
          <h2>データの状態</h2>
          <div className="quality-list">
            <div>
              価格未取得 / 不正{" "}
              <strong>{number(m?.price_missing_count)}</strong>
            </div>
            <div>
              取得エラーあり <strong>{number(m?.failure_count)}</strong>
            </div>
            <div>
              JPX基準日 <strong>{m?.source.as_of || "未登録"}</strong>
            </div>
            <div>
              Split検出 <strong>{number(m?.split_events)}</strong>
            </div>
          </div>
          <Link className="button section-gap" href="/data">
            市場データを確認 →
          </Link>
        </div>
        <div className="panel">
          <h2>検証の進め方</h2>
          <p className="check-note">
            01　市場データを差分更新
            <br />
            02　下落率 × 出来高倍率 × 保有期間を選択
            <br />
            03　Trainで候補を選び、Testで再現性を確認
          </p>
          <p className="muted">
            バックテストは保存済みデータだけを使います。未取得銘柄は品質レポートに記録します。
          </p>
        </div>
      </div>
      <Notice />
    </>
  );
}
