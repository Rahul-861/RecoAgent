import type { CandidateRow, ExceptionType, MatchOut } from "../types";
import { formatMoney, sourceLabel } from "./format";

export type EvidenceStatus = "success" | "warning" | "danger" | "neutral";

export interface FormattedEvidenceRow {
  label: string;
  status: EvidenceStatus;
  value: string;
  detail?: string;
}

const RULE_NAMES: Record<string, string> = {
  R001: "Exact identity",
  R002: "Settlement batch",
  R003: "Fee-adjusted",
  R004: "Strong candidate",
  R005: "Currency conflict",
  R006: "Consumed candidate",
  R007: "Refund reconciliation",
  R008: "Invoice aggregation",
  R009: "AI adjudication",
};

const EXCEPTION_LABELS: Record<string, string> = {
  duplicate: "Duplicate candidates",
  missing_counterpart: "Missing counterpart",
  amount_mismatch: "Amount mismatch",
  timing_difference: "Timing difference",
  ambiguous: "Ambiguous",
  unidentified_cash: "Unidentified cash",
  refund_missing_from_bank: "Refund missing from bank",
  duplicate_refund: "Duplicate refund",
  partially_paid: "Partially paid invoice",
  overpaid: "Overpaid invoice",
  invalid: "Invalid record",
  currency_mismatch: "Currency mismatch",
};

const EVIDENCE_VALUE_LABELS: Record<string, { text: string; status: EvidenceStatus }> = {
  exact: { text: "Matched exactly", status: "success" },
  refund_equals_debit: { text: "Refund equals bank debit", status: "success" },
  exact_after_fee: { text: "Matched after documented fees", status: "success" },
  sum_equals_settlement: { text: "Sum equals settlement amount", status: "success" },
  sum_equals_invoice: { text: "Sum equals invoice amount", status: "success" },
  compatible: { text: "Compatible within tolerance", status: "success" },
  weak: { text: "Weak signal", status: "warning" },
  strong_match: { text: "Strongly matched", status: "success" },
  strong: { text: "Strong match", status: "success" },
  partial: { text: "Partial match", status: "warning" },
  fuzzy_match: { text: "Fuzzy name/description match", status: "success" },
  semantic_match: { text: "Semantic description match", status: "success" },
  within_window: { text: "Within allowed date window", status: "success" },
  within_1_day: { text: "Within 1 day", status: "success" },
  outside_window: { text: "Outside the date window", status: "warning" },
  ai_interpreted: { text: "Interpreted by AI from provided candidates", status: "neutral" },
};

const EVIDENCE_KEY_LABELS: Record<string, string> = {
  amount: "Amount",
  currency: "Currency",
  reference: "Reference",
  date: "Transaction date",
  counterparty: "Counterparty",
  matched: "Match result",
  stage: "Pipeline stage",
  note: "Note",
};

const CONTRADICTION_LABELS: Record<string, string> = {
  currency_mismatch: "Currency conflicts with the candidate",
  amount_mismatch: "Candidate amount differs beyond tolerance",
  reference_conflict: "Reference conflicts with the candidate",
};

export function ruleName(ruleId: string | null | undefined): string | null {
  if (!ruleId) return null;
  return RULE_NAMES[ruleId] || null;
}

export function formatRule(ruleId: string | null | undefined, stage?: string | null): string {
  if (!ruleId) return stage ? stage.replace(/_/g, " ") : "Evidence unavailable";
  const name = ruleName(ruleId);
  return name ? `${ruleId} · ${name}` : ruleId;
}

export function exceptionLabel(type: string | null | undefined): string {
  if (!type) return "Exception";
  return EXCEPTION_LABELS[type] || type.replace(/_/g, " ");
}

export function isAiUsed(match: {
  ai_used?: boolean | null;
  AI_used?: boolean | null;
  provider_used?: string | null;
  match_stage?: string | null;
}): boolean {
  if (match.ai_used === true || match.AI_used === true) return true;
  if (match.provider_used === "groq" || match.provider_used === "gemini") return true;
  return match.match_stage === "llm";
}

function humanizeToken(raw: string): string {
  return raw.replace(/_/g, " ");
}

export function formatEvidenceValue(key: string, raw: unknown): FormattedEvidenceRow {
  const label = EVIDENCE_KEY_LABELS[key] || humanizeToken(key);
  if (raw === null || raw === undefined || raw === "") {
    return { label, status: "neutral", value: "Evidence unavailable" };
  }
  if (typeof raw === "boolean") {
    return { label, status: raw ? "success" : "warning", value: raw ? "Yes" : "No" };
  }
  if (typeof raw === "number") {
    return { label, status: "neutral", value: String(raw) };
  }
  if (typeof raw === "object") {
    return { label, status: "neutral", value: "See technical evidence" };
  }
  const mapped = EVIDENCE_VALUE_LABELS[String(raw)];
  if (mapped) return { label, status: mapped.status, value: mapped.text };
  return { label, status: "neutral", value: humanizeToken(String(raw)) };
}

