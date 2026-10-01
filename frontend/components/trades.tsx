"use client";
import { useState } from "react";
import { useApi, query } from "@/lib/api";
import { Metrics, Page } from "@/lib/types";
import { pct, number, cap, capLabels } from "@/lib/format";
import { ErrorBox, Empty } from "./common";
export default function Trades({
  id,
  filters,
  compact = false,
}: {
  id: string;
  filters: Record<string, string | number>;
  compact?: boolean;
}) {
  const [search, setSearch] = useState("");
  const [outcome, setOutcome] = useState("all");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [status, setStatus] = useState("complete");
  const [pageState, setPage] = useState({ scope: "", offset: 0 });
  const q = query({
    ...filters,
    search,
    outcome,
    signal_start: start,
    signal_end: end,
    trade_status: status,
  });
  const offset = pageState.scope === q ? pageState.offset : 0;
  const { data, error, loading } = useApi<Page<Metrics>>(
    "backtests/" + id + "/trades?" + q + "&limit=50&offset=" + offset,
  );
  function paginate(v: number) {
    setPage({ scope: q, offset: v });
  }
  const day = (v: unknown) => (typeof v === "string" ? v.slice(0, 10) : "—");
  return (
    <div className="panel">
      <div className="panel-head">
        <h2>{compact ? "選択条件の取引" : "取引一覧"}</h2>
        <a
          className="button"
          href={"/api/backtests/" + id + "/trades.csv?" + q}
        >
          現在の条件で CSV ↓
        </a>
      </div>
      <div className="toolbar">
        <label>
          銘柄・企業名
          <input
            aria-label="取引銘柄検索"
            placeholder="7203 / トヨタ"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <label>
          Signal開始
          <input
            type="date"
            value={start}
            onChange={(e) => setStart(e.target.value)}
          />
        </label>
        <label>
          Signal終了
          <input
            type="date"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
          />
        </label>
        <label>
          損益
          <select value={outcome} onChange={(e) => setOutcome(e.target.value)}>
            <option value="all">すべて</option>
            <option value="profit">利益</option>
            <option value="loss">損失</option>
          </select>
        </label>
        <label>
          取引状態
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="complete">有効取引</option>
            <option value="all">すべて</option>
            <option value="boundary_purged">境界除外</option>
            <option value="incomplete">保有期間未成熟</option>
            <option value="invalid_price">不正価格</option>
          </select>
        </label>
      </div>
      <ErrorBox error={error} />
      {data?.items.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {[
                  "コード",
                  "企業名",
                  "市場",
                  "Signal日",
                  "Signal株価",
                  "Drawdown",
                  "Volume",
                  "時価総額",
                  "規模",
                  "Entry日",
                  "Entry価格",
                  "Exit日",
                  "Exit価格",
                  "Return",
                  "状態",
                ].map((x) => (
                  <th key={x}>{x}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.items.map((r, i) => (
                <tr key={i}>
                  <td>{r.code}</td>
                  <td>{r.company_name}</td>
                  <td>{r.market_segment}</td>
                  <td>{day(r.signal_date)}</td>
                  <td>{number(r.signal_price, 2)}</td>
                  <td>{pct(r.actual_drawdown)}</td>
                  <td>{number(r.actual_volume_ratio, 2)}x</td>
                  <td>{cap(r.market_cap)}</td>
                  <td>
                    {capLabels[String(r.market_cap_group)] ||
                      r.market_cap_group}
                  </td>
                  <td>{day(r.entry_date)}</td>
                  <td>{number(r.entry_price, 2)}</td>
                  <td>{day(r.exit_date)}</td>
                  <td>{number(r.exit_price, 2)}</td>
                  <td
                    className={
                      typeof r.return === "number" && r.return > 0
                        ? "positive"
                        : "negative"
                    }
                  >
                    {pct(r.return)}
                  </td>
                  <td>{r.trade_status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty>
          {loading ? "取引を読み込み中…" : "この条件の取引はありません。"}
        </Empty>
      )}
      <p className="check-note">
        Signal株価は当日Raw
        Close。Entry・Exitは同じEntry日株価単位に揃えた配当・分割調整、費用控除後価格です。未成熟・境界除外のReturnは欠損です。
      </p>
      <div className="pagination">
        <button disabled={!offset} onClick={() => paginate(offset - 50)}>
          前へ
        </button>
        <span>
          {Math.min(offset + 50, data?.total || 0)} / {number(data?.total || 0)}
        </span>
        <button
          disabled={offset + 50 >= (data?.total || 0)}
          onClick={() => paginate(offset + 50)}
        >
          次へ
        </button>
      </div>
    </div>
  );
}
