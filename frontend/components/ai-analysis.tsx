"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Job } from "@/lib/types";
import type {
  AnalysisState,
  AnalysisReport,
  EvidenceCandidate,
} from "@/lib/analysis";
import { dateTime, number, pct, statusLabels } from "@/lib/format";
import { ErrorBox, Empty } from "./common";
import { MarketCapLabel } from "./market-cap";
import StrategyResults from "./strategy-results";

function Parameters({ candidate: c }: { candidate: EvidenceCandidate }) {
  const p = c.parameters;
  const parts: string[] = [];
  if (c.strategy_id === "bottom_volume")
    parts.push(
      `下落率 ${pct(p.drawdown_threshold, false)}`,
      `出来高 ${p.volume_ratio}倍`,
    );
  else {
    parts.push(p.mode === "price_only" ? "価格のみ" : "財務条件あり");
    if (c.strategy_id === "kenmo_breakout")
      parts.push(
        p.high_enabled ? `高値更新 ${p.high_period}営業日` : "高値更新 OFF",
      );
    if (c.strategy_id !== "kenmo_growth")
      parts.push(
        p.volume_enabled ? `出来高 ${p.volume_ratio}倍` : "出来高条件 OFF",
      );
    if (c.strategy_id === "kenmo_earnings")
      parts.push(
        `決算 ${p.entry_offset}営業日後`,
        `反応率 ${pct(p.reaction_rate, false)}`,
      );
    if (c.strategy_id === "kenmo_growth")
      parts.push(
        `時価総額 ${Number(p.cap_min) / 1e8}〜${Number(p.cap_max) / 1e8}億円未満`,
      );
    if (p.mode === "fundamentals") {
      for (const [key, flag, label] of [
        ["revenue_growth", "revenue_enabled", "売上成長"],
        ["earnings_growth", "earnings_enabled", "利益成長"],
        ["roe", "roe_enabled", "ROE"],
      ])
        if (p[flag]) parts.push(`${label} ${pct(p[key], false)}以上`);
      if (p.per_enabled) parts.push(`PER ${p.per_min}〜${p.per_max}倍`);
    }
    if (p.listing_enabled) parts.push(`上場 ${p.listing_years}年以内`);
  }
  if (p.holding_period) parts.push(`保有 ${p.holding_period}営業日`);
  const exits: Record<string, string> = {
    holding: "保有期間後の始値",
    legacy_close: "保有期間後の終値",
    fixed: "固定利確",
    trailing: "トレーリング",
    ma: "移動平均割れ",
  };
  if (p.exit_mode)
    parts.push(`決済 ${exits[String(p.exit_mode)] || p.exit_mode}`);
  if (Number(p.stop_loss) > 0) parts.push(`損切り ${pct(p.stop_loss, false)}`);
  if (p.exit_mode === "fixed") parts.push(`利確 ${pct(p.take_profit, false)}`);
  if (p.exit_mode === "trailing")
    parts.push(`Trailing ${pct(p.trailing_stop, false)}`);
  if (p.exit_mode === "ma") parts.push(`移動平均 ${p.ma_period}営業日`);
  if (p.maximum_holding) parts.push(`最大保有 ${p.maximum_holding}営業日`);
  return (
    <>
      <p>{parts.join(" · ")}</p>
      <details>
        <summary>保存されたパラメータをすべて表示</summary>
        <pre>{JSON.stringify(p, null, 2)}</pre>
      </details>
    </>
  );
}
function Lines({ items }: { items: string[] }) {
  return (
    <ul>
      {items.map((text, i) => (
        <li key={i}>{text}</li>
      ))}
    </ul>
  );
}
function Comparison({
  title,
  rows,
  report: r,
  job,
}: {
  title: string;
  rows: EvidenceCandidate[];
  report: AnalysisReport;
  job: Job;
}) {
  const metric = r.mode === "portfolio" ? "cagr" : "mean_return";
  return (
    <div className="panel">
      <h2>{title}</h2>
      <p className="muted">
        各行の候補をTrainだけで比較し、Testは同じ条件を評価しています。取引なし・無効な行では優劣を判断できません。集計範囲は重複し、取引数を合算できません。
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>手法・条件</th>
              <th>時価総額帯・市場</th>
              <th>Train件数</th>
              <th>Train {r.mode === "portfolio" ? "CAGR" : "平均"}</th>
              <th>
                {r.mode === "portfolio"
                  ? "Train 最大下落"
                  : "Train 95%区間下限"}
              </th>
              <th>Test件数</th>
              <th>Test {r.mode === "portfolio" ? "CAGR" : "平均"}</th>
              <th>Train採用条件</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr
                key={[
                  c.strategy_id,
                  c.parameter_id,
                  c.market_cap_group,
                  c.market_segment,
                ].join("/")}
              >
                <td>
                  <strong>{c.strategy_name}</strong>
                  <Parameters candidate={c} />
                </td>
                <td>
                  <MarketCapLabel
                    group={c.market_cap_group}
                    bins={job.market_cap_bins || []}
                  />
                  <small>
                    {c.market_segment === "ALL" ? "全市場" : c.market_segment}
                  </small>
                </td>
                <td>{number(c.train.num_trades)}</td>
                <td
                  className={
                    Number(c.train[metric]) > 0 ? "positive" : "negative"
                  }
                >
                  {pct(c.train[metric])}
                </td>
                <td>
                  {pct(
                    c.train[
                      r.mode === "portfolio" ? "max_drawdown" : "ci95_lower"
                    ],
                  )}
                </td>
                <td>{number(c.test?.num_trades)}</td>
                <td>{pct(c.test?.[metric])}</td>
                <td>{c.eligible ? "条件充足" : c.blockers.join(" / ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
export default function AIAnalysis({ job }: { job: Job }) {
  const [state, setState] = useState<AnalysisState>();
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const path = `backtests/${job.id}/analysis`;
    const read = async () => {
      try {
        const value = await api<AnalysisState>(path);
        if (alive) {
          setState(value);
          setError("");
        }
        if (alive && !["completed", "failed"].includes(value.status))
          timer = setTimeout(read, 2000);
      } catch (e) {
        if (alive) setError((e as Error).message);
      }
    };
    const start = async () => {
      setState(undefined);
      setError("");
      try {
        await api(path + (revision ? "?retry=true" : ""), { method: "POST" });
        if (alive) await read();
      } catch (e) {
        if (alive) setError((e as Error).message);
      }
    };
    void start();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [job.id, revision]);
  const r = state?.report;
  return (
    <div role="tabpanel" aria-label="AI分析">
      <div className="panel">
        <div className="eyebrow">BACKTEST ANALYSIS</div>
        <h2>検証結果からの分析</h2>
        <p>
          この実行に保存された全戦略・全パラメータ・時価総額帯を比較します。他のタブの表示フィルターは分析に影響しません。
        </p>
        {r && (
          <p className="muted">
            {r.generation.label}
            {r.generation.model ? ` · ${r.generation.model}` : ""} ·{" "}
            {dateTime(r.generated_at)} 保存
          </p>
        )}
      </div>
      <ErrorBox error={error || state?.error_message || ""} />
      {(error || state?.status === "failed") && (
        <button onClick={() => setRevision((v) => v + 1)}>分析を再試行</button>
      )}
      {!r && !error && state?.status !== "failed" && (
        <Empty>
          {state
            ? `${statusLabels[state.status] || "分析を準備中"}… ${number(state.progress_percent)}%（独立Workerで処理）`
            : "分析を準備中…"}
        </Empty>
      )}
      {r && (
        <>
          <div className="panel">
            <div className="eyebrow">
              {r.status === "supported"
                ? "第一候補・Test条件充足"
                : r.status === "unconfirmed"
                  ? "Train第一候補・Test未確認"
                  : "根拠不足・推奨保留"}
            </div>
            <h2>{r.conclusion}</h2>
            <p className="muted">
              Train {r.periods.train.start}〜{r.periods.train.end} / Test{" "}
              {r.periods.test.start}〜{r.periods.test.end} · 最低
              {r.minimum_trades}取引／期間
            </p>
            {r.reference && (
              <>
                <h3>
                  {r.selected
                    ? "選んだ手法・パラメータ・規模"
                    : "次の検証に使う参考候補"}
                </h3>
                <strong>{r.reference.strategy_name}</strong>
                <p>
                  <MarketCapLabel
                    group={r.reference.market_cap_group}
                    bins={job.market_cap_bins || []}
                  />{" "}
                  ·{" "}
                  {r.reference.market_segment === "ALL"
                    ? "全市場"
                    : r.reference.market_segment}
                </p>
                <Parameters candidate={r.reference} />
              </>
            )}
            <h3>この判断の理由</h3>
            <Lines items={r.reasons} />
          </div>
          {r.ai_commentary && (
            <div className="panel">
              <h2>生成AIの補足解説</h2>
              <Lines items={r.ai_commentary.interpretation} />
              <h3>解釈上の注意</h3>
              <Lines items={r.ai_commentary.caveats} />
              <h3>次に検証すること</h3>
              <Lines items={r.ai_commentary.next_steps} />
            </div>
          )}
          <Comparison
            title="手法別の最上位候補"
            rows={r.strategy_comparison}
            report={r}
            job={job}
          />
          <Comparison
            title="時価総額帯別の最上位候補"
            rows={r.cap_comparison}
            report={r}
            job={job}
          />
          <Comparison
            title="条件の比較（Train上位20件）"
            rows={r.comparison}
            report={r}
            job={job}
          />
          <div className="panel">
            <h2>判断の限界・次の検証</h2>
            <Lines items={r.risks} />
            <h3>次に検証すること</h3>
            <Lines items={r.next_steps} />
            <details>
              <summary>比較方法と保存設定</summary>
              <p>{r.methodology}</p>
              <p>
                買付費用 {pct(r.costs.buy_cost_rate, false)} / 売却費用{" "}
                {pct(r.costs.sell_cost_rate, false)} / Slippage{" "}
                {pct(r.costs.slippage_rate, false)}
              </p>
              <p>
                Event
                Studyは取引の収益分布、Portfolioは資金・現金・未決済評価を含む資産指標です。両者のリターンは直接比較できません。
              </p>
            </details>
            <a
              className="button"
              href={
                "data:application/json;charset=utf-8," +
                encodeURIComponent(JSON.stringify(r, null, 2))
              }
              download={`analysis-${job.id}.json`}
            >
              分析JSONを保存 ↓
            </a>
          </div>
        </>
      )}
    </div>
  );
}
export function PortfolioResultsTabs({ job }: { job: Job }) {
  const [tab, setTab] = useState("results");
  return (
    <>
      <div className="tabs" role="tablist" aria-label="結果表示">
        {[
          ["results", "結果比較"],
          ["analysis", "AI分析"],
        ].map(([id, label]) => (
          <button
            key={id}
            role="tab"
            aria-selected={tab === id}
            className={tab === id ? "active" : ""}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "analysis" ? (
        <AIAnalysis job={job} />
      ) : (
        <StrategyResults job={job} />
      )}
    </>
  );
}
