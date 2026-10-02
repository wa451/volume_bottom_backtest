import { describe, it, expect } from "vitest";
import { combinationCount, isPortfolio } from "../lib/strategy";
import type { Config, StrategyParameters } from "../lib/types";
const c = {
  drawdown_thresholds: [0.2, 0.3],
  volume_ratio_thresholds: [1.5, 2],
  holding_periods: [20, 60],
} as Config;
const d: Record<string, StrategyParameters> = {
  kenmo_breakout: {
    mode: "price_only",
    high_enabled: true,
    volume_enabled: true,
    revenue_enabled: true,
    earnings_enabled: true,
    roe_enabled: true,
    per_enabled: true,
    high_period: [120, 252],
    volume_ratio: [1, 1.5, 2],
    revenue_growth: [0.05, 0.1, 0.2],
    earnings_growth: [0.1, 0.2, 0.3],
    roe: [0.1],
    per_max: [40],
    stop_loss: [0.08],
    exit_modes: ["holding", "trailing"],
    holding_period: [20, 60],
    trailing_stop: [0.1, 0.2],
  },
};
describe("戦略の探索件数と既存互換", () => {
  it("旧設定は単独Bottomとして扱う", () => {
    expect(isPortfolio(c)).toBe(false);
    expect(combinationCount(c, d)).toBe(8);
  });
  it("価格版では財務の候補数を掛けない", () => {
    const v = { ...c, strategy_ids: ["kenmo_breakout"] };
    expect(isPortfolio(v)).toBe(true);
    expect(combinationCount(v, d)).toBe(24);
  });
  it("複数戦略と売却方式は合算、財務のONだけ探索", () => {
    const v = {
      ...c,
      strategy_ids: ["bottom_volume", "kenmo_breakout"],
      strategy_params: {
        kenmo_breakout: { mode: "fundamentals", revenue_enabled: false },
      },
    };
    expect(combinationCount(v, d)).toBe(80);
  });
});
