import type { MatchOut } from "../types";
import { decisionHeadline, formatRule, isAiUsed, processLabel } from "../utils/evidenceFormatter";
import ConfidenceBadge from "./ConfidenceBadge";
import DecisionExplanation from "./DecisionExplanation";
import EvidenceSummary from "./EvidenceSummary";
import FinancialEvidence from "./FinancialEvidence";
import TechnicalEvidence from "./TechnicalEvidence";

/**
 * Everything optional (and null-tolerant) so both full MatchOut results
 * and AuditRecords (nullable strings, no status field) can render through
 * the same evidence card. Shared evidence presentation lives here — do
 * not duplicate implementations (README §17).
 */
export type DecisionInput = {
  [K in keyof MatchOut]?: MatchOut[K] | null;
} & {
  AI_used?: boolean | null;
  AI_provider?: string | null;
  AI_model?: string | null;
};

interface Props {
  match: DecisionInput;
}

export default function DecisionCard({ match }: Props) {
  const ai = isAiUsed(match);
  const headline = decisionHeadline(match);

  // Deterministic vs AI provenance (README §13). Only real fields:
  // a human resolution is visible via review status / lifecycle, AI use via
  // the stored AI fields, everything else was decided by deterministic rules.
  const lifecycle = (match.exception_lifecycle || "").toUpperCase();
  const humanResolved =
    match.review_status === "resolved" ||
    match.review_status === "rejected" ||
    lifecycle === "RESOLVED" ||
    lifecycle === "REJECTED";
  const provenance = humanResolved
    ? { cls: "prov-human", label: "Human-resolved" }
    : ai
      ? { cls: "prov-ai", label: "AI-assisted" }
      : match.rule_id || match.decision_stage
        ? { cls: "prov-rule", label: "Rule-based" }
        : null;

  return (
    <div className="decision-card">
      <div className="decision-card-header">
        <span className={`status-badge status-${(match.decision || match.status || "open").toLowerCase()}`}>
          {headline}
        </span>
        {provenance && <span className={`provenance-tag ${provenance.cls}`}>{provenance.label}</span>}
        {match.relationship_type && (
          <span className="decision-meta">Relationship: {match.relationship_type.replace(/_/g, " ")}</span>
        )}
        <span className="decision-meta">
          Decision stage: {match.decision_stage?.replace(/_/g, " ") || processLabel(match.match_stage)}
        </span>
      </div>

      {match.confidence != null && (
        <div className="decision-confidence">
          <span className="decision-confidence-label">Match confidence</span>
          <ConfidenceBadge confidence={match.confidence} />
        </div>
      )}

      <DecisionExplanation
        reason={match.reason}
        decision={match.decision}
        left_txn_ids={match.left_txn_ids}
        right_txn_ids={match.right_txn_ids}
        match_stage={match.match_stage}
        exception_type={match.exception_type}
      />

      <div className="panel-title">Evidence</div>
      <EvidenceSummary evidence={match.evidence} contradictions={match.contradictions} />

      <FinancialEvidence match={match} />

      <div className="kv">
        <span>Rule</span>
        <span>{formatRule(match.rule_id, match.match_stage)}</span>
      </div>

      {ai && (
        <div className="ai-callout">
          <strong>AI assisted</strong>
          <div className="kv">
            <span>Provider</span>
            <span>{match.AI_provider || match.provider_used || "—"}</span>
          </div>
          {match.AI_model && (
            <div className="kv">
              <span>Model</span>
              <span>{match.AI_model}</span>
            </div>
          )}
          {match.confidence != null && (
            <div className="kv">
              <span>AI confidence</span>
              <span>{Math.round(match.confidence * 100)}%</span>
            </div>
          )}
        </div>
      )}

      <TechnicalEvidence evidence={match.evidence} contradictions={match.contradictions} />
    </div>
  );
}
