"""Attach centralized rule metadata to pipeline decisions."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.config import settings
from app.exceptions.classifier import classify_exception
from app.pipeline.state_machine import decision_from_match, final_state_for_decision
from app.rules.base import rule_for_stage


def relationship_type(left_ids: List[str], right_ids: List[str]) -> str:
    ln, rn = len(left_ids), len(right_ids)
    if ln > 1 and rn <= 1:
        return "MANY_TO_ONE"
    if ln <= 1 and rn > 1:
        return "ONE_TO_MANY"
    return "ONE_TO_ONE"


def enrich_decision(u: Dict[str, Any]) -> Dict[str, Any]:
    stage = u.get("match_stage") or "unresolved"
    status = u.get("status") or "matched"
    exception_type = u.get("exception_type")
    decision = u.get("decision") or decision_from_match(status, stage, exception_type)
    rule = rule_for_stage(stage)
    category, severity = classify_exception(exception_type, decision)
    if status == "exception" and not u.get("severity"):
        u["severity"] = (severity or "MEDIUM").lower() if severity else u.get("severity")
    elif severity and status == "exception":
        u["severity"] = severity.lower()

    left_ids = u.get("left_txn_ids") or []
    right_ids = u.get("right_txn_ids") or []
    evidence = u.get("evidence")
    if evidence is None:
        evidence = _default_evidence(stage, status)
    contradictions = u.get("contradictions") or []
    candidate_ids = u.get("candidate_ids")
    if candidate_ids is None:
        shown = u.get("candidates_shown") or []
        candidate_ids = []
        if isinstance(shown, list):
            for c in shown:
                if isinstance(c, dict):
                    candidate_ids.append(c.get("transaction_id") or c.get("payment_id") or c.get("bank_txn"))
        candidate_ids = [c for c in candidate_ids if c]

    out = dict(u)
    out["decision"] = decision
    out["state"] = final_state_for_decision(decision)
    out["decision_stage"] = "AI_ADJUDICATION" if stage == "llm" else "RULE_ENGINE"
    out["rule_id"] = u.get("rule_id") or (rule.rule_id if rule else None)
    out["rule_set_version"] = settings.RULE_SET_VERSION
    out["pipeline_version"] = settings.PIPELINE_VERSION
    out["normalization_version"] = settings.NORMALIZATION_VERSION
    out["evidence"] = evidence
    out["contradictions"] = contradictions
    out["candidate_ids"] = candidate_ids
    out["relationship_type"] = relationship_type(left_ids, right_ids)
    out["exception_category"] = category
    out["ai_used"] = stage == "llm" or bool(u.get("provider_used") in ("groq", "gemini"))
    return out


def _default_evidence(stage: str, status: str) -> Dict[str, Any]:
    if status != "matched":
        return {"stage": stage, "matched": False}
    mapping = {
        "exact": {"amount": "exact", "reference": "strong_match", "currency": "exact", "date": "within_window"},
        "fee_aware": {"amount": "exact_after_fee", "currency": "exact", "date": "within_window"},
        "many_to_one": {"amount": "sum_equals_settlement", "currency": "exact"},
        "one_to_many": {"amount": "sum_equals_invoice", "currency": "exact"},
        "refund": {"amount": "refund_equals_debit", "currency": "exact"},
        "fuzzy": {"amount": "exact", "counterparty": "fuzzy_match"},
        "semantic": {"amount": "exact", "counterparty": "semantic_match"},
        "llm": {"amount": "ai_interpreted", "note": "AI adjudication of unresolved candidates"},
    }
    return mapping.get(stage, {"stage": stage})
