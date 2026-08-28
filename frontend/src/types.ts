export interface UploadResponse {
  batch_id: string;
  bank_count: number;
  processor_count: number;
  erp_count: number;
  has_answer_key: boolean;
}

export interface StageBreakdown {
  exact: number;
  fee_aware: number;
  many_to_one: number;
  one_to_many: number;
  fuzzy: number;
  semantic: number;
  refund: number;
  llm: number;
  unresolved: number;
}

export interface AccuracyStage {
  stage: string;
  precision: number | null;
  recall: number | null;
  n_predicted: number;
  n_expected: number;
}

export interface CalibrationBucket {
  bucket: string;
  n: number;
  accuracy: number | null;
}

export interface AccuracyReport {
  available: boolean;
  overall_precision: number | null;
  overall_recall: number | null;
  overall_f1: number | null;
  false_match_rate: number | null;
  missed_match_rate: number | null;
  per_stage: AccuracyStage[];
  calibration: CalibrationBucket[];
}

export interface ReconcileResponse {
  batch_id: string;
  total_records: number;
  match_rate: number;
  stage_breakdown: StageBreakdown;
  exception_count: number;
  manual_review_reduction: number;
  llm_call_count: number;
  llm_batched_call_count: number;
  failover_count: number;
  throughput_per_sec: number;
  processing_ms: number;
  settlement_variance: number | null;
  accuracy: AccuracyReport;
  validation_status?: string | null;
  control_totals?: Record<string, number> | null;
  pipeline_version?: string | null;
  rule_set_version?: string | null;
  normalization_version?: string | null;
  audit_completeness?: number | null;
  invalid_count?: number;
  reused_existing_run?: boolean;
}

export interface CandidateRow {
  transaction_id?: string;
  payment_id?: string;
  bank_txn?: string;
  amount?: number;
  net_amount?: number;
  date?: string | null;
  counterparty?: string;
  reference?: string | null;
  score?: number;
  stage?: string;
}

export type ExceptionType =
  | "duplicate"
  | "missing_counterpart"
  | "amount_mismatch"
  | "timing_difference"
  | "ambiguous"
  | "unidentified_cash"
  | "refund_missing_from_bank"
  | "duplicate_refund"
  | "partially_paid"
  | "overpaid"
  | "invalid"
  | "currency_mismatch"
  | null;

export type SourceName = "bank" | "processor" | "erp" | null;

export interface MatchOut {
  match_id: string;
  left_source: SourceName;
  left_txn_ids: string[];
  right_source: SourceName;
  right_txn_ids: string[];
  match_stage:
    | "exact"
    | "fee_aware"
    | "many_to_one"
    | "one_to_many"
    | "fuzzy"
    | "semantic"
    | "refund"
    | "llm"
    | "unresolved";
  confidence: number;
  reason: string;
  candidates_shown: CandidateRow[] | null;
  provider_used: "groq" | "gemini" | "heuristic" | null;
  status: "matched" | "exception";
  exception_type: ExceptionType;
  severity: "low" | "medium" | "high" | null;
  review_status: "open" | "resolved" | "rejected";
  decision?: string | null;
  state?: string | null;
  decision_stage?: string | null;
  rule_id?: string | null;
  evidence?: Record<string, unknown> | null;
  contradictions?: unknown;
  candidate_ids?: string[] | null;
  exception_category?: string | null;
  exception_lifecycle?: string | null;
  relationship_type?: string | null;
  top_score?: number | null;
  second_score?: number | null;
  score_margin?: number | null;
  ai_used?: boolean | null;
  pipeline_version?: string | null;
}

export interface ResultsResponse {
  batch_id: string;
  matches: MatchOut[];
}

export interface BatchSummary {
  batch_id: string;
  status: string;
  bank_count: number;
  processor_count: number;
  erp_count: number;
  has_answer_key: boolean;
  match_rate: number | null;
  manual_review_reduction: number | null;
  stage_breakdown: StageBreakdown | null;
  llm_call_count: number;
  llm_batched_call_count: number;
  failover_count: number;
  processing_ms: number | null;
  throughput_per_sec: number | null;
  settlement_variance: number | null;
  validation_status?: string | null;
  control_totals?: Record<string, number> | null;
  pipeline_version?: string | null;
  normalization_version?: string | null;
  rule_set_version?: string | null;
  configuration_version?: string | null;
  audit_completeness?: number | null;
  invalid_count?: number | null;
}

export interface GraphNode {
  id: string;
  source: string;
  label: string;
  amount: number | null;
  kind: "order" | "payment" | "settlement" | "bank" | "erp";
}

export interface GraphEdge {
  source_id: string;
  target_id: string;
  label: string;
}

export interface EventChain {
  chain_id: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  status: "complete" | "partial";
}

export interface GraphResponse {
  batch_id: string;
  chains: EventChain[];
}

export interface QAResponse {
  question: string;
  answer: string;
  data: unknown;
}

export interface ResolutionHistoryEntry {
  id: number;
  action: string;
  previous_lifecycle: string | null;
  new_lifecycle: string | null;
  note: string | null;
  resolved_by: string | null;
  created_at: string | null;
}

