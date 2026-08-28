import { buildDecisionNarrative } from "../utils/evidenceFormatter";

interface Props {
  reason?: string | null;
  decision?: string | null;
  left_txn_ids?: string[] | null;
  right_txn_ids?: string[] | null;
  match_stage?: string | null;
  exception_type?: string | null;
  title?: string;
}

export default function DecisionExplanation({ title = "Why this decision?", ...match }: Props) {
  return (
    <div className="decision-explanation">
      <div className="panel-title">{title}</div>
      <p>{buildDecisionNarrative(match)}</p>
    </div>
  );
}