export function formatEvidence(evidence: unknown): FormattedEvidenceRow[] {
  if (evidence == null) return [];
  if (typeof evidence === "string") {
    return [{ label: "Evidence", status: "neutral", value: evidence }];
  }
  if (Array.isArray(evidence)) {
    return evidence.map((item, i) => formatEvidenceValue(`item_${i + 1}`, item));
  }
  if (typeof evidence !== "object") {
    return [{ label: "Evidence", status: "neutral", value: String(evidence) }];
  }
  const skip = new Set([
    "left_source",
    "right_source",
    "lag_median_days",
    "lag_sample_size",
    "direction_basis",
    "match_stage",
    "exception_lifecycle",
    "ai_range_days",
    "ai_fallback_reason",
  ]);
  const rows: FormattedEvidenceRow[] = [];
  for (const [key, value] of Object.entries(evidence as Record<string, unknown>)) {
    if (skip.has(key) || key.endsWith("_json")) continue;
    rows.push(formatEvidenceValue(key, value));
  }
  return rows.slice(0, 8);
}

export function formatContradictions(contradictions: unknown): string[] {
  if (contradictions == null) return [];
  const items = Array.isArray(contradictions) ? contradictions : [contradictions];
  return items
    .map((c) => {
      if (c == null) return "";
      if (typeof c === "string") return CONTRADICTION_LABELS[c] || humanizeToken(c);
      if (typeof c === "object") {
        const obj = c as Record<string, unknown>;
        if (typeof obj.message === "string") return obj.message;
        if (typeof obj.reason === "string") return obj.reason;
        return JSON.stringify(c);
      }
      return String(c);
    })
    .filter(Boolean);
}

export function recommendedAction(exceptionType: ExceptionType | string | null | undefined): string {
  switch (exceptionType) {
    case "refund_missing_from_bank":
      return "Search the bank feed for a refund or debit from the same processor within the configured reconciliation window.";
    case "duplicate":
    case "duplicate_refund":
      return "Review possible duplicate — confirm whether both records represent the same economic event.";
    case "amount_mismatch":
      return "Check settlement fees, tax, or partial capture before treating this as a true mismatch.";
    case "overpaid":
      return "Verify invoice payment — the collected amount exceeds the invoice.";
    case "partially_paid":
      return "Verify remaining invoice balance and expected follow-on payments.";
    case "currency_mismatch":
      return "Confirm currency / FX treatment. Hard constraint: currencies do not match.";
    case "ambiguous":
      return "Review candidate transactions and choose the unique counterpart, or escalate if both remain plausible.";
    case "missing_counterpart":
      return "Search the counterpart source for a missing posting within the amount and date window.";
    case "unidentified_cash":
      return "Identify the source of this cash before treating it as available.";
    case "timing_difference":
      return "Confirm whether this is a settlement-lag timing difference rather than a missed match.";
    case "invalid":
      return "Correct or exclude the invalid source record, then re-run reconciliation.";
    default:
      return "Manual investigation required — insufficient evidence for a safe recommendation.";
  }
}

export function decisionHeadline(match: {
  decision?: string | null;
  state?: string | null;
  status?: string | null;
}): string {
  if (match.decision) return match.decision.replace(/_/g, " ");
  if (match.state) return match.state.replace(/_/g, " ");
  if (match.status === "matched") return "RECONCILED";
  if (match.status === "exception") return "EXCEPTION";
  return "DECISION";
}

export function stageGroup(stage: string | null | undefined): "deterministic" | "fuzzy" | "ai" | "unresolved" {
  if (!stage || stage === "unresolved") return "unresolved";
  if (stage === "llm") return "ai";
  if (stage === "fuzzy" || stage === "semantic") return "fuzzy";
  return "deterministic";
}

export function processLabel(stage: string | null | undefined): string {
  switch (stageGroup(stage)) {
    case "deterministic":
      return "Rule engine";
    case "fuzzy":
      return "Fuzzy / semantic";
    case "ai":
      return "AI-adjudicated";
    default:
      return "Needs review";
  }
}

function candidateAmount(c: CandidateRow): number | null {
  const n = c.amount ?? c.net_amount;
  return typeof n === "number" ? n : null;
}

/** Wide input so both full MatchOut results and AuditRecords can render. */
export interface FinancialSidesInput {
  left_source?: MatchOut["left_source"] | null;
  right_source?: MatchOut["right_source"] | null;
  left_txn_ids?: string[] | null;
  right_txn_ids?: string[] | null;
  match_stage?: string | null;
  candidates_shown?: CandidateRow[] | null;
  evidence?: Record<string, unknown> | null;
}

