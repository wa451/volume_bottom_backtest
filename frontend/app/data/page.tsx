"use client";
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, useApi } from "@/lib/api";
import { Market } from "@/lib/types";
import { number, pct, dateTime } from "@/lib/format";
import { ErrorBox, Stat, Notice, Empty } from "@/components/common";
export default function DataPage() {
  const router = useRouter();
  const {
    data: m,
    error,
    loading,
  } = useApi<Market>("market-data/status", 15000);
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [onlyErrors, setOnlyErrors] = useState(false);
  const [tickers, setTickers] = useState("");
  const [start, setStart] = useState("2010-01-01");
  const [strategyData, setStrategyData] = useState(false);
  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const pending = useRef(false);
  const last = useRef({ body: "", key: "" });
  const rows = (m?.items || []).filter(
    (x) =>
      (!onlyErrors ||
        x.price_error ||
        x.shares_error ||
        x.earnings_error ||
        x.fundamentals_error) &&
      (x.ticker.toLowerCase().includes(search.toLowerCase()) ||
        x.company_name.includes(search)),
  );
  async function update(retry = false) {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setSubmitError("");
    const body = JSON.stringify({
      start_date: start,
      tickers: tickers.split(/[\s,、]+/).filter(Boolean),
      retry_failed: retry,
      refresh_universe: true,
      include_strategy_data: strategyData,
    });
    if (last.current.body !== body)
      last.current = { body, key: crypto.randomUUID() };
    try {
      const j = await api<{ job_id: string }>("market-data/update", {
        method: "POST",
        headers: { "Idempotency-Key": last.current.key },
        body,
      });
      router.push("/backtests/" + j.job_id);
    } catch (e) {
      setSubmitError((e as Error).message);
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }
  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">MARKET DATA</div>
          <h1>市場データ</h1>
          <p className="subtitle">
            取得済みの履歴を再利用し、不足期間だけを更新します。
          </p>
        </div>
        <span className="muted">
          最終確認 {dateTime(m?.checked_at || null)}
        </span>
      </div>
      <ErrorBox error={error || submitError} />
      <div className="stats">
        <Stat
          label="対象銘柄"
          value={number(m?.stock_count)}
          detail={"JPX " + (m?.source.as_of || "未取得")}
        />
        <Stat
          label="有効価格 / 未取得・不正"
          value={number(m?.price_success_count)}
          detail={number(m?.price_missing_count) + "銘柄が未取得・不正"}
        />
        <Stat
          label="価格データ最終日"
          value={m?.latest_date || "—"}
          detail={"Split " + number(m?.split_events) + "件"}
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
        <h2>データ更新ジョブ</h2>
        <div className="toolbar">
          <label>
            取得開始日
            <input
              type="date"
              value={start}
              onChange={(e) => setStart(e.target.value)}
            />
          </label>
          <label>
            銘柄指定（空欄は全市場）
            <input
              placeholder="7203, 6758"
              value={tickers}
              onChange={(e) => setTickers(e.target.value)}
            />
          </label>
          <button
            className="primary"
            disabled={busy}
            onClick={() => void update()}
          >
            市場データを更新
          </button>
          <button disabled={busy} onClick={() => void update(true)}>
            失敗分を再試行
          </button>
        </div>
        <label>
          <input
            type="checkbox"
            checked={strategyData}
            onChange={(e) => setStrategyData(e.target.checked)}
          />{" "}
          決算日・財務スナップショットも差分更新（Kenmo用）
        </label>
        <p className="check-note">
          決算日は既存履歴へ追加、財務は取得時点を保存します。財務の取得は過去の公表履歴を復元しません。通常は決算日1日・財務7日以内のキャッシュを再利用します。
        </p>
        <p className="check-note">
          株価は最終確定行の確認と最新期間、株式数は取得済み期間の先を取得。調整基準が変わった銘柄は整合性のため履歴を再取得します。成功分は即時保存され、中断後も再利用します。全市場の初回取得は時間がかかります。
        </p>
        {m?.source.last_refresh_error && (
          <ErrorBox error={"JPX更新エラー: " + m.source.last_refresh_error} />
        )}
      </div>
      <div className="panel">
        <div className="panel-head">
          <h2>キャッシュ・取得エラー</h2>
          <span className="muted">
            エラーあり {number(m?.failure_count)}銘柄
          </span>
        </div>
        <div className="toolbar">
          <input
            aria-label="銘柄検索"
            placeholder="コード・企業名で検索"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setOffset(0);
            }}
          />
          <label>
            <span>
              <input
                type="checkbox"
                checked={onlyErrors}
                onChange={(e) => {
                  setOnlyErrors(e.target.checked);
                  setOffset(0);
                }}
              />{" "}
              エラーのみ
            </span>
          </label>
          <span className="muted">
            前回検証の時価総額カバー率{" "}
            {pct(m?.last_backtest_market_cap_coverage, false)}（
            {number(m?.last_backtest_stock_count)}銘柄の選択範囲）
          </span>
        </div>
        {rows.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>銘柄</th>
                  <th>企業名</th>
                  <th>市場</th>
                  <th>価格行</th>
                  <th>最終日</th>
                  <th>株式数行</th>
                  <th>決算日 / 財務観測</th>
                  <th>取得方式</th>
                  <th>エラー</th>
                </tr>
              </thead>
              <tbody>
                {rows.slice(offset, offset + 50).map((x) => (
                  <tr key={x.ticker}>
                    <td>{x.code}</td>
                    <td>{x.company_name}</td>
                    <td>{x.market_segment}</td>
                    <td>{number(x.price_rows)}</td>
                    <td>{x.latest_date || "—"}</td>
                    <td>{number(x.shares_rows)}</td>
                    <td>
                      {number(x.earnings_rows)} / {number(x.fundamentals_rows)}
                    </td>
                    <td>{x.download_mode || "既存 / 未取得"}</td>
                    <td
                      title={
                        (x.price_error || "") +
                        " " +
                        [x.shares_error, x.earnings_error, x.fundamentals_error]
                          .filter(Boolean)
                          .join(" / ")
                      }
                    >
                      {(
                        (x.price_error || "") +
                        " " +
                        [x.shares_error, x.earnings_error, x.fundamentals_error]
                          .filter(Boolean)
                          .join(" / ")
                      ).slice(0, 100) || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty>
            {loading
              ? "読み込み中…"
              : "該当データがありません。既存CLIのキャッシュはWorker起動時に登録されます。"}
          </Empty>
        )}
        <div className="pagination">
          <button disabled={!offset} onClick={() => setOffset(offset - 50)}>
            前へ
          </button>
          <span>
            {Math.min(offset + 50, rows.length)} / {number(rows.length)}
          </span>
          <button
            disabled={offset + 50 >= rows.length}
            onClick={() => setOffset(offset + 50)}
          >
            次へ
          </button>
        </div>
      </div>
      <Notice />
    </>
  );
}
