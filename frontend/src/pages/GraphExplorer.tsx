import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { getGraph } from "../api/client";
import type { EventChain, GraphNode } from "../types";
import { ErrorBlock, LoadingBlock } from "../components/StateBlocks";
import { formatMoney } from "../utils/format";

const FLOW: { kind: GraphNode["kind"]; label: string }[] = [
  { kind: "order", label: "Order" },
  { kind: "payment", label: "Payment" },
  { kind: "settlement", label: "Settlement" },
  { kind: "bank", label: "Bank" },
  { kind: "erp", label: "ERP" },
];

const KIND_COLORS: Record<string, string> = {
  order: "#94a3b8",
  payment: "#2554C7",
  settlement: "#0ea5a5",
  bank: "#16a34a",
  erp: "#f97316",
};

function nodeByKind(chain: EventChain, kind: string): GraphNode | undefined {
  return chain.nodes.find((n) => n.kind === kind);
}

function edgeBetween(chain: EventChain, fromId?: string, toId?: string) {
  if (!fromId || !toId) return undefined;
  return chain.edges.find((e) => e.source_id === fromId && e.target_id === toId);
}

function amountDelta(from?: GraphNode, to?: GraphNode): number | null {
  if (from?.amount == null || to?.amount == null) return null;
  return Math.round((to.amount - from.amount) * 100) / 100;
}

function ChainCard({ chain }: { chain: EventChain }) {
  const present = FLOW.filter((s) => nodeByKind(chain, s.kind));
  const connected = present.length;
  const missingKinds = FLOW.filter((s) => s.kind !== "order" && !nodeByKind(chain, s.kind)).map((s) => s.label);
  const payment = nodeByKind(chain, "payment");
  const settlement = nodeByKind(chain, "settlement");
  const bank = nodeByKind(chain, "bank");
  const feeDelta = amountDelta(payment, settlement);

  return (
    <div className="panel panel-pad chain-card">
      <div className="chain-header">
        <span className="trace-pill">
          {chain.status === "complete" && missingKinds.length === 0
            ? "Complete money trail"
            : `${connected} / ${FLOW.length} sources connected`}
        </span>
        <span className={`chain-status chain-status-${chain.status}`}>
          {chain.status === "complete" && missingKinds.length === 0 ? "✓ Fully reconciled" : "⚠ Partial"}
        </span>
      </div>
      <div className="chain-flow canonical-flow">
        {FLOW.map((stage, i) => {
          const node = nodeByKind(chain, stage.kind);
          const prev = i > 0 ? nodeByKind(chain, FLOW[i - 1].kind) : undefined;
          const edge = node && prev ? edgeBetween(chain, prev.id, node.id) : undefined;
          const delta = amountDelta(prev, node);
          const missing = !node && stage.kind !== "order";
          const skipOrder = stage.kind === "order" && !node;
          if (skipOrder) {
            return (
              <span key={stage.kind} className="chain-node-wrap chain-optional">
                <span className="chain-arrow muted">→</span>
              </span>
            );
          }
          return (
            <span key={stage.kind} className="chain-node-wrap">
              {i > 0 && (
                <span className="chain-connector">
                  {delta != null && delta !== 0 && (
                    <span className="chain-fee">
                      {edge?.label || (delta < 0 ? `Gateway fee ${formatMoney(delta)}` : `Adjustment ${formatMoney(delta)}`)}
                    </span>
                  )}
                  {delta === 0 && edge?.label && <span className="chain-fee quiet">{edge.label}</span>}
                  <span className="chain-arrow">{missing ? "⇢" : "→"}</span>
                </span>
              )}
              {node ? (
                <span className="chain-node" style={{ borderColor: KIND_COLORS[node.kind] }}>
                  <span className="chain-node-kind" style={{ color: KIND_COLORS[node.kind] }}>
                    {stage.label}
                  </span>
                  <span className="chain-node-label">{node.label}</span>
                  {node.amount !== null && <span className="chain-node-amount mono">{formatMoney(node.amount)}</span>}
                  <span className="chain-node-status">{chain.status === "complete" ? "Traced" : "Present"}</span>
                </span>
              ) : (
                <span className="chain-node chain-missing">
                  <span className="chain-node-kind">? {stage.label}</span>
                  <span className="chain-node-label">Missing counterpart</span>
                </span>
              )}
            </span>
          );
        })}
      </div>
      {settlement && bank && (
        <div className="chain-recon-footer">
          <div className="panel-title">Settlement reconciliation</div>
          {payment && payment.amount != null && (
            <div className="fin-row">
              <span>Gross payment</span>
              <span className="mono">{formatMoney(payment.amount)}</span>
            </div>
          )}
          {feeDelta != null && feeDelta !== 0 && (
            <div className="fin-row">
              <span>{feeDelta < 0 ? "Gateway fee" : "Adjustment"}</span>
              <span className="mono">{formatMoney(feeDelta)}</span>
            </div>
          )}
          <div className="fin-row">
            <span>Expected settlement</span>
            <span className="mono">{formatMoney(settlement.amount)}</span>
          </div>
          <div className="fin-row">
            <span>Actual bank settlement</span>
            <span className="mono">{formatMoney(bank.amount)}</span>
          </div>
          <div className="fin-row fin-diff">
            <span>Difference</span>
            <span className="mono">{formatMoney(amountDelta(settlement, bank) || 0)}</span>
          </div>
          {chain.status === "complete" && Math.abs(amountDelta(settlement, bank) || 0) < 0.005 && (
            <div className="evidence-row evidence-success">✓ Fully reconciled</div>
          )}
        </div>
      )}
      {missingKinds.length > 0 && (
        <div className="metric-sub">Missing stage: {missingKinds.join(", ")}</div>
      )}
    </div>
  );
}

