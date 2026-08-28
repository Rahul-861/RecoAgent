import type { StageBreakdown } from "../types";

interface Props {
  breakdown: StageBreakdown;
  total: number;
}

const STAGES: { key: keyof StageBreakdown; label: string; color: string; cls: string }[] = [
  { key: "exact", label: "Exact", color: "var(--stage-exact)", cls: "exact" },
  { key: "fee_aware", label: "Fee-aware", color: "#0ea5a5", cls: "fee-aware" },
  { key: "many_to_one", label: "Many-to-one", color: "#6366f1", cls: "many-to-one" },
  { key: "one_to_many", label: "One-to-many", color: "#8b5cf6", cls: "one-to-many" },
  { key: "fuzzy", label: "Fuzzy", color: "var(--stage-fuzzy)", cls: "fuzzy" },
  { key: "semantic", label: "Semantic", color: "var(--stage-semantic)", cls: "semantic" },
  { key: "refund", label: "Refund", color: "#f97316", cls: "refund" },
  { key: "llm", label: "LLM", color: "var(--stage-llm)", cls: "llm" },
  { key: "unresolved", label: "Review queue", color: "var(--stage-unresolved)", cls: "unresolved" },
];

export default function StageBar({ breakdown, total }: Props) {
  const safeTotal = total || 1;
  return (
    <div className="ledger-tape">
      <div className="tape-strip">
        {STAGES.map((s) => {
          const count = breakdown[s.key] || 0;
          const pct = (count / safeTotal) * 100;
          if (pct === 0) return null;
          return (
            <div
              key={s.key}
              className="tape-segment"
              style={{ flexBasis: `${pct}%`, background: s.color }}
              title={`${s.label}: ${count}`}
            />
          );
        })}
      </div>
      <div className="tape-legend">
        {STAGES.map((s) => (
          <div className="tape-legend-item" key={s.key}>
            <span className="tape-dot" style={{ background: s.color }} />
            <div>
              <div className="tape-legend-value">{breakdown[s.key] || 0}</div>
              <div className="tape-legend-label">{s.label}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
