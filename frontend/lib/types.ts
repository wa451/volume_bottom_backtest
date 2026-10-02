export type MarketCapBin = { name: string; min: number; max: number | null };
export type StrategyParameters = Record<
  string,
  number | string | boolean | number[] | string[]
>;
export type Config = {
  strategy_ids?: string[];
  strategy_params?: Record<string, StrategyParameters>;
  portfolio?: {
    initial_capital: number;
    max_positions: number;
    benchmark: string;
  };
  costs?: {
    buy_cost_rate: number;
    sell_cost_rate: number;
    slippage_rate: number;
  };
  start_date: string;
  end_date: string;
  train_start: string;
  train_end: string;
  test_start: string;
  test_end: string;
  drawdown_thresholds: number[];
  volume_ratio_thresholds: number[];
  holding_periods: number[];
  cooldown: number;
  markets: string[];
  market_cap_groups: string[];
  tickers: string[];
};
export type Metrics = Record<string, number | boolean | string | null>;
export type Result = Metrics & {
  period_type: string;
  market_cap_group: string;
  market_segment: string;
  drawdown_threshold: number;
  volume_ratio_threshold: number;
  holding_period: number;
  num_trades: number;
  num_signals: number;
  insufficient_sample: boolean;
  profit_factor_infinite: boolean;
};
export type Job = {
  id: string;
  job_id: string;
  kind: string;
  status: string;
  progress_percent: number;
  current_step: string;
  processed_items: number;
  total_items: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  attempts: number;
  config: Config;
  market_cap_bins: MarketCapBin[];
  summary: {
    analysis_mode?: string;
    warnings?: string[];
    benchmark_available?: boolean;
    benchmark_ticker?: string;
    quality?: Record<string, number | null>;
    parameter_combinations?: number;
    holding_periods?: number[];
    minimum_trades?: number;
    candidates?: Metrics[];
    full_note?: string;
    downloaded?: number;
    cached?: number;
    failed?: number;
    items?: { ticker: string; kind: string; status: string; error: string }[];
  };
  artifacts: string[];
};
export type Page<T> = {
  items: T[];
  total: number;
  offset: number;
  limit: number;
};
export type MarketItem = {
  code: string;
  ticker: string;
  company_name: string;
  market_segment: string;
  price_valid?: boolean;
  shares_valid?: boolean;
  latest_date?: string;
  price_rows?: number;
  shares_rows?: number;
  earnings_rows?: number;
  fundamentals_rows?: number;
  earnings_error?: string;
  fundamentals_error?: string;
  price_error?: string;
  shares_error?: string;
  download_mode?: string;
};
export type Market = {
  stock_count: number;
  price_success_count: number;
  price_missing_count: number;
  failure_count: number;
  shares_success_count: number;
  shares_coverage: number | null;
  latest_date: string | null;
  split_events: number;
  last_backtest_market_cap_coverage: number | null;
  last_backtest_stock_count: number | null;
  last_backtest_id: string | null;
  checked_at: string | null;
  source: { as_of?: string; last_refresh_error?: string };
  items: MarketItem[];
};