export default function GraphExplorer() {
  const { batchId } = useParams<{ batchId: string }>();
  const [chains, setChains] = useState<EventChain[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "complete" | "partial">("all");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!batchId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getGraph(batchId)
      .then((res) => {
        if (!cancelled) setChains(res.chains);
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
      <div className="page">
        <div className="page-header">
          <h1>Money Flow</h1>
        </div>
        <ErrorBlock
          context="Unable to load the event graph."
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
          <h1>Money Flow</h1>
        </div>
        <LoadingBlock message="Loading money flow…" />
      </div>
    );
  }

  const complete = chains.filter((c) => c.status === "complete").length;
  const filtered = filter === "all" ? chains : chains.filter((c) => c.status === filter);

  return (
    <div className="page">
      <div className="page-header">
        <h1>Money flow</h1>
        <p>
          Order → Payment → Settlement → Bank → ERP. Amount changes such as gateway fees appear on the
          connection. {complete} of {chains.length} payment chains are fully traced end-to-end.
        </p>
      </div>

      <div className="filter-chips">
        <button className={`filter-chip ${filter === "all" ? "active" : ""}`} onClick={() => setFilter("all")}>
          All ({chains.length})
        </button>
        <button
          className={`filter-chip ${filter === "complete" ? "active" : ""}`}
          onClick={() => setFilter("complete")}
        >
          Complete ({complete})
        </button>
        <button
          className={`filter-chip ${filter === "partial" ? "active" : ""}`}
          onClick={() => setFilter("partial")}
        >
          Partial ({chains.length - complete})
        </button>
      </div>

      {filtered.length === 0 ? (
        <div className="panel">
          <div className="empty-state">
            <h3>No chains to show</h3>
            <p>Run reconciliation on this batch first.</p>
          </div>
        </div>
      ) : (
        <div className="chain-list">
          {filtered.map((c) => (
            <ChainCard key={c.chain_id} chain={c} />
          ))}
        </div>
      )}
    </div>
  );
}
