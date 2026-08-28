import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getMemory } from "../api/client";
import type { LearnedRule, MemoryMapping, MemoryResponse } from "../types";
import { ErrorBlock, LoadingBlock } from "../components/StateBlocks";
import { exceptionLabel } from "../utils/evidenceFormatter";
import { formatDateTime } from "../utils/format";

const MEMORY_LOOP = [
  "Human resolution",
  "Approved mapping",
  "Reusable knowledge",
  "Future automation",
];

function shortBatch(batchId: string | null): string {
  if (!batchId) return "—";
  return batchId.length > 13 ? `${batchId.slice(0, 10)}…` : batchId;
}

function MappingsTable({
  mappings,
  batchId,
}: {
  mappings: MemoryMapping[];
  batchId: string;
}) {
  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead>
          <tr>
            <th>Approved mapping</th>
            <th>Field</th>
            <th>Source</th>
            <th>Target</th>
            <th>Amount</th>
            <th>Diff</th>
            <th>Approved by</th>
            <th>Approved</th>
            <th>Status</th>
            <th>Rule</th>
            <th>Last approved</th>
            <th>Origin</th>
          </tr>
        </thead>
        <tbody>
          {mappings.map((m) => (
            <tr key={m.id}>
              <td>
                <span className="mapping-pair">
                  <span className="mono">{m.raw_value}</span>
                  <span className="mapping-arrow">{String.fromCharCode(8594)}</span>
                  <span className="mono">{m.canonical_value}</span>
                </span>
              </td>
              <td>{m.mapping_kind}</td>
              <td className="mono">{m.source_record_id || m.source_transaction_id || "—"}</td>
              <td className="mono">{m.target_record_id || m.target_transaction_id || "—"}</td>
              <td className="mono">
                {m.source_amount && m.target_amount
                  ? `${m.source_amount} → ${m.target_amount}`
                  : m.source_amount
                  ? String(m.source_amount)
                  : m.target_amount
                  ? String(m.target_amount)
                  : "—"}
              </td>
              <td className="mono">
                {m.source_amount && m.target_amount
                  ? (m.source_amount - m.target_amount).toFixed(2)
                  : "—"}
              </td>
              <td className="mono">{m.reviewer || "—"}</td>
              <td className="mono">
                {m.approval_count} time{m.approval_count !== 1 ? "s" : ""}
              </td>
              <td>
                <span className={`memory-status memory-${m.status}`}>{m.status}</span>
              </td>
              <td className="mono">{m.rule_source || "—"}</td>
              <td>{formatDateTime(m.last_approved_at)}</td>
              <td>
                {shortBatch(m.origin_batch_id)}
                {(m.origin_batch_id === batchId || m.last_batch_id === batchId) && (
                  <span className="batch-flag">this batch</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RulesTable({ rules, batchId }: { rules: LearnedRule[]; batchId: string }) {
  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead>
          <tr>
            <th>Rule ID</th>
            <th>Rule name</th>
            <th>Version</th>
            <th>Approval status</th>
            <th>Origin exception</th>
            <th>Origin</th>
          </tr>
        </thead>
        <tbody>
          {rules.map((r) => (
            <tr key={r.rule_id}>
              <td className="mono">{r.rule_id}</td>
              <td>{r.name}</td>
              <td className="mono">
                v{r.version} · {r.times_approved} approval{r.times_approved !== 1 ? "s" : ""}
              </td>
              <td>
                <span className="memory-status memory-active">{r.approval_status.replace(/_/g, " ")}</span>
              </td>
              <td>{r.exception_type ? exceptionLabel(r.exception_type) : "—"}</td>
              <td>
                {shortBatch(r.origin_batch_id)}
                {r.origin_batch_id === batchId && <span className="batch-flag">this batch</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function MemoryPage() {
  const { batchId } = useParams<{ batchId: string }>();
  const [data, setData] = useState<MemoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!batchId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getMemory(batchId)
      .then((res) => {
        if (!cancelled) setData(res);
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

  if (!batchId) {
    return (
      <div className="page">
        <div className="error-banner">No batch selected.</div>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-header">
        <h1>Reconciliation memory</h1>
        <p>
          Every time a human resolves an exception, the counterparty and reference pairing
          they approved is recorded here as reusable knowledge — so repeated manual work
          decreases over time. Mappings shown are real recorded approvals from actual
          resolutions; nothing is simulated.
        </p>
      </div>

      <div className="panel panel-pad">
        <div className="panel-title">How memory is built</div>
        <div className="memory-loop">
          {MEMORY_LOOP.map((step, i) => (
            <span key={step} className="memory-loop-step">
              {i > 0 && <span className="memory-loop-arrow">→</span>}
              <span className="memory-loop-chip">{step}</span>
            </span>
          ))}
        </div>
        {data && (
          <div className="memory-totals">
            <span className="sev-pill sev-value">
              {data.totals.mappings} approved mapping{data.totals.mappings !== 1 ? "s" : ""}
            </span>
            <span className="sev-pill sev-value">
              {data.totals.approvals} human approval{data.totals.approvals !== 1 ? "s" : ""} recorded
            </span>
            <span className="sev-pill sev-value">
              {data.totals.rules} learned rule{data.totals.rules !== 1 ? "s" : ""}
            </span>
            {data.totals.from_this_batch > 0 && (
              <span className="sev-pill sev-medium">
                {data.totals.from_this_batch} approved in this batch
              </span>
            )}
          </div>
        )}
      </div>

      {error && (
        <ErrorBlock
          context="Unable to load reconciliation memory."
          message={error}
          onRetry={() => setReloadKey((k) => k + 1)}
        />
      )}

      {loading && !data && <LoadingBlock message="Loading reconciliation memory…" />}

      {data && (
        <>
          <div className="panel panel-pad section-gap">
            <div className="panel-title">Previously approved mappings</div>
            {data.mappings.length === 0 ? (
              <div className="empty-state">
                <h3>No approved mappings yet</h3>
                <p>
                  Memory fills as reviewers resolve exceptions.{" "}
                  <Link to={`/exceptions/${batchId}`}>Open the exception queue →</Link>
                </p>
              </div>
            ) : (
              <MappingsTable mappings={data.mappings} batchId={batchId} />
            )}
          </div>

          <div className="panel panel-pad section-gap">
            <div className="panel-title">Learned rules</div>
            {data.rules.length === 0 ? (
              <div className="empty-state">
                <h3>No learned rules yet</h3>
                <p>
                  Each human-approved mapping becomes a versioned rule with a real rule ID,
                  name and approval status — shown here once the first exception is resolved.
                </p>
              </div>
            ) : (
              <RulesTable rules={data.rules} batchId={batchId} />
            )}
          </div>

          <p className="metric-sub section-gap">
            Recorded knowledge for future automation. Matching logic itself is unchanged —
            these mappings document what humans approved, with the rule, version and
            resolution that produced them.
          </p>
        </>
      )}
    </div>
  );
}

