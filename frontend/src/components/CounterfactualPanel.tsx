import { useEffect, useState } from "react";
import { getContract } from "../api/client";
import type { MatchingContract, MatchOut } from "../types";
import {
  exceptionLabel,
  financialSides,
  formatContradictions,
  formatEvidence,
} from "../utils/evidenceFormatter";
import { formatMoney } from "../utils/format";

interface Props {
  match: MatchOut;
}

interface Tolerances {
  amountTolerance: number | null;
  timingDays: number | null;
  candidateMargin: number | null;
}

function readTolerances(contract: MatchingContract | null): Tolerances | null {
  const m = contract?.matching;
  if (!m) return null;
  const t: Tolerances = {
    amountTolerance: typeof m.amount_tolerance === "number" ? m.amount_tolerance : null,
    timingDays: typeof m.timing_tolerance_days === "number" ? m.timing_tolerance_days : null,
    candidateMargin: typeof m.min_candidate_margin === "number" ? m.min_candidate_margin : null,
  };
  if (t.amountTolerance == null && t.timingDays == null && t.candidateMargin == null) return null;
  return t;
}

/**
 * Counterfactual explanation (README §12): why this did NOT match, and — only
 * where the real configured tolerances support it — what would have made it
 * match. Thresholds always come from the backend's own /api/contract; when
 * they can't be loaded the section is omitted rather than guessed.
 */
export default function CounterfactualPanel({ match }: Props) {
  const [tolerances, setTolerances] = useState<Tolerances | null>(null);

  useEffect(() => {
    let cancelled = false;
    getContract().then((c) => {
      if (!cancelled) setTolerances(readTolerances(c));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const sides = financialSides(match);
  const type = match.exception_type;
  if (!type) return null;

  // Blocking evidence: only warning/danger rows and real contradictions.
  const blocking = formatEvidence(match.evidence).filter(
    (r) => r.status === "warning" || r.status === "danger"
  );
  const contradictions = formatContradictions(match.contradictions);
  const hasBlocking = blocking.length > 0 || contradictions.length > 0;

  // Counterfactual requirements — derived only from real configured values.
  const conditions: string[] = [];
  if (tolerances?.amountTolerance != null && type === "amount_mismatch") {
    conditions.push(
      `Amount within the configured ±${Math.round(tolerances.amountTolerance * 1000) / 10}% tolerance`
    );
  }
  if (type === "currency_mismatch") {
    conditions.push("Both records carrying the same currency");
  }
  if (tolerances?.timingDays != null && type === "timing_difference") {
    conditions.push(`Dates within the configured ${tolerances.timingDays}-day window`);
  }
  if (
    tolerances?.candidateMargin != null &&
    (type === "duplicate" || type === "ambiguous")
  ) {
    conditions.push(
      `One candidate clearly ahead of the rest — beating the runner-up by the configured ${Math.round(
        tolerances.candidateMargin * 100
      )}% margin`
    );
  }

  const diff =
    sides.leftAmount != null && sides.rightAmount != null
      ? Math.round((sides.leftAmount - sides.rightAmount) * 100) / 100
      : null;

  const hasAmounts = sides.leftAmount != null || sides.rightAmount != null;
  if (!hasAmounts && !hasBlocking && conditions.length === 0) return null;

  return (
    <div className="counterfactual">
      <div className="panel-title">Why did this not match?</div>
      <p className="counterfactual-headline">{exceptionLabel(type)}</p>

      {hasAmounts && (
        <div className="fin-grid">
          {sides.leftAmount != null && (
            <div className="fin-row">
              <span>Expected — {sides.leftLabel}</span>
              <span className="mono">{formatMoney(sides.leftAmount)}</span>
            </div>
          )}
          {sides.rightAmount != null && (
            <div className="fin-row">
              <span>Observed — {sides.rightLabel}</span>
              <span className="mono">{formatMoney(sides.rightAmount)}</span>
            </div>
          )}
          {diff != null && diff !== 0 && (
            <div className="fin-row fin-difference">
              <span>Difference</span>
              <span className="mono">{formatMoney(Math.abs(diff))}</span>
            </div>
          )}
        </div>
      )}

      {hasBlocking && (
        <>
          <div className="panel-title section-gap-sm">Blocking evidence</div>
          <ul className="counterfactual-list">
            {blocking.map((r) => (
              <li key={r.label}>
                <strong>{r.label}</strong>
                {r.value ? ` — ${r.value}` : ""}
                {r.detail ? ` · ${r.detail}` : ""}
              </li>
            ))}
            {contradictions.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </>
      )}

      {conditions.length > 0 && (
        <>
          <div className="panel-title section-gap-sm">What would have made this match?</div>
          <ul className="counterfactual-list counterfactual-fix">
            {conditions.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
          <p className="metric-sub">
            Conditions come from the engine's configured tolerances, not from this record.
          </p>
        </>
      )}
    </div>
  );
}
