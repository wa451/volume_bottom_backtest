"use client";
import { useState } from "react";
import { useApi, query } from "@/lib/api";
import type { Job, Page, StrategyParameters } from "@/lib/types";
import { strategyNames } from "@/lib/strategy";
import { MarketCapLabel, MarketCapGuide } from "./market-cap";
import { ErrorBox, Empty, Notice } from "./common";
import { number } from "@/lib/format";

type Row = {
  strategy_id: string;
  parameter_id: string;
  parameters: StrategyParameters;
  train_selected: boolean;
  insufficient_sample: boolean;
  metrics_valid: boolean;
  [key: string]: unknown;
};
type Curve = {
  date: string;
  equity: number;
  drawdown: number;
  benchmark: number | null;
};
type Trade = {
  ticker: string;
  company_name: string;
  entry_date: string;
  exit_date: string | null;
  entry_reason: string;
  exit_reason: string;
  entry_price: number;
  exit_price: number | null;
  return: number | null;
  holding_days: number;
  trade_status: string;
};
const metrics: [string, string, boolean][] = [
  ["total_return", "総リターン", true],
  ["cagr", "CAGR", true],
  ["max_drawdown", "最大DD", true],
  ["win_rate", "勝率", true],
  ["num_trades", "取引数", false],
  ["average_win", "平均利益", true],
  ["average_loss", "平均損失", true],
  ["payoff_ratio", "Payoff", false],
  ["profit_factor", "PF", false],
  ["sharpe_ratio", "Sharpe", false],
  ["sortino_ratio", "Sortino", false],
  ["average_holding_days", "平均保有日数", false],
  ["expectancy", "Expectancy", true],
  ["calmar_ratio", "Calmar", false],
  ["median_return", "中央値", true],
  ["maximum_wins", "最大連勝", false],
  ["maximum_losses", "最大連敗", false],
  ["top_10_profit_dependency", "上位10%利益依存度", true],
];
function fmt(v: unknown, percent = false) {
  return typeof v === "number" && Number.isFinite(v)
    ? (v * (percent ? 100 : 1)).toLocaleString("ja-JP", {
        maximumFractionDigits: 2,
      }) + (percent ? "%" : "")
    : "—";
}
function metricColor(value: unknown) {
  return typeof value === "number"
    ? value > 0
      ? "positive"
      : value < 0
        ? "negative"
        : undefined
    : undefined;
}
function paramLabel(id: string, p: StrategyParameters) {
  const parts: string[] = [];
  if (id === "bottom_volume")
    parts.push(
      `下落${fmt(p.drawdown_threshold, true)}`,
      `出来高${p.volume_ratio}倍`,
    );
  else parts.push(p.mode === "price_only" ? "価格版" : "財務版");
  if (id === "kenmo_breakout" && p.high_enabled)
    parts.push(`高値${p.high_period}日`);
  if ((id === "kenmo_breakout" || id === "kenmo_earnings") && p.volume_enabled)
    parts.push(`出来高${p.volume_ratio}倍`);
  if (id === "kenmo_earnings")
    parts.push(
      `反応${fmt(p.reaction_rate, true)}`,
      `決算${p.entry_offset}営業日後`,
    );
  if (id === "kenmo_growth")
    parts.push(
      `時価総額${Number(p.cap_min) / 1e8}〜${Number(p.cap_max) / 1e8}億円未満`,
    );
  if (p.mode === "fundamentals") {
    for (const [key, enabled, label] of [
      ["revenue_growth", "revenue_enabled", "売上"],
      ["earnings_growth", "earnings_enabled", "EPS/利益"],
      ["roe", "roe_enabled", "ROE"],
    ])
      if (p[enabled]) parts.push(label + fmt(p[key], true));
    if (p.per_enabled) parts.push(`PER${p.per_min}〜${p.per_max}倍`);
  }
  if (p.listing_enabled) parts.push(`上場${p.listing_years}年以内`);
  if (Number(p.stop_loss) > 0) parts.push(`損切り${fmt(p.stop_loss, true)}`);
  if (p.exit_mode === "holding" || p.exit_mode === "legacy_close")
    parts.push(
      `保有${p.holding_period}営業日${p.exit_mode === "legacy_close" ? "後終値" : ""}`,
    );
  else if (p.exit_mode === "fixed")
    parts.push(`利確${fmt(p.take_profit, true)}`);
  else if (p.exit_mode === "trailing")
    parts.push(`Trailing${fmt(p.trailing_stop, true)}`);
  else if (p.exit_mode === "ma") parts.push(`MA${p.ma_period}日割れ`);
  return parts.join(" · ");
}
function CurveChart({
  rows,
  drawdown = false,
}: {
  rows: Curve[];
  drawdown?: boolean;
}) {
  if (!rows.length) return <Empty>この範囲には資産曲線がありません。</Empty>;
  const values = rows.flatMap((r) =>
    drawdown
      ? [r.drawdown * 100]
      : [r.equity, ...(r.benchmark === null ? [] : [r.benchmark])],
  );
  const min = drawdown ? Math.min(-1, ...values) : Math.min(...values),
    max = drawdown ? 0 : Math.max(...values);
  const x = (i: number) => 90 + (i / Math.max(1, rows.length - 1)) * 940;
  const y = (v: number) => 20 + ((max - v) / Math.max(1e-8, max - min)) * 190;
  const path = (key: "equity" | "benchmark" | "drawdown") => {
    let previous = false;
    return rows
      .map((r, i) => {
        const value = r[key];
        if (value === null || !Number.isFinite(value)) {
          previous = false;
          return "";
        }
        const cmd = previous ? "L" : "M";
        previous = true;
        return (
          cmd +
          x(i).toFixed(2) +
          "," +
          y(key === "drawdown" ? value * 100 : value).toFixed(2)
        );
      })
      .join(" ");
  };
  return (
    <div className="portfolio-chart">
      <svg
        role="img"
        aria-label={drawdown ? "ドローダウン曲線" : "資産曲線とベンチマーク"}
        viewBox="0 0 1100 260"
        width="100%"
      >
        <text x="0" y="30">
          {fmt(max)}
          {drawdown ? "%" : "円"}
        </text>
        <text x="0" y="212">
          {fmt(min)}
          {drawdown ? "%" : "円"}
        </text>
        <line x1="90" x2="1030" y1="210" y2="210" stroke="var(--line)" />
        <path
          d={path(drawdown ? "drawdown" : "equity")}
          fill="none"
          stroke={drawdown ? "var(--negative)" : "var(--positive)"}
          strokeWidth="2"
        />
        {!drawdown && (
          <path
            d={path("benchmark")}
            fill="none"
            stroke="#888"
            strokeWidth="1.5"
            strokeDasharray="5 4"
          />
        )}
        <text x="90" y="245">
          {rows[0].date.slice(0, 10)}
        </text>
        <text x="875" y="245">
          {rows[rows.length - 1].date.slice(0, 10)}
        </text>
      </svg>
      <p className="muted">
        {drawdown
          ? "初期資金を含む最高資産からの下落率"
          : "実線：戦略　破線：ベンチマーク（欠損部分は描画しません）"}
      </p>
    </div>
  );
}
export default function StrategyResults({ job }: { job: Job }) {
  const [period, setPeriod] = useState("test");
  const [cap, setCap] = useState("ALL");
  const [market, setMarket] = useState("ALL");
  const [sort, setSort] = useState("cagr");
  const [selected, setSelected] = useState<{
    strategy_id: string;
    parameter_id: string;
  } | null>(null);
  const [tradeOffset, setTradeOffset] = useState(0);
  const base = "backtests/" + job.id + "/";
  const scope = {
    period_type: period,
    market_cap_group: cap,
    market_segment: market,
  };
  const all = useApi<Page<Row>>(
    base + "strategy-results?" + query({ ...scope, sort, limit: 1000 }),
  );
  const train = useApi<Page<Row>>(
    base +
      "strategy-results?" +
      query({ ...scope, period_type: "train", sort: "cagr", limit: 1000 }),
  );
  const ids = job.config.strategy_ids || [];
  const comparisons = ids.map((id) => {
    const choices = (train.data?.items || []).filter(
      (r) => r.strategy_id === id,
    );
    const candidate =
      choices.find((r) => r.train_selected) ||
      choices
        .slice()
        .sort((a, b) => a.parameter_id.localeCompare(b.parameter_id))[0];
    const current = (all.data?.items || []).find(
      (r) => r.strategy_id === id && r.parameter_id === candidate?.parameter_id,
    );
    return { id, row: current, candidate };
  });
  const active =
    (selected &&
      all.data?.items.find(
        (r) =>
          r.strategy_id === selected.strategy_id &&
          r.parameter_id === selected.parameter_id,
      )) ||
    comparisons.find((x) => x.row)?.row;
  const filter = active
    ? query({
        ...scope,
        strategy_id: active.strategy_id,
        parameter_id: active.parameter_id,
      })
    : null;
  const curves = useApi<Page<Curve>>(
    filter ? base + "strategy-curves?" + filter : null,
  );
  const trades = useApi<Page<Trade>>(
    filter
      ? base + "strategy-trades?" + filter + "&offset=" + tradeOffset
      : null,
  );
  const changeScope = (set: (v: string) => void, value: string) => {
    set(value);
    setSelected(null);
    setTradeOffset(0);
  };
  return (
    <>
      <div className="panel">
        <h2>戦略比較・ポートフォリオ検証</h2>
        <p>
          前日資産の1 / 最大同時保有数を予算として、現金の範囲で買付。Train /
          Testは別資金で開始します。無取引・取引数不足も確認してください。
        </p>
        <details open>
          <summary>データと検証の制約</summary>
          {job.summary.warnings?.map((w) => (
            <p className="check-note" key={w}>
              {w}
            </p>
          ))}
          <p>{job.summary.full_note}</p>
          <p className="check-note">
            同一日に複数銘柄が発生した場合は銘柄コード順。端株・調整価格の理論モデルです。PFに損失がない場合は∞参考値、その他の計算不能値は「—」。リスク指標は無リスク金利0・年252営業日。
          </p>
        </details>
        <MarketCapGuide bins={job.market_cap_bins} />
        <div className="toolbar">
          <label>
            集計期間
            <select
              aria-label="集計期間"
              value={period}
              onChange={(e) => changeScope(setPeriod, e.target.value)}
            >
              <option value="train">Train</option>
              <option value="test">Test</option>
              <option value="full">FULL（参考）</option>
            </select>
          </label>
          <label>
            時価総額
            <select
              aria-label="時価総額"
              value={cap}
              onChange={(e) => changeScope(setCap, e.target.value)}
            >
              {["ALL", ...job.market_cap_bins.map((b) => b.name)].map((x) => (
                <option key={x} value={x}>
                  {x}
                </option>
              ))}
            </select>
          </label>
          <MarketCapLabel group={cap} bins={job.market_cap_bins} />
          <label>
            市場
            <select
              aria-label="市場"
              value={market}
              onChange={(e) => changeScope(setMarket, e.target.value)}
            >
              {["ALL", ...job.config.markets].map((x) => (
                <option key={x}>{x}</option>
              ))}
            </select>
          </label>
        </div>
        <ErrorBox error={all.error || train.error} />
        <h3>同条件の戦略を横並び比較</h3>
        <p className="check-note">
          Trainで選択した候補のうち先頭の設定を同じ{period.toUpperCase()}
          期間で表示。最低取引数を満たす候補がない場合は設定ID順の参考値です。Testの最大値で選び直しません。
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>指標</th>
                {comparisons.map((x) => (
                  <th key={x.id}>
                    {strategyNames[x.id]}
                    <br />
                    {x.candidate?.train_selected
                      ? "Train候補"
                      : "参考設定（候補なし）"}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {metrics.map(([key, label, percent]) => (
                <tr key={key}>
                  <th>{label}</th>
                  {comparisons.map((x) => (
                    <td
                      key={x.id}
                      className={
                        percent ? metricColor(x.row?.[key]) : undefined
                      }
                    >
                      {key === "profit_factor" && x.row?.profit_factor_no_losses
                        ? "∞（損失なし）"
                        : fmt(x.row?.[key], percent)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="csv-row">
          <a
            className="button"
            href={"/api/" + base + "files/strategy_results.csv"}
          >
            全パラメータ結果 CSV ↓
          </a>
          <a
            className="button"
            href={"/api/" + base + "files/strategy_quality.csv"}
          >
            データ品質 CSV ↓
          </a>
          <a className="button" href={"/api/" + base + "files/run.json"}>
            実行設定 JSON ↓
          </a>
        </div>
      </div>
      <div className="panel">
        <h2>パラメータ比較</h2>
        <div className="toolbar">
          <label>
            並び替え
            <select
              aria-label="並び替え"
              value={sort}
              onChange={(e) => setSort(e.target.value)}
            >
              {[
                ["cagr", "CAGR"],
                ["sharpe_ratio", "Sharpe"],
                ["profit_factor", "Profit Factor"],
                ["max_drawdown", "最大DDが小さい順"],
                ["expectancy", "Expectancy"],
              ].map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <span>{number(all.data?.total)}設定</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>戦略 / 設定</th>
                <th>CAGR</th>
                <th>最大DD</th>
                <th>PF</th>
                <th>Sharpe</th>
                <th>取引数</th>
                <th>確認</th>
              </tr>
            </thead>
            <tbody>
              {all.data?.items.map((r) => (
                <tr key={r.strategy_id + r.parameter_id}>
                  <td>
                    <strong>{strategyNames[r.strategy_id]}</strong>
                    <br />
                    <small>{paramLabel(r.strategy_id, r.parameters)}</small>
                  </td>
                  <td className={metricColor(r.cagr)}>{fmt(r.cagr, true)}</td>
                  <td className={metricColor(r.max_drawdown)}>
                    {fmt(r.max_drawdown, true)}
                  </td>
                  <td>
                    {r.profit_factor_no_losses ? "∞" : fmt(r.profit_factor)}
                  </td>
                  <td>{fmt(r.sharpe_ratio)}</td>
                  <td>
                    {fmt(r.num_trades)}
                    {r.insufficient_sample && " / 件数不足"}
                    {!r.metrics_valid && " / 価格欠損・指標無効"}
                  </td>
                  <td>
                    <button
                      type="button"
                      onClick={() => {
                        setSelected({
                          strategy_id: r.strategy_id,
                          parameter_id: r.parameter_id,
                        });
                        setTradeOffset(0);
                      }}
                    >
                      曲線・取引
                    </button>
                    {r.train_selected && <small> Train候補</small>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {active && (
        <div className="panel">
          <h2>{strategyNames[active.strategy_id]} — 曲線・個別取引</h2>
          <details>
            <summary>この設定の全パラメータ</summary>
            <pre>{JSON.stringify(active.parameters, null, 2)}</pre>
          </details>
          <ErrorBox error={curves.error || trades.error} />
          {!active.metrics_valid && (
            <p className="error">
              保有中に価格欠損があります。曲線は参考値で、CAGR等を無効にしています。
            </p>
          )}
          <h3>Equity Curve · {job.summary.benchmark_ticker}</h3>
          <p className="check-note">
            指数データの対象営業日カバー率：
            {fmt(active.benchmark_coverage, true)}
            。初日の始値がなければ比較曲線は表示しません。
          </p>
          {curves.loading ? (
            <Empty>読み込み中…</Empty>
          ) : (
            <CurveChart rows={curves.data?.items || []} />
          )}
          <h3>Drawdown</h3>
          <CurveChart rows={curves.data?.items || []} drawdown />
          <p className="check-note">
            表示価格は売買コストを含む調整価格。実際の円建て株価・100株単位の約定を再現するものではありません。期間末の未決済は売却日・利益率を空欄とします。
          </p>
          <a
            className="button"
            href={"/api/" + base + "strategy-trades.csv?" + filter}
          >
            表示条件の取引 CSV ↓
          </a>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  {[
                    "銘柄 / 企業",
                    "Entry日 / 価格",
                    "Exit日 / 価格",
                    "利益率",
                    "保有日数",
                    "Entry理由",
                    "Exit理由",
                  ].map((x) => (
                    <th key={x}>{x}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {trades.data?.items.map((t, i) => (
                  <tr key={t.ticker + t.entry_date + i}>
                    <td>
                      {t.ticker}
                      <br />
                      {t.company_name}
                    </td>
                    <td>
                      {t.entry_date.slice(0, 10)}
                      <br />
                      {fmt(t.entry_price)}
                    </td>
                    <td>
                      {t.exit_date?.slice(0, 10) || "未決済"}
                      <br />
                      {fmt(t.exit_price)}
                    </td>
                    <td
                      className={
                        t.return !== null && t.return >= 0
                          ? "positive"
                          : "negative"
                      }
                    >
                      {fmt(t.return, true)}
                    </td>
                    <td>{fmt(t.holding_days)}</td>
                    <td>{t.entry_reason}</td>
                    <td>{t.exit_reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="pagination">
            <button
              disabled={!tradeOffset}
              onClick={() => setTradeOffset(tradeOffset - 50)}
            >
              前へ
            </button>
            <span>
              {Math.min(tradeOffset + 50, trades.data?.total || 0)} /{" "}
              {number(trades.data?.total)}
            </span>
            <button
              disabled={tradeOffset + 50 >= (trades.data?.total || 0)}
              onClick={() => setTradeOffset(tradeOffset + 50)}
            >
              次へ
            </button>
          </div>
        </div>
      )}
      <Notice portfolio />
    </>
  );
}
