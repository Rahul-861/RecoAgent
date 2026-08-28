import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import {
  getBatch,
  getAccuracy,
  askQuestion,
  getExceptions,
  getForecast,
  getGraph,
  getDataQuality,
} from "../api/client";
import type {
  AccuracyReport,
  BatchSummary,
  CashForecastResponse,
  DataQualityResponse,
  EventChain,
  MatchOut,
  QAResponse,
} from "../types";
import StageBar from "../components/StageBar";
import { ErrorBlock, LoadingBlock } from "../components/StateBlocks";
import { exceptionLabel, impactAmount } from "../utils/evidenceFormatter";
import { formatMoney } from "../utils/format";

function pct(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return `${Math.round(n * 1000) / 10}%`;
}

const SUGGESTED_QUESTIONS = [
  "How many exceptions do I have?",
  "Tell me about refunds",
  "What's the manual review reduction?",
  "How fast did this run?",
];

const FLOW_STEPS = ["Order", "Payment", "Settlement", "Bank", "ERP"];

/** Canonical money flow strip (README §3/§8) — Order → Payment → Settlement → Bank → ERP. */
function MoneyFlowStrip({ chains, batchId }: { chains: EventChain[] | null; batchId: string }) {
  const complete = chains ? chains.filter((c) => c.status === "complete").length : null;
  return (
    <div className="panel panel-pad">
      <div className="panel-head-row">
        <div className="panel-title">Money flow</div>
        <Link className="panel-link" to={`/graph/${batchId}`}>
          Explore money flow →
        </Link>
      </div>
      <div className="flow-strip">
        {FLOW_STEPS.map((label, i) => (
          <span key={label} className="flow-step">
            {i > 0 && <span className="flow-arrow">→</span>}
            <span className="flow-chip">{label}</span>
          </span>
        ))}
      </div>
      <p className="metric-sub">
        {chains
          ? `${complete} of ${chains.length} payment chains traced end-to-end across all sources.`
          : "Every payment follows Order → Payment → Settlement → Bank → ERP; open the Money Flow page to trace individual chains."}
      </p>
    </div>
  );
}

/** Top exception categories requiring attention (real counts + real affected value). */
function ExceptionsNeedingAttention({
  exceptions,
  batchId,
}: {
  exceptions: MatchOut[] | null;
  batchId: string;
}) {
  const cats = exceptions
    ? (() => {
        const map = new Map<string, { count: number; value: number }>();
        for (const m of exceptions) {
          const key = m.exception_type || "other";
          const cur = map.get(key) || { count: 0, value: 0 };
          cur.count += 1;
          cur.value += impactAmount(m) || 0;
          map.set(key, cur);
        }
        return Array.from(map.entries()).sort((a, b) => b[1].count - a[1].count).slice(0, 4);
      })()
    : [];
  const high = exceptions ? exceptions.filter((m) => m.severity === "high").length : 0;
  const totalValue = exceptions
    ? exceptions.reduce((sum, m) => sum + (impactAmount(m) || 0), 0)
    : null;

  return (
    <div className="panel panel-pad">
      <div className="panel-head-row">
        <div className="panel-title">Exceptions requiring attention</div>
        <Link className="panel-link" to={`/exceptions/${batchId}`}>
          Review queue →
        </Link>
      </div>
      {exceptions === null ? (
        <p className="metric-sub">Open the Exceptions page for the full, live list.</p>
      ) : exceptions.length === 0 ? (
        <p className="all-clear">✓ No unresolved exceptions found — every row cleared with a confident match.</p>
      ) : (
        <>
          <div className="attention-grid">
            {cats.map(([type, v]) => (
              <Link key={type} to={`/exceptions/${batchId}`} className="attention-card">
                <span className="attention-count mono">{v.count}</span>
                <span className="attention-label">{exceptionLabel(type)}</span>
                <span className="attention-value mono">{formatMoney(v.value)}</span>
              </Link>
            ))}
          </div>
          <p className="metric-sub">
            {high} high severity · {exceptions.length} open total · affected value{" "}
            {formatMoney(totalValue ?? 0)}
          </p>
        </>
      )}
    </div>
  );
}

