export type Action = "BUY" | "HOLD" | "REDUCE" | "SELL" | "SKIP";

export interface ProposalLine {
  lineId: string;
  symbol: string;
  companyName: string;
  accountBucketId: string;
  currentShares: number;
  recommendedShares: number;
  shareDifference: number;
  action: Action;
  referencePrice: string;
  currentMarketValue: string;
  recommendedMarketValue: string;
  estimatedRequiredOrReleasedCash: string;
  holdExpectedValue: string;
  proposedExpectedValue: string;
  estimatedTransactionCost: string;
  estimatedTaxEffect: string;
  estimatedTaxCashWithholding?: string;
  netExpectedImprovement: string;
  downsideLevel: number;
  uncertaintyLevel: number;
  positiveReasons: string[];
  negativeReasons: string[];
}

export interface DailyProposal {
  proposalId: string;
  asOf: string;
  generatedAt: string;
  modelBundleVersion: string;
  decisionEngineVersion: string;
  status: string;
  isResearchOnly: boolean;
  isOrderInstruction: false;
  lines: ProposalLine[];
  estimatedSellValue: string;
  estimatedBuyValue: string;
  estimatedTransactionCost: string;
  estimatedTaxEffect: string;
  estimatedTaxCashWithholding?: string;
  estimatedCashAfter: Record<string, string>;
  changeCount: number;
  holdExpectedValue: string;
  proposedExpectedValue: string;
  netImprovement: string;
  noTradeReason: string | null;
}

export interface SavedAnalysis {
  analysisKind?: "latest_available_reference"; priceDate?: string;
  snapshotId: string; asOf: string; generatedAt: string; dataAsOf: string;
  modelVersion: string; readOnly: true; holdingSymbols: string[];
  predictions: { symbol: string; expected_return_5d: number | null;
    expected_return_20d: number | null; rank_score_20d?: number | null }[];
}

export interface TodayResponse {
  accountLabels?: Record<string,string>;
  savedAnalysis?: SavedAnalysis | null;
  businessDate: string;
  pipelineState: string;
  isStale: boolean;
  blockingReason: string | null;
  runtimeMode: string;
  proposal: DailyProposal | null;
}

export interface PortfolioSummary {
  asOf: string;
  totalAssets: string;
  cashValue: string;
  reservedCash?: string;
  buyingPower?: string;
  equityValue: string;
  holdingsCount: number;
}

export interface HoldingView {
  symbol: string;
  companyName: string;
  accountBucketId: string;
  shares: number;
  averageAcquisitionPrice: string;
  currentPrice: string;
  marketValue: string;
  unrealizedPnlAmount: string;
  latestAction: Action | null;
  recommendedShares: number | null;
  proposalId: string | null;
}

export interface HomeResponse {
  accountLabels?: Record<string,string>;
  initialLedger?: { confirmedAt: string; referencePriceDate: string | null } | null;
  runtimeMode: string;
  portfolio: PortfolioSummary | null;
  holdings: HoldingView[];
  blockingReason: string | null;
}

export interface DecisionReview {
  proposal_id: string;
  selected_targets: Record<string, number>;
  estimated_cash_after: Record<string, string>;
  estimated_buy_value: string;
  estimated_sell_value: string;
  estimated_transaction_cost: string;
  estimated_tax_effect: string;
  resulting_positions: number;
  constraint_violations: string[];
  is_order_instruction: false;
}

export interface RankingRow {
  ranking_id: string;
  as_of: string;
  symbol: string;
  company_name: string;
  rank_type: string;
  rank: number;
  total_universe: number;
  candidate_status: string;
  portfolio_action: Action | null;
  model_bundle_version: string;
  data_snapshot_id: string;
  percentile: number;
}

export interface AppStatus {
  businessDate: string;
  marketState: string;
  pipelineState: string;
  dataAsOf: string | null;
  morningDataAsOf: string | null;
  proposalGeneratedAt: string | null;
  portfolioUpdatedAt: string | null;
  modelBundleVersion: string | null;
  isStale: boolean;
  blockingReason: string | null;
  orderSubmissionAvailable: false;
  runtimeMode: string;
}

export interface PaperSummary {
  observations: number;
  proposal_return: number | null;
  benchmark_return: number | null;
  excess_return: number | null;
  maximum_drawdown: number | null;
  mean_cost_error: string | null;
  mean_tax_error: string | null;
  champion_mean_absolute_error: number | null;
  challenger_mean_absolute_error: number | null;
  challenger_better_rate: number | null;
  champion_version: string | null;
  champion_observations: number;
  challenger_version: string | null;
  challenger_observations: number;
  drift_status: "INSUFFICIENT_OBSERVATIONS" | "STABLE" | "DEGRADED";
  drift_ratio: number | null;
  drift_window: number;
  minimum_observation_count: number;
  is_decision_ready: boolean;
  model_monitoring_ready: boolean;
  updated_at: string | null;
  horizon_sessions: 1;
  series: PaperSeriesPoint[];
  weekly_readouts: PaperReadout[];
  monthly_readouts: PaperReadout[];
}

export interface PaperSeriesPoint {
  observed_at: string;
  observations: number;
  proposal_return: number;
  benchmark_return: number;
  excess_return: number;
}

export interface PaperReadout {
  period: "weekly" | "monthly";
  period_key: string;
  period_start: string;
  period_end: string;
  observations: number;
  proposal_return: number;
  benchmark_return: number;
  excess_return: number;
  mean_cost_error: string | null;
  mean_tax_error: string | null;
  champion_mean_absolute_error: number;
  challenger_mean_absolute_error: number | null;
  challenger_better_rate: number | null;
  champion_versions: string[];
  challenger_versions: string[];
  updated_at: string;
}

export interface StockDetail {
  accountLabels?: Record<string,string>;
  symbol: string;
  positions: Array<{
    symbol: string;
    account_bucket_id: string;
    shares: number;
    average_acquisition_price: string;
    market_price: string;
  }>;
  proposalLines: ProposalLine[];
  proposal: DailyProposal | null;
  forecast: {
    ranks?:{return5d:number|null;return20d:number|null;rank20d:number|null;total:number};
    snapshotId: string; asOf: string; generatedAt: string; isStale: boolean;
    mode: "research" | "paper" | "owner_approved"; blockingReasons: string[];
    labelDefinition?: string; labelDefinitionSupported?: boolean;
    prediction: { expected_return_5d: number | null; expected_return_20d: number | null; large_loss_probability: number | null;
      rank_score_5d?: number | null; rank_score_20d?: number | null };
    researchEligible: boolean;
  } | null;
  researchRuns: import("./mobile/chatgpt").ResearchRunView[];
  chatgptResearch: import("./mobile/chatgpt").ResearchRecord[];
}
