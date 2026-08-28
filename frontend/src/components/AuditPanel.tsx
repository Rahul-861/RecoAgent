import { useEffect, useState } from "react";
import { getAudit, getResolutionHistory } from "../api/client";
import type { AuditRecord, ResolutionHistoryEntry } from "../types";
import ReconciliationState from "./ReconciliationState";
import DecisionEvidence from "./DecisionEvidence";
import ConfidenceBadge from "./ConfidenceBadge";
import { ErrorBlock, LoadingBlock } from "./StateBlocks";

interface Props {
  batchId: string;
}

function idLabel(r: AuditRecord): string {
  const left = r.left_txn_ids?.length ? r.left_txn_ids.join(", ") : r.transaction_id;
  const right = r.right_txn_ids?.length ? r.right_txn_ids.join(", ") : r.matched_transaction_id;
  return [left, right].filter(Boolean).join(" ↔ ") || r.match_id;
}

function HistoryRow({ entry }: { entry: ResolutionHistoryEntry }) {
  return (
    <div className="history-row">
      <span className="history-action">{entry.action}</span>
      <span className="history-transition mono">
        {entry.previous_lifecycle || "—"} → {entry.new_lifecycle || "—"}
      </span>
      <span className="history-meta">
        {entry.resolved_by || "unknown"}
        {entry.created_at ? ` · ${new Date(entry.created_at).toLocaleString()}` : ""}
      </span>
      {entry.note && <span className="history-note">{entry.note}</span>}
    </div>
  );
}

function ResolutionHistoryBlock({ matchId }: { matchId: string }) {
  const [entries, setEntries] = useState<ResolutionHistoryEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getResolutionHistory(matchId)
      .then((res) => {
        if (!cancelled) setEntries(res.history);
      })
      .catch((e) => {
        if (!cancelled) setError((e as Error).message);
      });
    return () => {
      cancelled = true;
    };
  }, [matchId]);

  if (error) return <div className="history-empty">Could not load history: {error}</div>;
  if (entries === null) return <div className="history-empty">Loading history…</div>;
  if (entries.length === 0) {
    return <div className="history-empty">No resolution actions recorded for this match yet.</div>;
  }

  return (
    <div className="history-list">
      {entries.map((e) => (
        <HistoryRow key={e.id} entry={e} />
      ))}
    </div>
  );
}

export default function AuditPanel({ batchId }: Props) {
  const [records, setRecords] = useState<AuditRecord[]>([]);
  const [completeness, setCompleteness] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!batchId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getAudit(batchId)
      .then((res) => {
        if (!cancelled) {
          setRecords(res.records);
          setCompleteness(res.audit_completeness);
        }
      })
      .catch((e) => {
        if (!cancelled) setError((e as Error).message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [batchId, reloadKey]);

  if (error) {
    return (
      <ErrorBlock
        context="Unable to load the audit trail."
        message={error}
        onRetry={() => setReloadKey((k) => k + 1)}
      />
    );
  }

  if (loading) {
    return <LoadingBlock message="Loading audit trail…" />;
  }

  if (records.length === 0) {
    return (
      <div className="panel panel-pad">
        <div className="empty-state">
          <h3>No audit records yet</h3>
          <p>Run reconciliation on this batch to generate an audit trail.</p>
        </div>
      </div>
    );
  }

  const pipelineVersion = records[0]?.pipeline_version || "—";
  const ruleSetVersion = records[0]?.rule_set_version || "—";
  const normalizationVersion = records[0]?.normalization_version || "—";

  return (
    <div>
      <div className="metrics-grid" style={{ marginBottom: 18 }}>
        <div className="panel metric-card" style={{ boxShadow: "none" }}>
          <div className="metric-value">{pipelineVersion}</div>
          <div className="metric-label">Pipeline version</div>
        </div>
        <div className="panel metric-card" style={{ boxShadow: "none" }}>
          <div className="metric-value">{ruleSetVersion}</div>
          <div className="metric-label">Rule set version</div>
        </div>
        <div className="panel metric-card" style={{ boxShadow: "none" }}>
          <div className="metric-value">{normalizationVersion}</div>
          <div className="metric-label">Normalization version</div>
        </div>
        <div className="panel metric-card" style={{ boxShadow: "none" }}>
          <div className="metric-value">
            {completeness != null ? `${Math.round(completeness * 1000) / 10}%` : "—"}
          </div>
          <div className="metric-label">Audit completeness</div>
          <div className="metric-sub">{records.length} decision{records.length !== 1 ? "s" : ""} recorded</div>
        </div>
      </div>

      <div className="exception-list">
        {records.map((r) => {
          const isOpen = expanded === r.match_id;
          return (
            <div className="exception-row" key={r.match_id}>
              <div
                className="exception-summary"
                onClick={() => setExpanded(isOpen ? null : r.match_id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setExpanded(isOpen ? null : r.match_id);
                  }
                }}
                role="button"
                tabIndex={0}
                aria-expanded={isOpen}
              >
                <span className={`chevron ${isOpen ? "open" : ""}`}>▶</span>
                <span className="exception-confidence">
                  <ConfidenceBadge confidence={r.confidence} compact />
                </span>
                <span className="exception-id">{idLabel(r)}</span>
                <span className="exception-reason">{r.reason || "—"}</span>
                <span className="exception-badges">
                  {r.AI_used && <span className="provider-tag">via {r.AI_provider || "AI"}</span>}
                </span>
              </div>
              {isOpen && (
                <div className="why-panel">
                  <ReconciliationState match={r} />
                  <DecisionEvidence match={r} />
                  <div className="panel-title section-gap">Audit metadata</div>
                  <div className="kv">
                    <span>Decision ID</span>
                    <span className="mono">{r.match_id}</span>
                  </div>
                  <div className="kv">
                    <span>Timestamp</span>
                    <span className="mono">
                      {r.timestamp ? new Date(r.timestamp).toLocaleString() : "—"}
                    </span>
                  </div>
                  <div className="kv">
                    <span>Pipeline version</span>
                    <span className="mono">{r.pipeline_version || "—"}</span>
                  </div>
                  <div className="kv">
                    <span>Rule set version</span>
                    <span className="mono">{r.rule_set_version || "—"}</span>
                  </div>
                  <div className="kv">
                    <span>Normalization version</span>
                    <span className="mono">{r.normalization_version || "—"}</span>
                  </div>
                  <div className="kv">
                    <span>AI used</span>
                    <span>{r.AI_used ? `${r.AI_provider || "Yes"}${r.AI_model ? ` · ${r.AI_model}` : ""}` : "No"}</span>
                  </div>
                  <div className="panel-title section-gap">Resolution history</div>
                  <ResolutionHistoryBlock matchId={r.match_id} />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
