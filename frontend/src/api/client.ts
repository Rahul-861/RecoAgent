import type {
  UploadResponse,
  ReconcileResponse,
  ResultsResponse,
  AccuracyReport,
  BatchSummary,
  GraphResponse,
  QAResponse,
  AuditResponse,
  ResolutionHistoryResponse,
  CashForecastResponse,
  ForecastLine,
  MemoryResponse,
  MemoryAuditEvent,
  DataQualityResponse,
  MatchingContract,
} from "../types";

const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      /* ignore parse failure */
    }
    throw new Error(detail);
  }
  return res.json();
}

export async function uploadBatch(
  bankFile: File,
  processorFile: File,
  erpFile: File,
  answerKey: File | null
): Promise<UploadResponse> {
  const form = new FormData();
  form.append("bank_file", bankFile);
  form.append("processor_file", processorFile);
  form.append("erp_file", erpFile);
  if (answerKey) form.append("answer_key_file", answerKey);

  const res = await fetch(`${BASE_URL}/api/upload`, { method: "POST", body: form });
  return handle<UploadResponse>(res);
}

export async function runReconciliation(batchId: string): Promise<ReconcileResponse> {
  const res = await fetch(`${BASE_URL}/api/reconcile/${batchId}`, { method: "POST" });
  return handle<ReconcileResponse>(res);
}

export async function getResults(batchId: string): Promise<ResultsResponse> {
  const res = await fetch(`${BASE_URL}/api/results/${batchId}`);
  return handle<ResultsResponse>(res);
}

export async function getExceptions(batchId: string): Promise<ResultsResponse> {
  const res = await fetch(`${BASE_URL}/api/exceptions/${batchId}`);
  return handle<ResultsResponse>(res);
}

export async function resolveException(
  matchId: string,
  action: "resolved" | "rejected" | "escalated" | "in_review",
  reviewer?: string,
  chosenCandidateId?: string
): Promise<{
  match_id: string;
  review_status: string;
  exception_lifecycle: string;
  resolution_note: string | null;
  learned_rule_ids: string[];
}> {
  const body: Record<string, unknown> = { action };
  if (reviewer) body.resolved_by = reviewer;
  if (chosenCandidateId) body.chosen_candidate_id = chosenCandidateId;
  const res = await fetch(`${BASE_URL}/api/exceptions/${matchId}/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handle(res);
}

export async function getAccuracy(batchId: string): Promise<AccuracyReport> {
  const res = await fetch(`${BASE_URL}/api/accuracy/${batchId}`);
  return handle<AccuracyReport>(res);
}

export async function getBatch(batchId: string): Promise<BatchSummary> {
  const res = await fetch(`${BASE_URL}/api/batch/${batchId}`);
  return handle<BatchSummary>(res);
}

export async function getAudit(batchId: string): Promise<AuditResponse> {
  const res = await fetch(`${BASE_URL}/api/audit/${batchId}`);
  return handle<AuditResponse>(res);
}

export async function getResolutionHistory(matchId: string): Promise<ResolutionHistoryResponse> {
  const res = await fetch(`${BASE_URL}/api/exceptions/${matchId}/history`);
  return handle<ResolutionHistoryResponse>(res);
}

export async function getGraph(batchId: string): Promise<GraphResponse> {
  const res = await fetch(`${BASE_URL}/api/graph/${batchId}`);
  return handle<GraphResponse>(res);
}

export async function askQuestion(batchId: string, question: string): Promise<QAResponse> {
  const res = await fetch(`${BASE_URL}/api/qa/${batchId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  return handle<QAResponse>(res);
}

export async function runForecast(
  batchId: string,
  opts?: { horizonDays?: number; openingBalance?: number; force?: boolean }
): Promise<CashForecastResponse> {
  const params = new URLSearchParams();
  if (opts?.horizonDays != null) params.set("horizon_days", String(opts.horizonDays));
  if (opts?.openingBalance != null) params.set("opening_balance", String(opts.openingBalance));
  if (opts?.force) params.set("force", "true");
  const qs = params.toString();
  const res = await fetch(`${BASE_URL}/api/forecast/${batchId}${qs ? `?${qs}` : ""}`, {
    method: "POST",
  });
  return handle<CashForecastResponse>(res);
}

export async function getForecast(batchId: string): Promise<CashForecastResponse> {
  const res = await fetch(`${BASE_URL}/api/forecast/${batchId}`);
  return handle<CashForecastResponse>(res);
}

export async function getForecastLine(batchId: string, lineId: string): Promise<ForecastLine> {
  const res = await fetch(`${BASE_URL}/api/forecast/${batchId}/line/${lineId}`);
  return handle<ForecastLine>(res);
}

export async function getMemory(batchId: string): Promise<MemoryResponse> {
  const res = await fetch(`${BASE_URL}/api/memory/${batchId}`);
  return handle<MemoryResponse>(res);
}

export async function getMemoryAudit(batchId: string): Promise<MemoryAuditEvent[]> {
  const res = await fetch(`${BASE_URL}/api/memory/${batchId}/audit`);
  return handle<MemoryAuditEvent[]>(res);
}

export async function getDataQuality(batchId: string): Promise<DataQualityResponse> {
  const res = await fetch(`${BASE_URL}/api/data-quality/${batchId}`);
  return handle<DataQualityResponse>(res);
}

let contractCache: Promise<MatchingContract> | null = null;

/**
 * Configured matching tolerances (README §12) — used for counterfactual
 * explanations so no threshold is ever invented in the UI. Fetched once and
 * cached; a failure resolves to an empty contract and callers omit the
 * affected section instead of guessing values.
 */
export function getContract(): Promise<MatchingContract> {
  if (!contractCache) {
    contractCache = fetch(`${BASE_URL}/api/contract`)
      .then((res) => handle<MatchingContract>(res))
      .catch(() => ({}) as MatchingContract);
  }
  return contractCache;
}