export interface ResolutionHistoryResponse {
  match_id: string;
  current_review_status: string;
  current_exception_lifecycle: string | null;
  history: ResolutionHistoryEntry[];
}

export interface AuditRecord {
  batch_id: string;
  match_id: string;
  transaction_id: string | null;
  matched_transaction_id: string | null;
  left_txn_ids: string[];
  right_txn_ids: string[];
  decision: string | null;
  state: string | null;
  decision_stage: string | null;
  rule_id: string | null;
  rule_set_version: string | null;
  score: number | null;
  confidence: number | null;
  candidate_ids: string[] | null;
  evidence: Record<string, unknown> | null;
  contradictions: unknown;
  AI_used: boolean | null;
  AI_provider: string | null;
  AI_model: string | null;
  pipeline_version: string | null;
  normalization_version: string | null;
  timestamp: string | null;
  reason: string | null;
  exception_category: string | null;
  top_score: number | null;
  second_score: number | null;
  score_margin: number | null;
}

export interface AuditResponse {
  batch_id: string;
  count: number;
  audit_completeness: number;
  records: AuditRecord[];
}

export interface MemoryAuditEvent {
  id: string;
  event_type: string;
  match_id: string | null;
  batch_id: string | null;
  reviewer: string | null;
  details: Record<string, unknown> | null;
  created_at: string | null;
}

// --- Forward Cash Forecaster (README §41) ---

export type ForecastBucket = "CONFIRMED" | "EXPECTED" | "AT_RISK" | "UNCLASSIFIABLE";

export interface ForecastCurvePoint {
  date: string;
  confirmed: number;
  expected: number;
  at_risk: number;
  running_balance?: number;
}

export interface ForecastTotals {
  confirmed: number;
  expected: number;
  at_risk: number;
  unclassifiable: number;
}

export interface ForecastLineSummary {
  line_id: string;
  category: ForecastBucket;
  direction: "inflow" | "outflow" | null;
  amount: number;
  currency: string | null;
  bucket_date: string | null;
  confidence: "high" | "medium" | "low" | null;
  lag_source: "observed" | "default" | "ai_estimated" | null;
  exception_type?: string | null;
  reason?: string | null;
}

export interface CashForecastResponse {
  batch_id: string;
  run_id: string;
  as_of_date: string;
  horizon_days: number;
  opening_balance: number | null;
  forecast_version: string | null;
  lag_model_version: string | null;
  forecast_llm_call_count: number;
  forecast_failover_count: number;
  curve: ForecastCurvePoint[];
  totals: ForecastTotals;
  line_count: number;
  lines?: ForecastLineSummary[];
}

export interface ForecastLine {
  line_id: string;
  run_id: string;
  batch_id: string;
  bucket_date: string | null;
  category: ForecastBucket;
  direction: "inflow" | "outflow" | null;
  amount: number;
  currency: string | null;
  confidence: "high" | "medium" | "low" | null;
  lag_source: "observed" | "default" | "ai_estimated" | null;
  source_match_ids: string[];
  evidence: Record<string, unknown>;
  ai_used: boolean;
}

// --- Reconciliation memory (README §7) & exception → rule learning (§8) ---

export interface MemoryMapping {
  id: string;
  mapping_kind: "counterparty" | "reference" | string;
  raw_value: string;
  canonical_value: string;
  approval_count: number;
  status: string;
  rule_source: string | null;
  origin_match_id: string | null;
  origin_batch_id: string | null;
  exception_type: string | null;
  first_approved_at: string | null;
  last_approved_at: string | null;
  last_batch_id: string | null;
  source_transaction_id: string | null;
  target_transaction_id: string | null;
  source_record_id: string | null;
  target_record_id: string | null;
  source_amount: number | null;
  target_amount: number | null;
  reviewer: string | null;
}

export interface LearnedRule {
  rule_id: string;
  name: string;
  kind: string;
  version: number;
  approval_status: string;
  times_approved: number;
  origin_match_id: string | null;
  origin_batch_id: string | null;
  exception_type: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface MemoryResponse {
  batch_id: string;
  mappings: MemoryMapping[];
  rules: LearnedRule[];
  totals: {
    mappings: number;
    rules: number;
    approvals: number;
    from_this_batch: number;
  };
}

// --- Data quality layer (README §15) ---

export interface DataQualityRecord {
  transaction_id: string;
  source: string | null;
  source_record_id: string | null;
  transaction_type: string | null;
  amount: number | null;
  currency: string | null;
  reference: string | null;
  transaction_date: string | null;
  validation_errors: string[];
}

export interface DataQualityResponse {
  batch_id: string;
  invalid_count: number;
  records: DataQualityRecord[];
}

// --- Matching contract (README §12: real configured tolerances only) ---

export interface MatchingContract {
  version?: string;
  matching?: {
    amount_tolerance?: number | null;
    timing_tolerance_days?: number | null;
    min_candidate_margin?: number | null;
    [key: string]: unknown;
  };
}
