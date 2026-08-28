import DecisionCard, { type DecisionInput } from "./DecisionCard";

/**
 * Human-readable evidence block. Raw JSON is behind Technical evidence
 * inside DecisionCard. Accepts the same wide input as DecisionCard so
 * AuditPanel (AuditRecord) and WhyPanel (MatchOut) can both compose it.
 */
export default function DecisionEvidence({ match }: { match: DecisionInput }) {
  return <DecisionCard match={match} />;
}
