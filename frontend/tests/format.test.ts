import { describe, it, expect } from "vitest";
import { pct, number, cap, metric, dateTime } from "../lib/format";
describe("金融数値と欠損の表示", () => {
  it("日本株のリターンを符号付きで表示", () => {
    expect(pct(0.0852)).toBe("+8.52%");
    expect(pct(-0.0341)).toBe("-3.41%");
    expect(pct(0.612, false)).toBe("61.20%");
  });
  it("欠損を0と混同しない", () => {
    expect(pct(null)).toBe("—");
    expect(number(NaN)).toBe("—");
    expect(pct(0)).toBe("0.00%");
  });
  it("時価総額とPFを表示", () => {
    expect(cap(325e8)).toBe("325億円");
    expect(cap(1.24e12)).toBe("1.24兆円");
    expect(metric(null, "profit_factor", true)).toBe("∞");
    expect(metric(125, "num_trades")).toBe("125");
  });
  it("UTCを東京時間で表示", () => {
    expect(dateTime("2023-06-01T13:15:00Z")).toContain("22:15");
  });
});
