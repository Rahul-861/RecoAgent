import type { MatchOut } from "../types";
import { decisionHeadline, formatRule } from "../utils/evidenceFormatter";
import ConfidenceBadge from "./ConfidenceBadge";

/**
 * All fields are optional so audit records (which store confidence as a
 * nullable value and carry no `status`) can reuse the same chip.
 */
interface Props {
  match: Partial<
    Pick<MatchOut, "decision" | "state" | "rule_id" | "decision_stage" | "pipeline_version">
  > & {
    status?: MatchOut["status"];
    confidence?: number | null;
  };
}

export default function ReconciliationState({ match }: Props) {
  if (!match.decision && !match.state && !match.rule_id) return null;
  const headline = decisionHeadline(match);

  return (
    <div className="recon-state-chip">
      <span className={`status-badge status-${(match.decision || match.status || "open").toLowerCase()}`}>
        {headline}
      </span>
      {match.confidence != null && <ConfidenceBadge confidence={match.confidence} compact />}
      {match.rule_id && <span className="recon-state-rule">{formatRule(match.rule_id, match.decision_stage)}</span>}
    </div>
  );
}
