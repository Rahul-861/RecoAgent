"""Structured audit trail for every reconciliation decision."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from app.config import settings
from app.db import MatchResult, loads


def decision_audit_record(m: MatchResult) -> Dict[str, Any]:
    return {
        "batch_id": m.batch_id,
        "match_id": m.match_id,
        "transaction_id": (loads(m.left_txn_ids_json) or [None])[0],
        "matched_transaction_id": (loads(m.right_txn_ids_json) or [None])[0],
        "left_txn_ids": loads(m.left_txn_ids_json) or [],
        "right_txn_ids": loads(m.right_txn_ids_json) or [],
        "decision": getattr(m, "decision", None) or ("MATCH" if m.status == "matched" else "UNMATCHED"),
        "state": getattr(m, "state", None),
        "decision_stage": getattr(m, "decision_stage", None) or m.match_stage,
        "rule_id": getattr(m, "rule_id", None),
        "rule_set_version": getattr(m, "rule_set_version", None) or settings.RULE_SET_VERSION,
        "score": getattr(m, "top_score", None) or m.confidence,
        "confidence": m.confidence,
        "candidate_ids": loads(getattr(m, "candidate_ids_json", None)) or [],
        "evidence": loads(getattr(m, "evidence_json", None)),
        "contradictions": loads(getattr(m, "contradictions_json", None)) or [],
        "AI_used": bool(getattr(m, "ai_used", False) or m.match_stage == "llm"),
        "AI_provider": m.provider_used,
        "AI_model": settings.GROQ_MODEL if m.provider_used == "groq" else (
            settings.GEMINI_MODEL if m.provider_used == "gemini" else None
        ),
        "pipeline_version": getattr(m, "pipeline_version", None) or settings.PIPELINE_VERSION,
        "normalization_version": getattr(m, "normalization_version", None) or settings.NORMALIZATION_VERSION,
        "timestamp": (m.created_at.isoformat() if getattr(m, "created_at", None) else datetime.utcnow().isoformat()),
        "reason": m.reason,
        "exception_category": getattr(m, "exception_category", None) or m.exception_type,
        "top_score": getattr(m, "top_score", None),
        "second_score": getattr(m, "second_score", None),
        "score_margin": getattr(m, "score_margin", None),
    }


def audit_completeness(records: List[Dict[str, Any]]) -> float:
    if not records:
        return 1.0
    required = ["decision", "decision_stage", "evidence", "pipeline_version"]
    complete = 0
    for r in records:
        if all(r.get(k) not in (None, "", []) for k in required):
            complete += 1
    return round(complete / len(records), 4)
