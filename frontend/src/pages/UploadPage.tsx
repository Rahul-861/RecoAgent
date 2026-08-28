import { useState, useRef, DragEvent } from "react";
import { useNavigate } from "react-router-dom";
import { uploadBatch, runReconciliation } from "../api/client";

function Dropzone({
  label,
  sub,
  file,
  onFile,
}: {
  label: string;
  sub: string;
  file: File | null;
  onFile: (f: File) => void;
}) {
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  function handleDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f) onFile(f);
  }

  return (
    <div
      className={`dropzone ${dragOver ? "dragover" : ""} ${file ? "filled" : ""}`}
      onClick={() => inputRef.current?.click()}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          inputRef.current?.click();
        }
      }}
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
      role="button"
      tabIndex={0}
      aria-label={`${label}: choose a CSV file`}
    >
      <div className="dropzone-label">{label}</div>
      <div className="dropzone-sub">{sub}</div>
      {file && <div className="dropzone-file">{file.name}</div>}
      <input
        ref={inputRef}
        type="file"
        accept=".csv"
        className="hidden-input"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
        }}
      />
    </div>
  );
}

export default function UploadPage() {
  const [bankFile, setBankFile] = useState<File | null>(null);
  const [processorFile, setProcessorFile] = useState<File | null>(null);
  const [erpFile, setErpFile] = useState<File | null>(null);
  const [answerKey, setAnswerKey] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState<"idle" | "uploading" | "reconciling">("idle");
  const navigate = useNavigate();

  const canRun = bankFile && processorFile && erpFile && !busy;

  async function handleRun() {
    if (!bankFile || !processorFile || !erpFile) return;
    setError(null);
    setBusy(true);
    try {
      setStage("uploading");
      const uploadRes = await uploadBatch(bankFile, processorFile, erpFile, answerKey);
      setStage("reconciling");
      await runReconciliation(uploadRes.batch_id);
      navigate(`/dashboard/${uploadRes.batch_id}`);
    } catch (e) {
      setError((e as Error).message || "Upload failed. Check the backend is running.");
    } finally {
      setBusy(false);
      setStage("idle");
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <h1>Run a reconciliation batch</h1>
        <p>
          Upload your bank statement, payment processor export, and ERP/ledger export for the same
          period. ReconAgent normalizes all three into one canonical schema, matches what it can
          prove — including fee-aware, many-to-one settlement, one-to-many invoice, and refund
          relationships — and hands you a short, explained list of what actually needs a human.
        </p>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="panel panel-pad">
        <div className="panel-title">Required sources</div>
        <div className="dropzone-grid dropzone-grid-3">
          <Dropzone
            label="Bank statement"
            sub="CSV with amount, date, reference / description"
            file={bankFile}
            onFile={setBankFile}
          />
          <Dropzone
            label="Payment processor export"
            sub="CSV with gross, fee, refund, net amount, settlement_id"
            file={processorFile}
            onFile={setProcessorFile}
          />
          <Dropzone
            label="ERP / general ledger export"
            sub="CSV with invoice_id, amount, reference"
            file={erpFile}
            onFile={setErpFile}
          />
        </div>

        <div className="optional-zone">
          <div className="panel-title" style={{ marginBottom: 10 }}>
            Optional — answer key
          </div>
          <Dropzone
            label="Ground-truth answer key"
            sub="Enables measured precision / recall / F1 / calibration on the dashboard"
            file={answerKey}
            onFile={setAnswerKey}
          />
        </div>

        <button className="btn btn-primary" disabled={!canRun} onClick={handleRun}>
          {busy && <span className="spinner" />}
          {stage === "uploading" && "Uploading…"}
          {stage === "reconciling" && "Running reconciliation pipeline…"}
          {stage === "idle" && "Run reconciliation"}
        </button>
      </div>

      <div className="section-gap panel panel-pad">
        <div className="panel-title">What happens next</div>
        <ol className="pipeline-steps">
          <li className="pipeline-step">
            <div className="pipeline-step-n">01 · Refunds &amp; batches</div>
            <p>Refunds clear against bank debits. Settlement batches and split invoices group structurally, not by coincidence.</p>
          </li>
          <li className="pipeline-step">
            <div className="pipeline-step-n">02 · Exact / fee-aware</div>
            <p>Payment IDs, invoice IDs, and net-after-fee amounts close the high-confidence 1:1 relationships first.</p>
          </li>
          <li className="pipeline-step">
            <div className="pipeline-step-n">03 · Fuzzy / semantic</div>
            <p>Name drift, legal suffixes, and description overlap are scored together — duplicates still go to review.</p>
          </li>
          <li className="pipeline-step">
            <div className="pipeline-step-n">04 · LLM leftovers</div>
            <p>Only ambiguous remainder is adjudicated. Every record ends as a match or an explained exception.</p>
          </li>
        </ol>
      </div>
    </div>
  );
}
