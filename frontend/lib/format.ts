import type { MarketCapBin } from "./types";

export function marketCapRange(group: string, bins: MarketCapBin[]): string {
  if (group === "ALL") return "全規模（欠損を含む）";
  if (group === "missing") return "当時の時価総額が不明";
  const bin = bins.find((b) => b.name === group);
  if (!bin) return "区分の定義なし";
  const bound = (v: number) =>
    v >= 1e12 ? number(v / 1e12, 6) + "兆円" : number(v / 1e8, 6) + "億円";
  if (bin.min === 0 && bin.max !== null) return bound(bin.max) + "未満";
  if (bin.max === null) return bound(bin.min) + "以上";
  return bound(bin.min) + "以上〜" + bound(bin.max) + "未満";
}

export function pct(value: unknown, signed = true): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return (signed && value > 0 ? "+" : "") + (value * 100).toFixed(2) + "%";
}
export function number(value: unknown, digits = 0): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString("ja-JP", { maximumFractionDigits: digits })
    : "—";
}
export function cap(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return value >= 1e12
    ? (value / 1e12).toFixed(2) + "兆円"
    : number(value / 1e8, 0) + "億円";
}
export function dateTime(value: string | null): string {
  return value
    ? new Date(value).toLocaleString("ja-JP", {
        timeZone: "Asia/Tokyo",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";
}
export const capLabels: Record<string, string> = {
  ALL: "ALL",
  micro: "Micro",
  small: "Small",
  small_mid: "Small-Mid",
  mid: "Mid",
  large: "Large",
  mega: "Mega",
  missing: "欠損",
};
export const statusLabels: Record<string, string> = {
  queued: "待機中",
  downloading: "データ取得中",
  preprocessing: "指標計算中",
  backtesting: "バックテスト中",
  analyzing: "集計・保存中",
  completed: "完了",
  failed: "失敗",
};
export const metrics: Record<string, string> = {
  mean_return: "平均リターン",
  median_return: "中央値",
  win_rate: "勝率",
  profit_factor: "Profit Factor",
  expectancy: "Expectancy",
  num_trades: "取引数",
  num_signals: "Signal数",
  ci95_lower: "95% CI 下限",
  robustness_score: "Robustness",
};
export function metric(value: unknown, key: string, infinite = false): string {
  if (key === "profit_factor") return infinite ? "∞" : number(value, 2);
  if (key === "num_trades" || key === "num_signals") return number(value);
  return pct(value, key !== "win_rate");
}
