import { useState } from "react";

interface Props {
  evidence: unknown;
  contradictions?: unknown;
}

export default function TechnicalEvidence({ evidence, contradictions }: Props) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  if (evidence == null && (contradictions == null || (Array.isArray(contradictions) && contradictions.length === 0))) {
    return null;
  }

  const payload =
    contradictions == null || (Array.isArray(contradictions) && contradictions.length === 0)
      ? evidence
      : { evidence, contradictions };
  const text = JSON.stringify(payload, null, 2);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="tech-evidence">
      <button type="button" className="tech-evidence-toggle" onClick={() => setOpen((v) => !v)}>
        Technical evidence {open ? "▴" : "▾"}
      </button>
      {open && (
        <div className="tech-evidence-body">
          <button type="button" className="btn btn-ghost btn-sm tech-copy" onClick={copy}>
            {copied ? "Copied" : "Copy JSON"}
          </button>
          <pre className="tech-json">{text}</pre>
        </div>
      )}
    </div>
  );
}
