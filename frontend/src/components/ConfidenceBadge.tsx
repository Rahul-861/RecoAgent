import { confidenceBand } from "../utils/format";

interface Props {
  confidence: number | null | undefined;
  /** compact: shorter label, for table rows */
  compact?: boolean;
}

/**
 * Consistent confidence presentation (README §15):
 *   95%  High confidence
 *   72%  Review recommended
 *   0%   No match
 * The score always comes from the API — never fabricated — and the
 * wording deliberately avoids sounding like certainty.
 */
const BANDS: Record<"High" | "Medium" | "Low", { label: string; short: string; cls: string }> = {
  High: { label: "High confidence", short: "High", cls: "conf-high" },
  Medium: { label: "Review recommended", short: "Review", cls: "conf-medium" },
  Low: { label: "Low confidence", short: "Low", cls: "conf-low" },
};

export default function ConfidenceBadge({ confidence, compact }: Props) {
  if (confidence == null || Number.isNaN(confidence)) return null;
  const band = confidenceBand(confidence);
  if (!band) return null;
  const meta = BANDS[band];
  const pct = Math.round(confidence * 100);
  const label = pct === 0 ? "No match" : compact ? meta.short : meta.label;
  return (
    <span
      className={`confidence-badge ${meta.cls}${compact ? " compact" : ""}`}
      title="Agent confidence score — high-confidence cases are auto-reconciled, uncertain cases are escalated for review."
    >
      <span className="confidence-pct mono">{pct}%</span>
      <span className="confidence-label">{label}</span>
    </span>
  );
}