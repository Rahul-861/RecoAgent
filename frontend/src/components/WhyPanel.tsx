import { useEffect, useState } from "react";
import type { MatchOut, ResolutionHistoryEntry } from "../types";
import { resolveException, getResolutionHistory } from "../api/client";
import DecisionCard from "./DecisionCard";
import CounterfactualPanel from "./CounterfactualPanel";
import {
  exceptionLabel,
  isAiUsed,
  problemStatement,
  recommendedAction,
  financialSides,
} from "../utils/evidenceFormatter";
import { formatMoney } from "../utils/format";

interface Props {
  match: MatchOut;
  onResolved: (matchId: string, status: "resolved" | "rejected" | "escalated" | "in_review") => void;
  reviewer?: string;
}

function HistoryList({ entries }: { entries: ResolutionHistoryEntry[] }) {
  return (
    <div className="history-list">
      {entries.map((h) => (
        <div className="history-row" key={h.id}>
          <span className="history-action">{h.action}</span>
          <span className="history-transition">
            {h.previous_lifecycle || "—"} → {h.new_lifecycle || "—"}
          </span>
          <span className="history-meta">
            {h.resolved_by || "unknown"}
            {h.created_at ? ` · ${new Date(h.created_at).toLocaleString()}` : ""}
          </span>
          {h.note && <span className="history-note">{h.note}</span>}
        </div>
      ))}
    </div>
  );
}

export default function WhyPanel({ match, onResolved, reviewer }: Props) {
  const candidates = match.candidates_shown || [];
  const [history, setHistory] = useState<ResolutionHistoryEntry[] | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);
  // The candidate the reviewer marks as the correct counterpart before
  // resolving -- resolving with a pick is what teaches memory (README §7).
  const [chosenCandidateId, setChosenCandidateId] = useState<string | null>(null);
  const sides = financialSides(match);
  const lifecycle = (match.exception_lifecycle || match.review_status || "open").toUpperCase();

  useEffect(() => {
    let cancelled = false;
    setChosenCandidateId(null);
    getResolutionHistory(match.match_id)
      .then((res) => {
        if (!cancelled) setHistory(res.history);
      })
      .catch((e) => {
        if (!cancelled) setHistoryError((e as Error).message);
      });
    return () => {
      cancelled = true;
    };
  }, [match.match_id, historyRefreshKey]);

  async function handleAction(action: "resolved" | "rejected" | "escalated" | "in_review") {
    try {
      await resolveException(
        match.match_id,
        action,
        reviewer,
        action === "resolved" && chosenCandidateId ? chosenCandidateId : undefined
      );
      onResolved(match.match_id, action);
      setHistoryRefreshKey((k) => k + 1);
    } catch (e) {
      alert(`Could not update review status: ${(e as Error).message}`);
    }
  }

  const isException = match.status === "exception";
  const aiUsed = isAiUsed(match);

  return (
    <div className="why-panel">
      {isException && (
        <div className="exception-detail-header">
          <div className="exception-detail-top">
            {match.severity && (
              <span className={`severity-tag severity-${match.severity}`}>{match.severity} severity</span>
            )}
            <span className={`review-badge ${match.review_status}`}>Status: {lifecycle}</span>
          </div>
          <h3>{exceptionLabel(match.exception_type || match.exception_category)}</h3>

          <div className="problem-block">
            <div className="panel-title">Problem</div>
            <p>{problemStatement(match)}</p>
          </div>

          <div className="impact-block">
            <div className="panel-title">Financial impact</div>
            <div className="fin-grid">
              <div className="fin-row">
                <span>{sides.leftLabel}</span>
                <span className="mono">
                  {formatMoney(sides.leftAmount)}
                  {match.left_txn_ids[0] && <span className="impact-id"> · {match.left_txn_ids[0]}</span>}
                </span>
              </div>
              <div className="fin-row">
                <span>{sides.rightLabel}</span>
                <span className="mono">
                  {match.right_txn_ids.length ? formatMoney(sides.rightAmount) : "Not found"}
                  {match.right_txn_ids.length > 0 && (
                    <span className="impact-id"> · {match.right_txn_ids.join(", ")}</span>
                  )}
                </span>
              </div>
            </div>
          </div>

          <CounterfactualPanel match={match} />

          {aiUsed && (
            <div className="ai-assessment">
              <div className="panel-title">AI assessment</div>
              <p>
                This decision was adjudicated by {match.provider_used || "an AI provider"}
                {match.confidence != null ? ` with ${Math.round(match.confidence * 100)}% confidence` : ""} using the
                candidate evidence below. The stored reasoning is kept on the decision record for audit.
              </p>
            </div>
          )}

          <div className="recommended-action">
            <div className="panel-title">Recommended action</div>
            <p>{recommendedAction(match.exception_type)}</p>
          </div>
        </div>
      )}

      <DecisionCard match={match} />

      {candidates.length > 0 && (
        <div className="section-gap">
          <div className="panel-title">Candidate transactions shown to the engine</div>
          <div className="memory-hint">
            Pick the correct counterpart below, then “Mark resolved” — the pairing you approve is
            recorded to Memory and used to suggest matches in future batches.
          </div>
          <div className="why-grid">
            {candidates.map((c, i) => {
              const id = c.transaction_id || c.payment_id || c.bank_txn || `candidate-${i}`;
              const amount = c.amount ?? c.net_amount;
              const selected = chosenCandidateId === id;
              return (
                <div
                  className={`why-row-card${selected ? " candidate-selected" : ""}`}
                  key={id}
                  onClick={() => setChosenCandidateId(selected ? null : id)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") setChosenCandidateId(selected ? null : id);
                  }}
                  title="Click to mark this as the correct counterpart"
                >
                  {selected && <div className="candidate-pick">✓ correct counterpart</div>}
                  <div className="kv">
                    <span>ID</span>
                    <span>{id}</span>
                  </div>
                  <div className="kv">
                    <span>Amount</span>
                    <span>{formatMoney(amount)}</span>
                  </div>
                  {c.date !== undefined && (
                    <div className="kv">
                      <span>Date</span>
                      <span>{c.date || "—"}</span>
                    </div>
                  )}
                  {c.counterparty !== undefined && (
                    <div className="kv">
                      <span>Counterparty</span>
                      <span>{c.counterparty || "—"}</span>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="panel-title section-gap">Resolution history</div>
      <div className="lifecycle-pill">Status: {lifecycle}</div>
      {historyError && <div className="history-empty">Could not load history: {historyError}</div>}
      {!historyError && history === null && <div className="history-empty">Loading history…</div>}
      {!historyError && history !== null && history.length === 0 && (
        <div className="history-empty">No prior resolve / reject / escalate actions on this match.</div>
      )}
      {!historyError && history !== null && history.length > 0 && <HistoryList entries={history} />}

      <div className="why-actions">
        <button className="btn btn-ghost btn-sm" onClick={() => handleAction("in_review")}>
          In review
        </button>
        <button
          className="btn btn-ghost btn-sm"
          disabled={match.review_status === "resolved"}
          onClick={() => handleAction("resolved")}
        >
          Mark resolved
        </button>
        <button
          className="btn btn-ghost btn-sm"
          disabled={match.review_status === "rejected"}
          onClick={() => handleAction("rejected")}
        >
          Reject
        </button>
        <button className="btn btn-ghost btn-sm" onClick={() => handleAction("escalated")}>
          Escalate
        </button>
      </div>
    </div>
  );
}
