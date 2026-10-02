import type { StrategyParameters } from "./types";
export type EvidenceMetrics = Record<string, number | boolean | null>;
export type EvidenceCandidate = {
  strategy_id: string;
  strategy_name: string;
  parameter_id: string;
  parameters: StrategyParameters;
  market_cap_group: string;
  market_cap_range: string;
  market_segment: string;
  train: EvidenceMetrics;
  test: EvidenceMetrics | null;
  score: number | null;
  eligible: boolean;
  blockers: string[];
};
export type AnalysisReport = {
  version: string;
  generated_at: string;
  mode: "portfolio" | "event_study";
  status: "insufficient" | "unconfirmed" | "supported";
  minimum_trades: number;
  conclusion: string;
  reasons: string[];
  risks: string[];
  next_steps: string[];
  methodology: string;
  reference: EvidenceCandidate | null;
  selected: EvidenceCandidate | null;
  comparison: EvidenceCandidate[];
  strategy_comparison: EvidenceCandidate[];
  cap_comparison: EvidenceCandidate[];
  periods: Record<"train" | "test", { start: string; end: string }>;
  costs: Record<string, number>;
  generation: { provider: string; label: string; model?: string };
  ai_commentary?: {
    interpretation: string[];
    caveats: string[];
    next_steps: string[];
  };
};
export type AnalysisState = {
  status: string;
  job_id?: string;
  error_message?: string;
  progress_percent?: number;
  report: AnalysisReport | null;
};
