import type { Config, StrategyParameters } from "./types";
export const strategyNames: Record<string, string> = {
  bottom_volume: "Bottom + Volume",
  kenmo_breakout: "Kenmo Breakout",
  kenmo_earnings: "Kenmo Earnings Momentum",
  kenmo_growth: "Kenmo Growth",
};
export function isPortfolio(c: Config) {
  const ids = c.strategy_ids || ["bottom_volume"];
  return ids.length !== 1 || ids[0] !== "bottom_volume";
}
export function combinationCount(
  c: Config,
  defaults: Record<string, StrategyParameters>,
) {
  return (c.strategy_ids || ["bottom_volume"]).reduce((total, id) => {
    if (id === "bottom_volume")
      return (
        total +
        c.drawdown_thresholds.length *
          c.volume_ratio_thresholds.length *
          c.holding_periods.length
      );
    const p = { ...defaults[id], ...c.strategy_params?.[id] };
    const count = (key: string) => (p[key] as unknown[])?.length || 0;
    let n = count("stop_loss");
    if (id === "kenmo_breakout" && p.high_enabled) n *= count("high_period");
    if (id !== "kenmo_growth" && p.volume_enabled) n *= count("volume_ratio");
    if (id === "kenmo_earnings")
      n *= count("entry_offset") * count("reaction_rate");
    if (p.mode === "fundamentals") {
      for (const [key, enabled] of [
        ["revenue_growth", "revenue_enabled"],
        ["earnings_growth", "earnings_enabled"],
        ["roe", "roe_enabled"],
        ["per_max", "per_enabled"],
      ])
        if (p[enabled]) n *= count(key);
    }
    const exitKeys: Record<string, string> = {
      fixed: "take_profit",
      holding: "holding_period",
      trailing: "trailing_stop",
      ma: "ma_period",
    };
    const exits = (p.exit_modes as string[]).reduce(
      (sum, mode) => sum + count(exitKeys[mode]),
      0,
    );
    return total + n * exits;
  }, 0);
}
