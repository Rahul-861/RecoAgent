import type { MatchOut } from "../types";
import { financialSides } from "../utils/evidenceFormatter";
import { formatMoney } from "../utils/format";

interface Props {
  match: {
    left_source?: MatchOut["left_source"];
    right_source?: MatchOut["right_source"];
    left_txn_ids?: string[] | null;
    right_txn_ids?: string[] | null;
    match_stage?: string | null;
    candidates_shown?: MatchOut["candidates_shown"];
    evidence?: MatchOut["evidence"];
  };
}

export default function FinancialEvidence({ match }: Props) {
  const sides = financialSides(match);
  const bothMissing = sides.leftAmount == null && sides.rightAmount == null;
  const diff =
    sides.leftAmount != null && sides.rightAmount != null
      ? Math.abs(sides.leftAmount) - Math.abs(sides.rightAmount)
      : null;

  return (
    <div className="financial-evidence">
      <div className="panel-title">Financial evidence</div>
      {bothMissing ? (
        <div className="evidence-empty">Evidence unavailable for source amounts on this decision.</div>
      ) : (
        <div className="fin-grid">
          <div className="fin-row">
            <span>{sides.leftLabel}</span>
            <span className="mono">{formatMoney(sides.leftAmount)}</span>
          </div>
          <div className="fin-row">
            <span>{sides.rightLabel}</span>
            <span className="mono">
              {match.right_txn_ids?.length ? formatMoney(sides.rightAmount) : "Not found"}
            </span>
          </div>
          <div className="fin-row fin-diff">
            <span>Difference</span>
            <span className="mono">{diff == null ? "—" : formatMoney(diff)}</span>
          </div>
        </div>
      )}
    </div>
  );
}
