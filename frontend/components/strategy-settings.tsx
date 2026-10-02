"use client";
import type { Config, StrategyParameters } from "@/lib/types";
import { combinationCount, strategyNames, isPortfolio } from "@/lib/strategy";

export default function StrategySettings({
  config: c,
  defaults,
  onChange,
}: {
  config: Config;
  defaults: Record<string, StrategyParameters>;
  onChange: (v: Config) => void;
}) {
  const ids = c.strategy_ids || ["bottom_volume"];
  const change = (id: string, key: string, value: StrategyParameters[string]) =>
    onChange({
      ...c,
      strategy_params: {
        ...c.strategy_params,
        [id]: { ...defaults[id], ...c.strategy_params?.[id], [key]: value },
      },
    });
  const count = combinationCount(c, defaults);
  const portfolio = c.portfolio || {
    initial_capital: 1000000,
    max_positions: 5,
    benchmark: "^N225",
  };
  return (
    <div className="panel">
      <h2>Strategy　戦略選択・比較</h2>
      <div className="choices">
        {Object.entries(strategyNames).map(([id, name]) => (
          <label key={id}>
            <input
              type="checkbox"
              checked={ids.includes(id)}
              onChange={(e) =>
                onChange({
                  ...c,
                  strategy_ids: e.target.checked
                    ? [...ids, id]
                    : ids.filter((x) => x !== id),
                })
              }
            />
            {name}
          </label>
        ))}
      </div>
      <p className="check-note">
        複数戦略は同じ期間・銘柄で、資金配分を定義したポートフォリオとして比較します。Bottom単独は既存Event
        Studyです。kenmo氏本人の投資法・成果を完全再現するものではありません。
      </p>
      {ids
        .filter((id) => id !== "bottom_volume")
        .map((id) => {
          const p = { ...defaults[id], ...c.strategy_params?.[id] };
          const toggle = (key: string, label: string) => (
            <label>
              <input
                type="checkbox"
                checked={!!p[key]}
                onChange={(e) => change(id, key, e.target.checked)}
              />{" "}
              {label}
            </label>
          );
          const choices = (
            key: string,
            label: string,
            options: number[],
            percent = false,
          ) => (
            <div key={key}>
              <h3>{label}</h3>
              <div className="choices">
                {options.map((x) => (
                  <label key={x}>
                    <input
                      type="checkbox"
                      checked={(p[key] as number[]).includes(x)}
                      onChange={(e) =>
                        change(
                          id,
                          key,
                          e.target.checked
                            ? [...(p[key] as number[]), x]
                            : (p[key] as number[]).filter((v) => v !== x),
                        )
                      }
                    />
                    {percent ? Math.round(x * 100) + "%" : x}
                  </label>
                ))}
              </div>
            </div>
          );
          const numeric = (key: string, label: string, scale = 1) => (
            <label>
              {label}
              <input
                type="number"
                min="0"
                step="any"
                required
                value={Number(p[key]) / scale}
                onChange={(e) =>
                  change(id, key, Number(e.target.value) * scale)
                }
              />
            </label>
          );
          return (
            <section key={id} className="strategy-section">
              <h3>{strategyNames[id]}</h3>
              <label>
                データ版
                <select
                  aria-label={strategyNames[id] + " データ版"}
                  value={String(p.mode)}
                  onChange={(e) => change(id, "mode", e.target.value)}
                >
                  <option value="price_only">Price-only（価格条件）</option>
                  <option value="fundamentals">
                    Fundamentals（取得時点以後の財務）
                  </option>
                </select>
              </label>
              {id === "kenmo_growth" && (
                <p className="check-note">
                  価格版は当時時価総額＋50日MA上の代理条件です。業績成長を確認した結果ではありません。
                </p>
              )}
              {id === "kenmo_breakout" && (
                <>
                  {toggle("high_enabled", "高値更新条件 ON")}
                  {!!p.high_enabled &&
                    choices(
                      "high_period",
                      "高値期間（営業日）",
                      [120, 180, 252],
                    )}
                </>
              )}
              {id !== "kenmo_growth" && (
                <>
                  {toggle("volume_enabled", "出来高条件 ON")}
                  {!!p.volume_enabled &&
                    choices(
                      "volume_ratio",
                      "出来高倍率（当日を除く20日平均）",
                      [1, 1.5, 2],
                    )}
                </>
              )}
              {id === "kenmo_earnings" && (
                <>
                  {choices(
                    "entry_offset",
                    "決算からエントリーまで（営業日）",
                    [1, 2, 3, 5],
                  )}
                  {choices(
                    "reaction_rate",
                    "決算後の株価反応",
                    [0.03, 0.05, 0.1],
                    true,
                  )}
                  <p className="check-note">
                    引け後・時刻不明は翌日の終値で反応を確認。翌日始値（1営業日後）には入れません。
                  </p>
                </>
              )}
              {id === "kenmo_growth" && (
                <div className="form-grid">
                  {numeric("cap_min", "時価総額下限（億円）", 1e8)}
                  {numeric("cap_max", "時価総額上限未満（億円）", 1e8)}
                </div>
              )}
              {p.mode === "fundamentals" && (
                <details>
                  <summary>財務フィルター（各条件ON / OFF）</summary>
                  <p className="check-note">
                    Yahoo財務表は過去の公表時点・改訂履歴を再現できません。取得完了時点以前は使わず、財務条件ONで観測がなければエントリーしません。
                  </p>
                  {toggle("revenue_enabled", "売上成長率 ON")}
                  {!!p.revenue_enabled &&
                    choices(
                      "revenue_growth",
                      "売上YoY",
                      [0.05, 0.1, 0.2],
                      true,
                    )}
                  {toggle("earnings_enabled", "EPS / 利益成長率 ON")}
                  {!!p.earnings_enabled &&
                    choices(
                      "earnings_growth",
                      "EPS / 利益YoY",
                      [0.1, 0.2, 0.3],
                      true,
                    )}
                  {toggle("roe_enabled", "ROE ON")}
                  {!!p.roe_enabled &&
                    choices("roe", "ROE", [0.08, 0.1, 0.15], true)}
                  {toggle("per_enabled", "PER ON")}
                  {!!p.per_enabled && (
                    <>
                      {numeric("per_min", "PER下限")}
                      {choices("per_max", "PER上限", [30, 40, 50])}
                    </>
                  )}
                </details>
              )}
              <details>
                <summary>売却・詳細設定</summary>
                {choices("stop_loss", "損切り", [0.05, 0.08, 0.1, 0.15], true)}
                <h3>売却方式（複数可）</h3>
                <div className="choices">
                  {Object.entries({
                    fixed: "固定利確",
                    holding: "保有期間",
                    trailing: "トレーリング",
                    ma: "MA割れ",
                  }).map(([key, label]) => (
                    <label key={key}>
                      <input
                        type="checkbox"
                        checked={(p.exit_modes as string[]).includes(key)}
                        onChange={(e) =>
                          change(
                            id,
                            "exit_modes",
                            e.target.checked
                              ? [...(p.exit_modes as string[]), key]
                              : (p.exit_modes as string[]).filter(
                                  (x) => x !== key,
                                ),
                          )
                        }
                      />
                      {label}
                    </label>
                  ))}
                </div>
                {(p.exit_modes as string[]).includes("fixed") &&
                  choices("take_profit", "利確率", [0.2, 0.3, 0.5, 1], true)}
                {(p.exit_modes as string[]).includes("holding") &&
                  choices(
                    "holding_period",
                    "保有期間（営業日）",
                    [20, 60, 120, 252],
                  )}
                {(p.exit_modes as string[]).includes("trailing") &&
                  choices(
                    "trailing_stop",
                    "最高値からの下落",
                    [0.1, 0.15, 0.2],
                    true,
                  )}
                {(p.exit_modes as string[]).includes("ma") &&
                  choices("ma_period", "移動平均（営業日）", [5, 20, 50])}
                {numeric(
                  "maximum_holding",
                  "固定利確・トレーリング・MAの最大保有日数",
                )}
                {id === "kenmo_growth" && (
                  <>
                    {toggle(
                      "listing_enabled",
                      "上場経過年数条件 ON（信頼できる上場日未取得時は取引なし）",
                    )}
                    {!!p.listing_enabled &&
                      numeric("listing_years", "上場からの最大年数")}
                  </>
                )}
              </details>
            </section>
          );
        })}
      <p aria-live="polite">
        評価の組み合わせ：{count} / 上限256
        {count === 0 || count > 256 ? " — 候補を調整してください" : ""}
      </p>
      <details>
        <summary>共通設定：手数料・資金配分</summary>
        <div className="form-grid">
          {(["buy_cost_rate", "sell_cost_rate", "slippage_rate"] as const).map(
            (key, i) => (
              <label key={key}>
                {["買付手数料（%）", "売却手数料（%）", "スリッページ（%）"][i]}
                <input
                  type="number"
                  step="0.1"
                  min="0"
                  max="5"
                  value={(c.costs?.[key] || 0) * 100}
                  onChange={(e) =>
                    onChange({
                      ...c,
                      costs: {
                        buy_cost_rate: 0,
                        sell_cost_rate: 0,
                        slippage_rate: 0,
                        ...c.costs,
                        [key]: Number(e.target.value) / 100,
                      },
                    })
                  }
                />
              </label>
            ),
          )}
          {isPortfolio(c) && (
            <>
              <label>
                初期資金（円）
                <input
                  type="number"
                  min="10000"
                  value={c.portfolio?.initial_capital || 1000000}
                  onChange={(e) =>
                    onChange({
                      ...c,
                      portfolio: {
                        ...portfolio,
                        initial_capital: Number(e.target.value),
                      },
                    })
                  }
                />
              </label>
              <label>
                最大同時保有数
                <input
                  type="number"
                  min="1"
                  max="50"
                  value={c.portfolio?.max_positions || 5}
                  onChange={(e) =>
                    onChange({
                      ...c,
                      portfolio: {
                        ...portfolio,
                        max_positions: Number(e.target.value),
                      },
                    })
                  }
                />
              </label>
              <label>
                ベンチマーク
                <select
                  value={c.portfolio?.benchmark || "^N225"}
                  onChange={(e) =>
                    onChange({
                      ...c,
                      portfolio: { ...portfolio, benchmark: e.target.value },
                    })
                  }
                >
                  <option value="^N225">日経平均</option>
                  <option value="^TOPX">TOPIX（未取得時は欠損）</option>
                </select>
              </label>
            </>
          )}
        </div>
      </details>
    </div>
  );
}