/** Connects unresolved reconciliation issues to cash at risk (README §3). */
function CashImpact({
  exceptions,
  forecast,
  batchId,
}: {
  exceptions: MatchOut[] | null;
  forecast: CashForecastResponse | null;
  batchId: string;
}) {
  const affected = exceptions
    ? exceptions.reduce((sum, m) => sum + (impactAmount(m) || 0), 0)
    : null;
  return (
    <div className="panel panel-pad">
      <div className="panel-head-row">
        <div className="panel-title">Cash impact</div>
        <Link className="panel-link" to={`/forecast/${batchId}`}>
          Cash Outlook →
        </Link>
      </div>
      <div className="impact-grid">
        <div className="impact-cell">
          <span className="impact-num mono">{affected != null ? formatMoney(affected) : "—"}</span>
          <span className="metric-sub">Unresolved exception value</span>
        </div>
        <div className="impact-cell">
          <span className="impact-num mono warning">
            {forecast ? formatMoney(forecast.totals.at_risk) : "—"}
          </span>
          <span className="metric-sub">
            {forecast
              ? `Projected at-risk cash over the next ${forecast.horizon_days} days`
              : "Cash at risk — run the Cash Outlook to project"}
          </span>
        </div>
      </div>
      <p className="metric-sub">
        Unresolved reconciliation issues are money recorded in one source without a proven
        counterpart — it can't be relied on until the exception is resolved.
      </p>
    </div>
  );
}

/** Agent summary + human-in-the-loop presentation (README §5/§24) — real counts only. */
function AgentPanel({ batch, exceptions }: { batch: BatchSummary; exceptions: MatchOut[] | null }) {
  const b = batch.stage_breakdown;
  const total = b ? Object.values(b).reduce((sum, n) => sum + (n || 0), 0) : null;
  const unresolved = b ? b.unresolved : null;
  const resolved = total != null && unresolved != null ? total - unresolved : null;
  const aiAssisted = b ? b.llm : null;
  const rejected = exceptions
    ? exceptions.filter((m) => m.review_status === "rejected").length
    : null;

  return (
    <div className="panel panel-pad agent-panel">
      <div className="agent-kicker">Reconciliation agent</div>
      <div className="agent-stats">
        {total != null && (
          <div className="agent-stat">
            <span className="agent-num mono">{total}</span>
            <span className="agent-label">decisions made</span>
          </div>
        )}
        {resolved != null && (
          <div className="agent-stat">
            <span className="agent-num mono success">{resolved}</span>
            <span className="agent-label">automatically resolved</span>
          </div>
        )}
        {aiAssisted != null && aiAssisted > 0 && (
          <div className="agent-stat">
            <span className="agent-num mono accent">{aiAssisted}</span>
            <span className="agent-label">AI-assisted</span>
          </div>
        )}
        {unresolved != null && (
          <div className="agent-stat">
            <span className="agent-num mono warning">{unresolved}</span>
            <span className="agent-label">require human review</span>
          </div>
        )}
        {rejected != null && rejected > 0 && (
          <div className="agent-stat">
            <span className="agent-num mono danger">{rejected}</span>
            <span className="agent-label">rejected by review</span>
          </div>
        )}
      </div>
      <div className="human-loop">
        <div className="human-loop-step">
          <span className="hl-top">High confidence</span>
          <span className="hl-arrow">↓</span>
          <span className="hl-bottom">Auto-resolve</span>
        </div>
        <div className="human-loop-step">
          <span className="hl-top">Uncertain</span>
          <span className="hl-arrow">↓</span>
          <span className="hl-bottom">AI / assisted review</span>
        </div>
        <div className="human-loop-step">
          <span className="hl-top">Insufficient evidence / high risk</span>
          <span className="hl-arrow">↓</span>
          <span className="hl-bottom">Human review</span>
        </div>
      </div>
    </div>
  );
}

/**
 * Data-quality layer (README §15): records that failed source validation.
 * These are data-quality problems, not reconciliation failures — they were
 * excluded from matching and their values were never modified.
 */
