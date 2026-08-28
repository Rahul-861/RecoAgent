import { useParams } from "react-router-dom";
import AuditPanel from "../components/AuditPanel";

export default function AuditExplorer() {
  const { batchId } = useParams<{ batchId: string }>();

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
        <h1>Audit explorer</h1>
        <p>
          Every decision this batch made, with the rule/pipeline/normalization versions that produced
          it, the evidence behind it, and the full resolution history for anything a reviewer has
          touched. Expand a row for details.
        </p>
      </div>
      <AuditPanel batchId={batchId} />
    </div>
  );
}
