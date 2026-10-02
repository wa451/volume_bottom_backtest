"use client";
import { useState } from "react";
import { useApi, query } from "@/lib/api";
import { Job, Page, Result, Metrics, MarketCapBin } from "@/lib/types";
import {
  pct,
  number,
  metric,
  metrics,
  capLabels,
  marketCapRange,
} from "@/lib/format";
import { ErrorBox, Empty, Stat, Notice } from "./common";
import Trades from "./trades";
import { MarketCapLabel, MarketCapGuide } from "./market-cap";
const metricKeys = [
  "mean_return",
  "median_return",
  "win_rate",
  "profit_factor",
  "expectancy",
  "num_trades",
  "ci95_lower",
];
type Cell = { drawdown_threshold: number; volume_ratio_threshold: number };
export default function Results({ job: j }: { job: Job }) {
  const bins = j.market_cap_bins ?? [];
  const caps = ["ALL", ...bins.map((b) => b.name)];
  const [tab, setTab] = useState("overview");
  const [period, setPeriod] = useState("train");
  const [holding, setHolding] = useState(j.config.holding_periods[0]);
  const [cap, setCap] = useState("ALL");
  const [heatCaps, setHeatCaps] = useState(["ALL"]);
  const [market, setMarket] = useState("ALL");
  const [metricKey, setMetric] = useState("mean_return");
  const [cell, setCell] = useState<Cell>({
    drawdown_threshold: j.config.drawdown_thresholds[0],
    volume_ratio_threshold: j.config.volume_ratio_thresholds[0],
  });
  const [sort, setSort] = useState("mean_return");
  const [descending, setDescending] = useState(true);
  const [offset, setOffset] = useState(0);
  const filters = {
    period_type: period,
    market_cap_group: cap,
    market_segment: market,
    holding_period: holding,
  };
  const scope = query({ ...filters, market_cap_group: "*" });
  const selected = query({ ...filters, ...cell });
  const heat = useApi<Page<Result>>(
    tab === "heatmap"
      ? "backtests/" + j.id + "/results?" + scope + "&limit=1000"
      : null,
  );
  const ranking = useApi<Page<Result>>(
    tab === "ranking"
      ? "backtests/" +
          j.id +
          "/results?" +
          query({
            ...filters,
            holding_period: null,
            sort,
            descending: String(descending),
            offset,
            limit: 100,
          })
      : null,
  );
  const comparison = useApi<Page<Result>>(
    ["cap", "market"].includes(tab)
      ? "backtests/" +
          j.id +
          "/results?" +
          query({
            ...filters,
            ...cell,
            market_cap_group: tab === "cap" ? "*" : cap,
            market_segment: tab === "market" ? "*" : market,
            limit: 100,
          })
      : null,
  );
  const q = j.summary.quality || {};
  const row = heat.data?.items.find(
    (r) =>
      r.market_cap_group === cap &&
      r.drawdown_threshold === cell.drawdown_threshold &&
      r.volume_ratio_threshold === cell.volume_ratio_threshold,
  );
  const visibleHeatRows = (heat.data?.items || []).filter((r) =>
    heatCaps.includes(r.market_cap_group),
  );
  const heatScale = Math.max(
    ...visibleHeatRows.map((r) => Math.abs(Number(r[metricKey]) || 0)),
    0.00001,
  );
  const overviewLabels: Record<string, string> = {
    price_success_count: "有効価格キャッシュ",
    price_failure_or_missing_count: "価格未取得・失敗",
    shares_success_count: "株式数キャッシュあり",
    completed_trade_count: "有効取引",
    boundary_purged: "Train/Test境界の除外",
    incomplete: "保有期間未成熟",
    invalid_price: "Entry / Exit不正価格",
    split_events: "Split検出",
    excluded_signal_parameter_pairs: "分割調整で除外したSignal・条件",
    missing_cells: "価格欠損セル",
    missing_sessions: "価格バーのない東証営業日",
    repaired_rows: "Repairフラグのある行",
  };
  const file = (name: string) => "/api/backtests/" + j.id + "/files/" + name;
  const candidates = (j.summary.candidates || []).filter(
    (r) => r.market_cap_group === "ALL" && r.market_segment === "ALL",
  );
  function changeTab(v: string) {
    setTab(v);
    setOffset(0);
  }
  function selectCap(group: string) {
    if (tab === "heatmap") {
      const next = heatCaps.includes(group)
        ? heatCaps.filter((c) => c !== group)
        : [...heatCaps, group];
      if (!next.length) return;
      setHeatCaps(next);
      if (!heatCaps.includes(group)) setCap(group);
      else if (cap === group) setCap(next[0]);
    } else {
      setCap(group);
      setHeatCaps([group]);
    }
    setOffset(0);
  }
  return (
    <>
      <div className="stats five">
        <Stat
          label="対象銘柄"
          value={number(q.universe_count)}
          detail={"価格有効 " + number(q.price_success_count) + "銘柄"}
        />
        <Stat
          label="Signal数"
          value={number(q.unique_signal_count)}
          detail="銘柄・Signal日で重複除去"
        />
        <Stat
          label="パラメータ条件"
          value={number(j.summary.parameter_combinations)}
          detail={"× " + j.config.holding_periods.length + "保有期間"}
        />
        <Stat
          label="有効取引"
          value={number(q.completed_trade_count)}
          detail="条件・保有期間ごとに重複あり"
        />
        <Stat
          label="時価総額カバー率"
          value={pct(q.market_cap_signal_coverage, false)}
          detail="Signal日当時 / 推測値なし"
        />
      </div>
      <div className="tabs" role="tablist" aria-label="結果表示">
        {[
          ["overview", "概要"],
          ["heatmap", "ヒートマップ"],
          ["cap", "時価総額別"],
          ["market", "市場別"],
          ["ranking", "パラメータ比較"],
          ["trades", "取引一覧"],
        ].map(([key, label]) => (
          <button
            role="tab"
            aria-selected={tab === key}
            className={tab === key ? "active" : ""}
            key={key}
            onClick={() => changeTab(key)}
          >
            {label}
          </button>
        ))}
      </div>
      {tab !== "overview" && (
        <div className="panel">
          <div className="toolbar">
            <label>
              評価期間
              <select
                aria-label="評価期間"
                value={period}
                onChange={(e) => {
                  setPeriod(e.target.value);
                  setOffset(0);
                }}
              >
                <option value="train">TRAIN · 候補選択</option>
                <option value="test">TEST · 検証</option>
                <option value="full">FULL · 参考</option>
              </select>
            </label>
            <label>
              保有期間
              <select
                aria-label="保有期間"
                value={holding}
                onChange={(e) => {
                  setHolding(Number(e.target.value));
                  setOffset(0);
                }}
              >
                {j.config.holding_periods.map((h) => (
                  <option key={h} value={h}>
                    {h}営業日
                  </option>
                ))}
              </select>
            </label>
            <label>
              市場
              <select
                aria-label="市場"
                value={market}
                onChange={(e) => {
                  setMarket(e.target.value);
                  setOffset(0);
                }}
              >
                {["ALL", ...j.config.markets].map((m) => (
                  <option key={m}>{m}</option>
                ))}
              </select>
            </label>
            {tab === "heatmap" && (
              <label>
                セルの指標
                <select
                  aria-label="セルの指標"
                  value={metricKey}
                  onChange={(e) => setMetric(e.target.value)}
                >
                  {metricKeys.map((k) => (
                    <option key={k} value={k}>
                      {metrics[k]}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          <div className="scope-pills" aria-label="時価総額フィルタ">
            {caps.map((x) => (
              <button
                key={x}
                aria-label={capLabels[x] || x}
                title={marketCapRange(x, bins)}
                aria-pressed={
                  tab === "heatmap" ? heatCaps.includes(x) : cap === x
                }
                className={
                  (tab === "heatmap" ? heatCaps.includes(x) : cap === x)
                    ? "active"
                    : ""
                }
                disabled={
                  tab === "heatmap" &&
                  heatCaps.length === 1 &&
                  heatCaps.includes(x)
                }
                onClick={() => selectCap(x)}
              >
                <MarketCapLabel group={x} bins={bins} />
              </button>
            ))}
          </div>
          {tab === "heatmap" && (
            <p className="check-note">
              時価総額は複数選択できます（最低1区分）。選んだ区分を同じ色スケールで並べて表示します。
              ALLも各区分と同時に比較できます。セルをクリックした区分の詳細・取引を下に表示します。
            </p>
          )}
          <p className="check-note">
            {period === "train"
              ? "候補はTrainの成績のみから選択します。"
              : period === "test"
                ? "Testは固定候補の検証用です。Testの順位で候補を選び直さないでください。"
                : j.summary.full_note}
            　最低取引数 {j.summary.minimum_trades}件。* は最低件数未満、—
            は算出不能。
          </p>
        </div>
      )}
      {tab === "overview" && (
        <>
          <div className="panel">
            <h2>実験設定・データ品質</h2>
            <p className="muted">
              Train {j.config.train_start} → {j.config.train_end}　 /　Test{" "}
              {j.config.test_start} → {j.config.test_end}
            </p>
            <p className="muted">
              市場 {j.config.markets.join(" / ")}　·　規模{" "}
              {j.config.market_cap_groups
                .map(
                  (x) =>
                    (capLabels[x] || x) + "（" + marketCapRange(x, bins) + "）",
                )
                .join(" / ")}
              　·　銘柄{" "}
              {j.config.tickers.length ? j.config.tickers.join(", ") : "全対象"}
              　·　Cooldown {j.config.cooldown}営業日
            </p>
            <MarketCapGuide bins={bins} />
            <div className="quality-list">
              {Object.entries(overviewLabels).map(([key, label]) => (
                <div key={key}>
                  {label}
                  <strong>{number(q[key])}</strong>
                </div>
              ))}
            </div>
            <p className="check-note">
              株式数はSignal日以前の履歴に後方as-ofで結合。分割時の単位不明・履歴欠損では時価総額を推測しません。95%
              CIは銘柄クラスタBootstrap。単一銘柄のみのセルではCIを算出できません。
            </p>
            <div className="csv-row">
              <a className="button" href={file("data_quality_report.md")}>
                品質レポート ↓
              </a>
              <a className="button" href={file("run.json")}>
                実行設定 JSON ↓
              </a>
            </div>
          </div>
          <div className="panel">
            <h2>Train固定候補 → Test評価（ALL / ALL）</h2>
            <p className="muted">
              Trainで最低件数を満たす上位条件を各保有期間から選択し、そのままTestへ適用します。
            </p>
            {candidates.length ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Train順位</th>
                      <th>DD</th>
                      <th>VR</th>
                      <th>保有日</th>
                      <th>Train取引数</th>
                      <th>Train平均</th>
                      <th>Test取引数</th>
                      <th>Test平均</th>
                      <th>Test 95% CI</th>
                    </tr>
                  </thead>
                  <tbody>
                    {candidates.map((r, i) => (
                      <tr key={i}>
                        <td>{number(r.candidate_rank)}</td>
                        <td>{pct(r.drawdown_threshold, false)}</td>
                        <td>{number(r.volume_ratio_threshold, 2)}x</td>
                        <td>{number(r.holding_period)}</td>
                        <td>{number(r.num_trades_train)}</td>
                        <td
                          className={
                            Number(r.mean_return_train) > 0
                              ? "positive"
                              : "negative"
                          }
                        >
                          {pct(r.mean_return_train)}
                        </td>
                        <td>{number(r.num_trades_test)}</td>
                        <td
                          className={
                            Number(r.mean_return_test) > 0
                              ? "positive"
                              : "negative"
                          }
                        >
                          {pct(r.mean_return_test)}
                        </td>
                        <td>
                          {pct(r.ci95_lower_test)} 〜 {pct(r.ci95_upper_test)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Empty>最低件数を満たすTrain候補はありません。</Empty>
            )}
            <div className="csv-row section-gap">
              <a className="button" href={file("top_candidates_train.csv")}>
                全区分のTrain候補 ↓
              </a>
              <a className="button" href={file("candidate_test_results.csv")}>
                固定候補のTest評価 ↓
              </a>
            </div>
          </div>
          <Downloads id={j.id} />
        </>
      )}
      {tab === "heatmap" && (
        <>
          <div className="panel-head heatmap-heading">
            <h2>下落率 × 出来高倍率</h2>
            <span className="muted">
              {metrics[metricKey]} / {holding}営業日 / {market} /{" "}
              {period.toUpperCase()}
            </span>
          </div>
          <ErrorBox error={heat.error} />
          {heat.data ? (
            <div className="heatmap-grid">
              {caps
                .filter((group) => heatCaps.includes(group))
                .map((group) => (
                  <section
                    className="panel heatmap-panel"
                    key={group}
                    aria-label={(capLabels[group] || group) + "のヒートマップ"}
                  >
                    <div className="panel-head">
                      <h3>
                        <MarketCapLabel group={group} bins={bins} />
                      </h3>
                      {cap === group && (
                        <span className="muted">詳細表示中</span>
                      )}
                    </div>
                    <Heatmap
                      rows={visibleHeatRows.filter(
                        (r) => r.market_cap_group === group,
                      )}
                      config={j.config}
                      metricKey={metricKey}
                      scale={heatScale}
                      cell={cap === group ? cell : null}
                      onCell={(value) => {
                        setCap(group);
                        setCell(value);
                      }}
                    />
                  </section>
                ))}
            </div>
          ) : (
            <div className="panel">
              <Empty>集計を読み込み中…</Empty>
            </div>
          )}
          {row && (
            <section className="panel" aria-label="選択条件の詳細">
              <h2>
                条件詳細 · 下落率 ≥ {pct(cell.drawdown_threshold, false)} /
                出来高 ≥ {cell.volume_ratio_threshold}x / {holding}日
              </h2>
              <p className="detail-scope">
                <MarketCapLabel group={cap} bins={bins} /> · {market} ·{" "}
                {period.toUpperCase()}
              </p>
              <div className="detail-grid">
                <div className="mini-stats">
                  {[
                    "num_signals",
                    "num_trades",
                    "win_rate",
                    "mean_return",
                    "median_return",
                    "average_win",
                    "average_loss",
                    "max_profit",
                    "max_loss",
                    "profit_factor",
                    "expectancy",
                    "std_return",
                    "p25",
                    "p75",
                    "ci95_lower",
                    "ci95_upper",
                    "robustness_score",
                  ].map((key) => (
                    <div key={key}>
                      {metrics[key] ||
                        (
                          {
                            average_win: "平均利益",
                            average_loss: "平均損失",
                            max_profit: "最大利益",
                            max_loss: "最大損失",
                            std_return: "標準偏差",
                            p25: "P25",
                            p75: "P75",
                            ci95_upper: "95% CI 上限",
                          } as Record<string, string>
                        )[key]}
                      <strong>
                        {metric(row[key], key, row.profit_factor_infinite)}
                      </strong>
                    </div>
                  ))}
                </div>
                <Histogram
                  path={"backtests/" + j.id + "/distribution?" + selected}
                />
              </div>
              {row.insufficient_sample && (
                <p className="check-note">
                  * 最低件数未満です。候補選択から除外しています。
                </p>
              )}
            </section>
          )}
          <Trades
            id={j.id}
            bins={bins}
            filters={{ ...filters, ...cell }}
            compact
          />
        </>
      )}
      {["cap", "market"].includes(tab) && (
        <div className="panel">
          <h2>{tab === "cap" ? "時価総額別" : "市場別"}の比較</h2>
          <ParameterPicker config={j.config} cell={cell} setCell={setCell} />
          <ErrorBox error={comparison.error} />
          {comparison.data ? (
            <ResultTable
              bins={bins}
              rows={comparison.data.items}
              onSelect={(r) => {
                setCap(r.market_cap_group);
                setHeatCaps([r.market_cap_group]);
                setMarket(r.market_segment);
                setCell({
                  drawdown_threshold: r.drawdown_threshold,
                  volume_ratio_threshold: r.volume_ratio_threshold,
                });
                changeTab("heatmap");
              }}
            />
          ) : (
            <Empty>比較結果を読み込み中…</Empty>
          )}
          <p className="check-note">
            同一条件・同一保有期間の比較です。ALLは欠損時価総額のSignalも含みます。
          </p>
          <Downloads id={j.id} />
        </div>
      )}
      {tab === "ranking" && (
        <div className="panel">
          <div className="panel-head">
            <h2>パラメータ比較 · {period.toUpperCase()}</h2>
            <div className="toolbar">
              <label>
                並び順
                <select
                  aria-label="並び順"
                  value={sort}
                  onChange={(e) => {
                    setSort(e.target.value);
                    setOffset(0);
                  }}
                >
                  {Object.entries(metrics).map(([key, label]) => (
                    <option key={key} value={key}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <button
                onClick={() => {
                  setDescending((v) => !v);
                  setOffset(0);
                }}
              >
                {descending ? "高い順 ↓" : "低い順 ↑"}
              </button>
            </div>
          </div>
          <p className="muted">
            全選択保有期間を比較。DDボタンをクリックするとセル詳細が開きます。
          </p>
          <ErrorBox error={ranking.error} />
          {ranking.data ? (
            <ResultTable
              bins={bins}
              rows={ranking.data.items}
              offset={offset}
              onSelect={(r) => {
                setHolding(r.holding_period);
                setCap(r.market_cap_group);
                setHeatCaps([r.market_cap_group]);
                setCell({
                  drawdown_threshold: r.drawdown_threshold,
                  volume_ratio_threshold: r.volume_ratio_threshold,
                });
                changeTab("heatmap");
              }}
            />
          ) : (
            <Empty>ランキングを読み込み中…</Empty>
          )}
          <div className="pagination">
            <button disabled={!offset} onClick={() => setOffset(offset - 100)}>
              前へ
            </button>
            <span>
              {Math.min(offset + 100, ranking.data?.total || 0)} /{" "}
              {ranking.data?.total || 0}
            </span>
            <button
              disabled={offset + 100 >= (ranking.data?.total || 0)}
              onClick={() => setOffset(offset + 100)}
            >
              次へ
            </button>
          </div>
          <Downloads id={j.id} />
        </div>
      )}
      {tab === "trades" && (
        <>
          <div className="panel">
            <ParameterPicker config={j.config} cell={cell} setCell={setCell} />
          </div>
          <Trades id={j.id} bins={bins} filters={{ ...filters, ...cell }} />
        </>
      )}
      <Notice />
    </>
  );
}
function Downloads({ id }: { id: string }) {
  return (
    <div className="csv-row section-gap">
      {[
        ["parameter_results.csv", "全パラメータ結果"],
        ["market_cap_comparison.csv", "時価総額比較"],
        ["market_segment_comparison.csv", "市場別比較"],
      ].map(([name, label]) => (
        <a
          key={name}
          className="button"
          href={"/api/backtests/" + id + "/files/" + name}
        >
          {label} CSV ↓
        </a>
      ))}
    </div>
  );
}
function ParameterPicker({
  config,
  cell,
  setCell,
}: {
  config: Job["config"];
  cell: Cell;
  setCell: (c: Cell) => void;
}) {
  return (
    <div className="toolbar">
      <label>
        下落率
        <select
          aria-label="下落率"
          value={cell.drawdown_threshold}
          onChange={(e) =>
            setCell({ ...cell, drawdown_threshold: Number(e.target.value) })
          }
        >
          {config.drawdown_thresholds.map((d) => (
            <option value={d} key={d}>
              {pct(d, false)}
            </option>
          ))}
        </select>
      </label>
      <label>
        出来高倍率
        <select
          aria-label="出来高倍率"
          value={cell.volume_ratio_threshold}
          onChange={(e) =>
            setCell({ ...cell, volume_ratio_threshold: Number(e.target.value) })
          }
        >
          {config.volume_ratio_thresholds.map((v) => (
            <option value={v} key={v}>
              {v}x
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
function ResultTable({
  bins,
  rows,
  onSelect,
  offset = 0,
}: {
  bins: MarketCapBin[];
  rows: Result[];
  onSelect: (r: Result) => void;
  offset?: number;
}) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {[
              "順位",
              "DD",
              "VR",
              "保有日",
              "規模",
              "市場",
              "Signal",
              "Trades",
              "平均",
              "中央値",
              "勝率",
              "PF",
              "Expectancy",
              "95% CI",
              "Robustness",
            ].map((x) => (
              <th key={x}>{x}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td>{offset + i + 1}</td>
              <td>
                <button className="text-button" onClick={() => onSelect(r)}>
                  {pct(r.drawdown_threshold, false)}
                </button>
              </td>
              <td>{r.volume_ratio_threshold}x</td>
              <td>{r.holding_period}</td>
              <td>
                <MarketCapLabel group={r.market_cap_group} bins={bins} />
              </td>
              <td>{r.market_segment}</td>
              <td>{number(r.num_signals)}</td>
              <td>
                {number(r.num_trades)}
                {r.insufficient_sample ? " *" : ""}
              </td>
              <td
                className={Number(r.mean_return) > 0 ? "positive" : "negative"}
              >
                {pct(r.mean_return)}
              </td>
              <td>{pct(r.median_return)}</td>
              <td>{pct(r.win_rate, false)}</td>
              <td>
                {metric(
                  r.profit_factor,
                  "profit_factor",
                  r.profit_factor_infinite,
                )}
              </td>
              <td>{pct(r.expectancy)}</td>
              <td>
                {pct(r.ci95_lower)} 〜 {pct(r.ci95_upper)}
              </td>
              <td>{pct(r.robustness_score)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!rows.length && <Empty>該当する集計がありません。</Empty>}
    </div>
  );
}
function Heatmap({
  rows,
  config,
  metricKey,
  scale,
  cell,
  onCell,
}: {
  rows: Result[];
  config: Job["config"];
  metricKey: string;
  scale: number;
  cell: Cell | null;
  onCell: (c: Cell) => void;
}) {
  const sequential = ["num_trades", "win_rate"].includes(metricKey);
  function style(r: Result | undefined) {
    const value =
      r?.profit_factor_infinite && metricKey === "profit_factor"
        ? scale
        : r?.[metricKey];
    if (typeof value !== "number" || !Number.isFinite(value))
      return { background: "#f0f2f5", color: "#85909c" };
    const alpha = Math.min(1, Math.abs(value) / scale);
    return {
      background: sequential
        ? `rgba(38,120,132,${0.06 + alpha * 0.5})`
        : value >= 0
          ? `rgba(207,78,92,${0.07 + alpha * 0.6})`
          : `rgba(57,124,182,${0.07 + alpha * 0.6})`,
      color:
        alpha > 0.8
          ? "#fff"
          : sequential
            ? "#195a64"
            : value >= 0
              ? "#922c3d"
              : "#205d8a",
    };
  }
  return (
    <>
      <div className="heatmap-axis">出来高 / 過去20営業日の平均 →</div>
      <div className="table-wrap">
        <table className="heatmap">
          <thead>
            <tr>
              <th>下落率 ↓</th>
              {config.volume_ratio_thresholds.map((v) => (
                <th key={v}>{v}x</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {config.drawdown_thresholds.map((d) => (
              <tr key={d}>
                <td>−{Math.round(d * 100)}%</td>
                {config.volume_ratio_thresholds.map((v) => {
                  const r = rows.find(
                    (r) =>
                      r.drawdown_threshold === d &&
                      r.volume_ratio_threshold === v,
                  );
                  return (
                    <td key={v}>
                      <button
                        aria-label={
                          "下落率" + Math.round(d * 100) + "% 出来高" + v + "倍"
                        }
                        className={
                          cell?.drawdown_threshold === d &&
                          cell?.volume_ratio_threshold === v
                            ? "selected"
                            : ""
                        }
                        style={style(r)}
                        onClick={() =>
                          onCell({
                            drawdown_threshold: d,
                            volume_ratio_threshold: v,
                          })
                        }
                      >
                        <strong>
                          {metric(
                            r?.[metricKey],
                            metricKey,
                            r?.profit_factor_infinite,
                          )}
                        </strong>
                        <small>
                          {number(r?.num_trades)} trades
                          {r?.insufficient_sample ? " *" : ""}
                        </small>
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="legend">
        <span>{sequential ? "濃い色: 高い値" : "青: マイナス"}</span>
        <span>{sequential ? "薄い色: 低い値" : "赤: プラス"}</span>
        <span>* 最低件数未満</span>
        <span>セルを選択すると詳細を表示</span>
      </div>
    </>
  );
}
function Histogram({ path }: { path: string }) {
  const { data, error } = useApi<{
    count: number;
    bins: { start: number; end: number; count: number }[];
  }>(path);
  const max = Math.max(...(data?.bins || []).map((b) => b.count), 1);
  return (
    <div>
      <h3>リターン分布</h3>
      <ErrorBox error={error} />
      {data?.bins.length ? (
        <>
          <svg
            className="chart"
            viewBox="0 0 480 190"
            role="img"
            aria-label={"リターン分布 " + data.count + "取引"}
          >
            <title>リターン分布（件数）</title>
            <line x1="30" x2="470" y1="160" y2="160" stroke="#d8dfe5" />
            <text x="0" y="16" fill="#6b7787" fontSize="10">
              {max}
            </text>
            {data.bins.map((b, i) => (
              <g key={i}>
                <rect
                  x={32 + i * 21.7}
                  y={160 - (b.count / max) * 140}
                  width="18"
                  height={(b.count / max) * 140}
                  fill={(b.start + b.end) / 2 >= 0 ? "#c55d68" : "#548ebc"}
                >
                  <title>
                    {pct(b.start)}〜{pct(b.end)}: {b.count}件
                  </title>
                </rect>
              </g>
            ))}
            <text x="30" y="181" fill="#6b7787" fontSize="10">
              {pct(data.bins[0].start)}
            </text>
            <text x="470" y="181" textAnchor="end" fill="#6b7787" fontSize="10">
              {pct(data.bins[data.bins.length - 1].end)}
            </text>
          </svg>
          <p className="check-note">
            {number(data.count)}取引 /
            20ビン。極端なリターンが平均値へ与える影響を確認してください。
          </p>
        </>
      ) : (
        <Empty>{data ? "有効取引がありません。" : "分布を読み込み中…"}</Empty>
      )}
    </div>
  );
}