function DataQualityPanel({ batchId, invalidCount }: { batchId: string; invalidCount: number }) {
  const [data, setData] = useState<DataQualityResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (invalidCount <= 0) return;
    let cancelled = false;
    getDataQuality(batchId)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((e) => {
        if (!cancelled) setError((e as Error).message);
      });
    return () => {
      cancelled = true;
    };
  }, [batchId, invalidCount]);

  if (invalidCount <= 0) return null;

  return (
    <div className="panel panel-pad section-gap">
      <div className="panel-title">Data quality</div>
      <p className="metric-sub">
        {invalidCount} record{invalidCount !== 1 ? "s" : ""} failed source validation (bad amount
        or date, missing reference, invalid currency or field format). These are data-quality
        problems rather than reconciliation failures — the records were excluded from matching
        and their values were never silently modified.
      </p>
      {error && <div className="history-empty">Could not load details: {error}</div>}
      {data && data.records.length > 0 && (
        <>
          <button
            type="button"
            className="tech-evidence-toggle"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
          >
            {expanded ? "Hide" : "Show"} invalid records ({data.records.length}) {expanded ? "▴" : "▾"}
          </button>
          {expanded && (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Source</th>
                    <th>Record</th>
                    <th>Amount</th>
                    <th>Date</th>
                    <th>Validation errors</th>
                  </tr>
                </thead>
                <tbody>
                  {data.records.map((r) => (
                    <tr key={r.transaction_id}>
                      <td>{r.source || "—"}</td>
                      <td className="mono">{r.source_record_id || r.transaction_id}</td>
                      <td className="mono">{r.amount != null ? formatMoney(r.amount, r.currency) : "—"}</td>
                      <td className="mono">{r.transaction_date || "—"}</td>
                      <td>{r.validation_errors.length ? r.validation_errors.join("; ") : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function QABox({ batchId }: { batchId: string }) {
  const [question, setQuestion] = useState("");
  const [history, setHistory] = useState<QAResponse[]>([]);
  const [busy, setBusy] = useState(false);

  async function ask(q: string) {
    if (!q.trim() || busy) return;
    setBusy(true);
    try {
      const res = await askQuestion(batchId, q);
      setHistory((prev) => [res, ...prev]);
      setQuestion("");
    } catch (e) {
      setHistory((prev) => [{ question: q, answer: `Error: ${(e as Error).message}`, data: null }, ...prev]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="section-gap panel panel-pad">
      <div className="panel-title">Ask about this batch</div>
      <div className="qa-input-row">
        <input
          className="qa-input"
          value={question}
          placeholder="e.g. how many exceptions do I have?"
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && ask(question)}
        />
        <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => ask(question)}>
          Ask
        </button>
      </div>
      <div className="qa-suggestions">
        {SUGGESTED_QUESTIONS.map((q) => (
          <button key={q} className="filter-chip" onClick={() => ask(q)}>
            {q}
          </button>
        ))}
      </div>
      {history.length > 0 && (
        <div className="qa-history">
          {history.map((h, i) => (
            <div className="qa-entry" key={i}>
              <div className="qa-question">{h.question}</div>
              <div className="qa-answer">{h.answer}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function ResultsDashboard() {
  const { batchId } = useParams<{ batchId: string }>();
  const [batch, setBatch] = useState<BatchSummary | null>(null);
  const [accuracy, setAccuracy] = useState<AccuracyReport | null>(null);
  const [exceptions, setExceptions] = useState<MatchOut[] | null>(null);
  const [chains, setChains] = useState<EventChain[] | null>(null);
  const [forecast, setForecast] = useState<CashForecastResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!batchId) return;
    let cancelled = false;
    setError(null);
    // Core batch data drives the whole page — a failure here is fatal
    // (with Retry). Supplementary feeds power individual story sections
    // and degrade quietly when absent. Nothing is fabricated.
    Promise.all([getBatch(batchId), getAccuracy(batchId)])
      .then(([b, a]) => {
        if (!cancelled) {
          setBatch(b);
          setAccuracy(a);
        }
      })
      .catch((e) => {
        if (!cancelled) setError((e as Error).message);
      });
    getExceptions(batchId)
      .then((res) => {
        if (!cancelled) setExceptions(res.matches);
      })
      .catch(() => {});
    getGraph(batchId)
      .then((res) => {
        if (!cancelled) setChains(res.chains);
      })
      .catch(() => {});
    getForecast(batchId)
      .then((res) => {
        if (!cancelled) setForecast(res);
      })
      .catch(() => {
        // No forecast run yet — the KPI shows a prompt instead of a number.
      });
    return () => {
      cancelled = true;
    };
  }, [batchId, reloadKey]);

  if (error) {
    return (
      <div className="page">
        <div className="page-header">
          <h1>Overview</h1>
        </div>
        <ErrorBlock
          context="Unable to load reconciliation results."
          message={error}
          onRetry={() => setReloadKey((k) => k + 1)}
        />
      </div>
    );
  }

  if (!batch) {
    return (
      <div className="page">
        <LoadingBlock message="Loading reconciliation results…" />
      </div>
    );
  }

  const breakdown = batch.stage_breakdown || {
    exact: 0, fee_aware: 0, many_to_one: 0, one_to_many: 0,
    fuzzy: 0, semantic: 0, refund: 0, llm: 0, unresolved: 0,
  };
  const total = batch.bank_count + batch.processor_count + batch.erp_count;
  const reconciledAmount =
    batch.control_totals && typeof batch.control_totals.reconciled_value === "number"
      ? batch.control_totals.reconciled_value
      : null;

  return (
    <div className="page">
      <div className="page-header">
        <h1>Overview</h1>
        <p>
          Batch <span className="mono">{batch.batch_id}</span> — {batch.bank_count} bank rows ×{" "}
          {batch.processor_count} processor rows × {batch.erp_count} ERP rows.{" "}
          <Link to={`/graph/${batch.batch_id}`}>View money flow →</Link>
        </p>
      </div>

      {batch.failover_count > 0 ? (
        <div className="failover-banner">
          ⚠ {batch.failover_count} LLM batch{batch.failover_count !== 1 ? "es" : ""} could not be
          served by the primary Groq provider — {batch.llm_call_count > 0 ? "rerouted to Gemini" : "the offline heuristic"} stepped
          in. The pipeline kept running without dropping work.
        </div>
      ) : (
        <div className="failover-banner calm">
          ✓ Every batch was served by the primary LLM provider this run — no failover needed.
        </div>
      )}

      <div className="metrics-grid">
        <div className="panel metric-card hero">
          <div className="metric-value accent">{pct(batch.match_rate)}</div>
          <div className="metric-label">Match rate</div>
          <div className="metric-sub">
            {Math.round((batch.match_rate || 0) * total)} / {total} unique records closed
          </div>
          <div className="metric-track" aria-hidden="true">
            <div className="metric-track-fill" style={{ width: `${Math.min(100, (batch.match_rate || 0) * 100)}%` }} />
          </div>
        </div>
        <div className="panel metric-card">
          <div className="metric-value">{total}</div>
          <div className="metric-label">Transactions processed</div>
          <div className="metric-sub">
            {batch.bank_count} bank · {batch.processor_count} processor · {batch.erp_count} ERP
          </div>
        </div>
        <div className="panel metric-card">
          <div className="metric-value success">
            {reconciledAmount != null ? formatMoney(reconciledAmount) : "—"}
          </div>
          <div className="metric-label">Reconciled amount</div>
          <div className="metric-sub">Value proven across sources by matched decisions</div>
        </div>
        <div className="panel metric-card">
          <div className="metric-value warning">{breakdown.unresolved}</div>
          <div className="metric-label">Exceptions</div>
          <div className="metric-sub">
            <Link to={`/exceptions/${batch.batch_id}`}>Review queue →</Link>
          </div>
        </div>
      </div>

      <div className="metrics-grid">
        <div className="panel metric-card" style={{ boxShadow: "none" }}>
          <div className="metric-value warning">
            {forecast ? formatMoney(forecast.totals.at_risk) : "—"}
          </div>
          <div className="metric-label">Cash at risk</div>
          <div className="metric-sub">
            {forecast ? (
              <Link to={`/forecast/${batch.batch_id}`}>{forecast.horizon_days}-day outlook →</Link>
            ) : (
              <Link to={`/forecast/${batch.batch_id}`}>Run the cash outlook →</Link>
            )}
          </div>
        </div>
        {accuracy?.available && (
          <div className="panel metric-card" style={{ boxShadow: "none" }}>
            <div className="metric-value">{pct(accuracy.overall_f1)}</div>
            <div className="metric-label">AI accuracy (F1)</div>
            <div className="metric-sub">
              {pct(accuracy.overall_precision)} precision · {pct(accuracy.overall_recall)} recall vs answer key
            </div>
          </div>
        )}
        <div className="panel metric-card" style={{ boxShadow: "none" }}>
          <div className="metric-value">{formatMoney(batch.settlement_variance)}</div>
          <div className="metric-label">Settlement variance</div>
          <div className="metric-sub">Unexplained amount across amount-mismatch exceptions</div>
        </div>
        <div className="panel metric-card" style={{ boxShadow: "none" }}>
          <div className="metric-value">{batch.validation_status || "—"}</div>
          <div className="metric-label">Final validation</div>
          <div className="metric-sub">
            Audit completeness {batch.audit_completeness != null ? `${Math.round(batch.audit_completeness * 1000) / 10}%` : "—"}
            {batch.invalid_count ? ` · ${batch.invalid_count} invalid` : ""}
          </div>
        </div>
      </div>

      <div className="panel panel-pad">
        <div className="panel-title">Stage breakdown</div>
        <StageBar breakdown={breakdown} total={total} />
      </div>

      <div className="story-grid section-gap">
        <MoneyFlowStrip chains={chains} batchId={batch.batch_id} />
        <ExceptionsNeedingAttention exceptions={exceptions} batchId={batch.batch_id} />
      </div>

      <div className="story-grid section-gap">
        <CashImpact exceptions={exceptions} forecast={forecast} batchId={batch.batch_id} />
        <AgentPanel batch={batch} exceptions={exceptions} />
      </div>

      <DataQualityPanel batchId={batch.batch_id} invalidCount={batch.invalid_count || 0} />

      <div className="metrics-grid section-gap">
        <div className="panel metric-card" style={{ boxShadow: "none" }}>
          <div className="metric-value">{batch.throughput_per_sec ?? "—"}</div>
          <div className="metric-label">Records / sec</div>
          <div className="metric-sub">{batch.processing_ms ? `${batch.processing_ms} ms total` : "—"}</div>
        </div>
        <div className="panel metric-card" style={{ boxShadow: "none" }}>
          <div className="metric-value">{batch.llm_call_count}</div>
          <div className="metric-label">LLM calls made</div>
          <div className="metric-sub">{batch.llm_batched_call_count} were batched (multiple rows/call)</div>
        </div>
        <div className="panel metric-card" style={{ boxShadow: "none" }}>
          <div className="metric-value">{pct(batch.manual_review_reduction)}</div>
          <div className="metric-label">Manual review reduction on this benchmark</div>
          <div className="metric-sub">
            {total} transactions → {breakdown.unresolved} flagged for review
          </div>
        </div>
        <div className="panel metric-card" style={{ boxShadow: "none" }}>
          <div className="metric-value">{batch.pipeline_version || "—"}</div>
          <div className="metric-label">Pipeline / rules</div>
          <div className="metric-sub">
            rules {batch.rule_set_version || "—"} · norm {batch.normalization_version || "—"}
          </div>
        </div>
      </div>

      {accuracy?.available && (
        <div className="section-gap panel panel-pad">
          <div className="panel-title">Accuracy against answer key</div>
          <div className="metrics-grid" style={{ marginBottom: 18 }}>
            <div className="panel metric-card" style={{ boxShadow: "none" }}>
              <div className="metric-value">{pct(accuracy.overall_precision)}</div>
              <div className="metric-label">Overall precision</div>
            </div>
            <div className="panel metric-card" style={{ boxShadow: "none" }}>
              <div className="metric-value">{pct(accuracy.overall_recall)}</div>
              <div className="metric-label">Overall recall</div>
            </div>
            <div className="panel metric-card" style={{ boxShadow: "none" }}>
              <div className="metric-value">{pct(accuracy.overall_f1)}</div>
              <div className="metric-label">Overall F1</div>
            </div>
            <div className="panel metric-card" style={{ boxShadow: "none" }}>
              <div className="metric-value warning">{pct(accuracy.false_match_rate)}</div>
              <div className="metric-label">False match rate</div>
            </div>
            <div className="panel metric-card" style={{ boxShadow: "none" }}>
              <div className="metric-value warning">{pct(accuracy.missed_match_rate)}</div>
              <div className="metric-label">Missed match rate</div>
            </div>
          </div>

          <table className="data-table">
            <thead>
              <tr>
                <th>Stage</th>
                <th>Precision</th>
                <th>Recall</th>
                <th>Predicted matches</th>
              </tr>
            </thead>
            <tbody>
              {accuracy.per_stage.map((s) => (
                <tr key={s.stage}>
                  <td>
                    <span className={`stage-tag ${s.stage}`}>{s.stage}</span>
                  </td>
                  <td className="mono">{pct(s.precision)}</td>
                  <td className="mono">{pct(s.recall)}</td>
                  <td className="mono">{s.n_predicted}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="panel-title section-gap">LLM confidence calibration</div>
          <table className="data-table">
            <thead>
              <tr>
                <th>Confidence bucket</th>
                <th>Matches in bucket</th>
                <th>Actually correct</th>
              </tr>
            </thead>
            <tbody>
              {accuracy.calibration.map((c) => (
                <tr key={c.bucket}>
                  <td className="mono">{c.bucket}</td>
                  <td className="mono">{c.n}</td>
                  <td className="mono">{c.n ? pct(c.accuracy) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!accuracy?.available && (
        <div className="section-gap panel panel-pad">
          <div className="panel-title">Accuracy against answer key</div>
          <p style={{ color: "var(--muted)", margin: 0, fontSize: 13.5 }}>
            No answer key was supplied for this batch, so precision/recall can't be measured. Upload one
            alongside your sources to see this section populate.
          </p>
        </div>
      )}

      {batchId && <QABox batchId={batchId} />}
    </div>
  );
}