export function financialSides(
  match: FinancialSidesInput
): { leftLabel: string; rightLabel: string; leftAmount: number | null; rightAmount: number | null } {
  const leftId = match.left_txn_ids?.[0];
  const rightId = match.right_txn_ids?.[0];
  const refund = match.match_stage === "refund";
  const leftLabel = refund
    ? `Processor refund${leftId ? ` ${leftId}` : ""}`
    : `${sourceLabel(match.left_source)}${leftId ? ` ${leftId}` : ""}`;
  const rightMissing = !match.right_txn_ids?.length;
  const rightLabel = rightMissing
    ? `${sourceLabel(match.right_source || "bank")} counterpart`
    : `${refund ? "Bank debit" : sourceLabel(match.right_source)}${rightId ? ` ${rightId}` : ""}`;

  const cands = Array.isArray(match.candidates_shown) ? match.candidates_shown : [];
  const rightAmt = cands.length ? candidateAmount(cands[0]) : null;
  let leftAmt: number | null = null;
  const ev = match.evidence;
  if (ev && typeof ev === "object") {
    const rec = ev as Record<string, unknown>;
    for (const key of ["left_amount", "refund_amount", "amount"]) {
      if (typeof rec[key] === "number") {
        leftAmt = rec[key] as number;
        break;
      }
    }
    if (typeof rec.right_amount === "number" && rightAmt == null) {
      return { leftLabel, rightLabel, leftAmount: leftAmt, rightAmount: rec.right_amount as number };
    }
  }
  return { leftLabel, rightLabel, leftAmount: leftAmt, rightAmount: rightAmt };
}

export function impactAmount(match: FinancialSidesInput): number | null {
  const sides = financialSides(match);
  if (sides.leftAmount != null) return Math.abs(sides.leftAmount);
  if (sides.rightAmount != null) return Math.abs(sides.rightAmount);
  return null;
}

export function buildDecisionNarrative(match: {
  reason?: string | null;
  decision?: string | null;
  left_txn_ids?: string[] | null;
  right_txn_ids?: string[] | null;
  match_stage?: string | null;
  exception_type?: string | null;
}): string {
  if (match.reason && match.reason.trim()) return match.reason.trim();
  if (match.exception_type) {
    return `${exceptionLabel(match.exception_type)}. Evidence unavailable for a fuller explanation.`;
  }
  const left = match.left_txn_ids?.[0];
  const right = match.right_txn_ids?.[0];
  if (left && right) {
    return `${left} was compared with ${right}. Evidence unavailable.`;
  }
  return "Evidence unavailable";
}

/**
 * Human "Problem" statement for an exception card (README §6).
 * Built only from fields the backend already stores — transaction IDs,
 * source names and the exception type. No amounts or fees are invented
 * here; the real amounts are rendered separately from stored data.
 */
export function problemStatement(match: {
  exception_type?: string | null;
  left_source?: string | null;
  right_source?: string | null;
  left_txn_ids?: string[] | null;
  right_txn_ids?: string[] | null;
}): string {
  const left = match.left_txn_ids?.[0];
  const leftName = left
    ? `${sourceLabel(match.left_source)} ${left}`
    : `this ${sourceLabel(match.left_source || "record").toLowerCase()}`;
  const right = match.right_txn_ids?.[0];
  const rightName = right
    ? `${sourceLabel(match.right_source)} ${right}`
    : `the ${sourceLabel(match.right_source || "bank").toLowerCase()} record`;
  const rightMissing = !match.right_txn_ids?.length;

  switch (match.exception_type) {
    case "refund_missing_from_bank":
      return left
        ? `Refund ${left} was recorded by the processor, but no matching bank debit was found.`
        : `A refund was recorded by the processor, but no matching bank debit was found.`;
    case "duplicate_refund":
      return `More than one bank debit corresponds to ${leftName}; a duplicate refund is possible.`;
    case "duplicate":
      return `Several transactions are equally plausible counterparts for ${leftName}; a unique match could not be proven.`;
    case "amount_mismatch":
      return rightMissing
        ? `No ${sourceLabel(match.right_source || "bank").toLowerCase()} record with a matching amount was found for ${leftName}.`
        : `${leftName} and ${rightName} were paired, but their recorded amounts differ beyond the allowed tolerance.`;
    case "ambiguous":
      return `Multiple candidate transactions are plausible for ${leftName}; the evidence does not identify a single counterpart.`;
    case "missing_counterpart":
      return `No counterpart for ${leftName} was found in the ${sourceLabel(match.right_source || "bank").toLowerCase()} data within the allowed window.`;
    case "unidentified_cash":
      return `${leftName} could not be tied to any known order, payment, or invoice.`;
    case "partially_paid":
      return `The received amount covers only part of ${leftName}.`;
    case "overpaid":
      return `The received amount exceeds the total for ${leftName}.`;
    case "currency_mismatch":
      return `A plausible counterpart exists for ${leftName}, but the two records are in different currencies.`;
    case "timing_difference":
      return `${leftName} differs from ${rightName} only by settlement date, outside the allowed window.`;
    case "invalid":
      return `${leftName} failed source validation and was excluded from matching.`;
    default:
      return `This case requires human review — the stored evidence does not support an automatic decision.`;
  }
}
