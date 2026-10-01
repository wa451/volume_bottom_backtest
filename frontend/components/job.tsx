"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, useApi } from "@/lib/api";
import { Job } from "@/lib/types";
import { number, dateTime, statusLabels } from "@/lib/format";
import { Badge, ErrorBox, Empty, Notice } from "./common";
import Results from "./results";
export default function JobPage({ id }: { id: string }) {
  const { data: j, error } = useApi<Job>("jobs/" + id, 2000);
  const [clock, setClock] = useState(Date.now());
  const [busy, setBusy] = useState(false);
  const [rerunError, setRerunError] = useState("");
  const pending = useRef(false);
  const rerunKey = useRef("");
  const router = useRouter();
  useEffect(() => {
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  async function rerun() {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setRerunError("");
    rerunKey.current ||= crypto.randomUUID();
    try {
      const result = await api<{ job_id: string }>(
        "backtests/" + id + "/rerun",
        { method: "POST", headers: { "Idempotency-Key": rerunKey.current } },
      );
      router.push("/backtests/" + result.job_id);
    } catch (e) {
      setRerunError((e as Error).message);
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }
  if (!j)
    return (
      <>
        <ErrorBox error={error} />
        <Empty>
          {error ? "ジョブを取得できません。" : "ジョブを読み込み中…"}
        </Empty>
      </>
    );
  const elapsed = j.started_at
    ? Math.max(
        0,
        Math.floor(
          ((j.completed_at ? new Date(j.completed_at).getTime() : clock) -
            new Date(j.started_at).getTime()) /
            1000,
        ),
      )
    : 0;
  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">
            {j.kind === "update" ? "DATA UPDATE" : "BACKTEST RESULTS"} ·{" "}
            {id.slice(0, 8)}
          </div>
          <h1>
            {j.kind === "update" ? "市場データ更新" : "バックテスト"}{" "}
            <Badge status={j.status} />
          </h1>
          <p className="subtitle">
            {j.kind === "backtest" && (
              <>
                {j.config.start_date} → {j.config.end_date}　·　
              </>
            )}
            {dateTime(j.created_at)} 登録
          </p>
        </div>
        {j.kind === "backtest" && (
          <button disabled={busy} onClick={() => void rerun()}>
            同じ条件で再実行
          </button>
        )}
      </div>
      <ErrorBox error={error || rerunError || j.error_message || ""} />
      {j.status !== "completed" && (
        <div className="panel">
          <div className="progress-title">
            <h2>{statusLabels[j.status]}</h2>
            <strong>{j.progress_percent.toFixed(0)}%</strong>
          </div>
          <div
            className="progress-track"
            role="progressbar"
            aria-label="ジョブ進捗"
            aria-valuenow={j.progress_percent}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <div style={{ width: j.progress_percent + "%" }} />
          </div>
          <div className="toolbar">
            <span>{j.current_step}</span>
            <span className="muted">
              {number(j.processed_items)} / {number(j.total_items)} 処理単位
            </span>
          </div>
          <p className="muted">
            開始 {dateTime(j.started_at)}　·　経過 {Math.floor(elapsed / 60)}分
            {elapsed % 60}秒　·　試行 {j.attempts}回
          </p>
          {j.status === "queued" && (
            <p className="muted">
              独立Workerの起動を待っています。画面を閉じてもジョブは保存されます。
            </p>
          )}
          <Link href={j.kind === "update" ? "/data" : "/backtests"}>
            一覧へ戻る ↗
          </Link>
        </div>
      )}
      {j.status === "completed" && j.kind === "backtest" && <Results job={j} />}{" "}
      {j.status === "completed" && j.kind === "update" && (
        <>
          <div className="panel">
            <h2>データ更新が完了しました</h2>
            <div className="mini-stats">
              <div>
                取得成功<strong>{number(j.summary.downloaded)}</strong>
              </div>
              <div>
                取得済みスキップ<strong>{number(j.summary.cached)}</strong>
              </div>
              <div>
                取得失敗<strong>{number(j.summary.failed)}</strong>
              </div>
            </div>
            <p className="muted">
              価格・株式数・ベンチマークごとの処理数です。個別失敗はキャッシュを保護して記録しています。
            </p>
            <div className="csv-row">
              <Link className="button" href="/data">
                データ品質を確認
              </Link>
              <Link className="button primary" href="/backtest/new">
                バックテストへ →
              </Link>
            </div>
          </div>
          {j.summary.items?.some((x) => x.status === "failed") && (
            <div className="panel">
              <h2>取得失敗</h2>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>銘柄</th>
                      <th>データ</th>
                      <th>理由</th>
                    </tr>
                  </thead>
                  <tbody>
                    {j.summary.items
                      .filter((x) => x.status === "failed")
                      .map((x) => (
                        <tr key={x.ticker + x.kind}>
                          <td>{x.ticker}</td>
                          <td>{x.kind}</td>
                          <td>{x.error}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
          <Notice />
        </>
      )}
    </>
  );
}
