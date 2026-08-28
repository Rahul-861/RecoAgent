import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { getExceptions } from "../api/client";
import type { MatchOut } from "../types";
import WhyPanel from "../components/WhyPanel";
import { ErrorBlock, LoadingBlock } from "../components/StateBlocks";
import { exceptionLabel, impactAmount } from "../utils/evidenceFormatter";
import { formatMoney } from "../utils/format";

function idLabel(m: MatchOut): string {
  const left = m.left_txn_ids.length ? `${m.left_source ?? ""} ${m.left_txn_ids.join(", ")}` : null;
  const right = m.right_txn_ids.length ? `${m.right_source ?? ""} ${m.right_txn_ids.join(", ")}` : null;
  return [left, right].filter(Boolean).join(" ↔ ") || "—";
}

const SEVERITY_RANK: Record<string, number> = { high: 0, medium: 1, low: 2, none: 3 };

export default function ExceptionQueue() {
  const { batchId } = useParams<{ batchId: string }>();
  const [matches, setMatches] = useState<MatchOut[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>("all");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!batchId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getExceptions(batchId)
      .then((res) => {
        if (!cancelled) setMatches(res.matches);
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

  function handleResolved(matchId: string, status: "resolved" | "rejected" | "escalated" | "in_review") {
    setMatches((prev) =>
      prev.map((m) =>
        m.match_id === matchId
          ? {
              ...m,
              // Only the two terminal actions change review_status; the
              // visible state comes from exception_lifecycle either way.
              review_status: status === "resolved" || status === "rejected" ? status : m.review_status,
              exception_lifecycle: status === "in_review" ? "IN_REVIEW" : status.toUpperCase(),
            }
          : m
      )
    );
  }

  const summary = useMemo(() => {
    const high = matches.filter((m) => m.severity === "high").length;
    const medium = matches.filter((m) => m.severity === "medium").length;
    const low = matches.filter((m) => m.severity === "low").length;
    const value = matches.reduce((sum, m) => sum + (impactAmount(m) || 0), 0);
    const byType = new Map<string, { count: number; value: number }>();
    for (const m of matches) {
      const key = m.exception_type || "other";
      const cur = byType.get(key) || { count: 0, value: 0 };
      cur.count += 1;
      cur.value += impactAmount(m) || 0;
      byType.set(key, cur);
    }
    return { high, medium, low, value, byType };
  }, [matches]);

  if (error) {
    return (
      <div className="page">
        <div className="page-header">
          <h1>Exceptions</h1>
        </div>
        <ErrorBlock
          context="Unable to load the exception queue."
          message={error}
          onRetry={() => setReloadKey((k) => k + 1)}
        />
      </div>
    );
  }

  if (loading) {
    return (
      <div className="page">
        <div className="page-header">
          <h1>Exceptions</h1>
        </div>
        <LoadingBlock message="Loading exception queue…" />
      </div>
    );
  }

  const types = Array.from(summary.byType.keys());
  const filtered = filter === "all" ? matches : matches.filter((m) => (m.exception_type || "other") === filter);
  const maxCat = Math.max(1, ...Array.from(summary.byType.values()).map((v) => v.count));

  // Prioritized human review queue (README §9): the accountant reviews the
  // most important unresolved items first. Ranked by real data only —
  // financial impact, then severity, then ambiguity (lowest confidence first).
  const prioritized = [...filtered].sort((a, b) => {
    const ia = impactAmount(a) ?? 0;
    const ib = impactAmount(b) ?? 0;
    if (ib !== ia) return ib - ia;
    const sa = SEVERITY_RANK[a.severity ?? ""] ?? SEVERITY_RANK.none;
    const sb = SEVERITY_RANK[b.severity ?? ""] ?? SEVERITY_RANK.none;
    if (sa !== sb) return sa - sb;
    const ca = typeof a.confidence === "number" ? a.confidence : 0;
    const cb = typeof b.confidence === "number" ? b.confidence : 0;
    return ca - cb;
  });

  return (
    <div className="page">
      <div className="page-header">
        <h1>Exceptions</h1>
        <p>
          Uncertain cases stay visible instead of being guessed into a match. Review financial impact,
          recommended next action, and stored evidence — then resolve, reject, or escalate.
        </p>
      </div>

      <div className="panel panel-pad exception-summary-header">
        <div className="exception-headline">
          <span className="metric-value warning">{matches.length}</span>
          <span className="exception-headline-label">
            {matches.length === 1 ? "exception requires attention" : "exceptions require attention"}
          </span>
        </div>
        <div className="severity-counts">
          <span className="sev-pill sev-high">High severity: {summary.high}</span>
          <span className="sev-pill sev-medium">Medium: {summary.medium}</span>
          <span className="sev-pill sev-low">Low: {summary.low}</span>
          <span className="sev-pill sev-value">Total value affected: {formatMoney(summary.value)}</span>
        </div>
      </div>

      {types.length > 0 && (
        <div className="panel panel-pad section-gap">
          <div className="panel-title">Category distribution</div>
          <div className="cat-bars">
            {Array.from(summary.byType.entries())
              .sort((a, b) => b[1].count - a[1].count)
              .map(([t, v]) => (
                <button
                  type="button"
                  key={t}
                  className={`cat-bar-row ${filter === t ? "active" : ""}`}
                  onClick={() => setFilter(filter === t ? "all" : t)}
                >
                  <span className="cat-bar-label">{exceptionLabel(t)}</span>
                  <span className="cat-bar-track">
                    <span className="cat-bar-fill" style={{ width: `${(v.count / maxCat) * 100}%` }} />
                  </span>
                  <span className="cat-bar-count mono">
                    {v.count} · {formatMoney(v.value)}
                  </span>
                </button>
              ))}
          </div>
        </div>
      )}

      <div className="filter-chips">
        <button className={`filter-chip ${filter === "all" ? "active" : ""}`} onClick={() => setFilter("all")}>
          All ({matches.length})
        </button>
        {types.map((t) => (
          <button
            key={t}
            className={`filter-chip ${filter === t ? "active" : ""}`}
            onClick={() => setFilter(t)}
          >
            {exceptionLabel(t)} ({summary.byType.get(t)?.count || 0})
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div className="panel">
          <div className="empty-state">
            <h3>No open exceptions</h3>
            <p>Every row cleared the pipeline with a confident match. Nothing to review here.</p>
          </div>
        </div>
      ) : (
        <>
          <p className="metric-sub queue-note">
            Prioritized by financial impact, then severity, then ambiguity — review the top
            items first.
          </p>
          <div className="exception-list">
            {prioritized.map((m, rank) => {
              const isOpen = expanded === m.match_id;
              const impact = impactAmount(m);
              return (
                <div className={`exception-row ${isOpen ? "open" : ""}`} key={m.match_id}>
                  <div
                    className="exception-summary"
                    onClick={() => setExpanded(isOpen ? null : m.match_id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setExpanded(isOpen ? null : m.match_id);
                      }
                    }}
                    role="button"
                    tabIndex={0}
                    aria-expanded={isOpen}
                  >
                    <span className="exception-rank mono">{rank + 1}</span>
                    <span className={`chevron ${isOpen ? "open" : ""}`}>▶</span>
                  <span className="exception-id">{idLabel(m)}</span>
                  <span className="exception-reason">{exceptionLabel(m.exception_type)}</span>
                  <span className="exception-impact mono">{formatMoney(impact)}</span>
                  <span className="exception-badges">
                    {m.severity && <span className={`severity-tag severity-${m.severity}`}>{m.severity}</span>}
                    <span className={`review-badge ${m.review_status}`}>{m.exception_lifecycle || m.review_status}</span>
                  </span>
                </div>
                {isOpen && <WhyPanel match={m} onResolved={handleResolved} />}
              </div>
            );
          })}
          </div>
        </>
      )}
    </div>
  );
}
