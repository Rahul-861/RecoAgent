import { formatContradictions, formatEvidence, type FormattedEvidenceRow } from "../utils/evidenceFormatter";

interface Props {
  evidence?: unknown;
  contradictions?: unknown;
}

function mark(status: FormattedEvidenceRow["status"]) {
  if (status === "success") return "✓";
  if (status === "danger") return "⚠";
  if (status === "warning") return "•";
  return "•";
}

export default function EvidenceSummary({ evidence, contradictions }: Props) {
  const rows = formatEvidence(evidence);
  const contradictionsList = formatContradictions(contradictions);

  if (rows.length === 0 && contradictionsList.length === 0) {
    return <div className="evidence-empty">Evidence unavailable</div>;
  }

  return (
    <div className="evidence-summary">
      {rows.map((row) => (
        <div className={`evidence-row evidence-${row.status}`} key={row.label}>
          <span className="evidence-mark">{mark(row.status)}</span>
          <span className="evidence-label">{row.label}</span>
          <span className="evidence-value">
            {row.value}
            {row.detail ? <span className="evidence-detail"> · {row.detail}</span> : null}
          </span>
        </div>
      ))}
      {contradictionsList.length > 0 ? (
        <div className="contradiction-block">
          <div className="contradiction-title">⚠ Contradictions</div>
          <ul>
            {contradictionsList.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="evidence-row evidence-success">
          <span className="evidence-mark">✓</span>
          <span className="evidence-value">No contradictions detected</span>
        </div>
      )}
    </div>
  );
}
