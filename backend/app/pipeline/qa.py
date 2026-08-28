"""
Natural-language reconciliation Q&A (README §29).

Deliberately NOT a free-form LLM chat layer: it recognizes a set of
common controller questions (counts, exception breakdowns, high-risk
items, per-source status) and answers them directly from the already-
computed batch/match data, so the answer is always exactly what the
dashboard would show -- no hallucination risk, no extra LLM cost per
question. If a question doesn't match a known pattern, it says so
plainly instead of guessing.
"""
from __future__ import annotations
from typing import Dict, Any
from sqlalchemy.orm import Session

from app.db import Batch, MatchResult, loads

EXCEPTION_TYPE_WORDS = [
    "duplicate", "amount_mismatch", "timing_difference", "missing_counterpart",
    "refund_missing_from_bank", "duplicate_refund", "ambiguous", "partially_paid", "overpaid",
]


def answer_question(db: Session, batch_id: str, question: str) -> Dict[str, Any]:
    q = question.lower().strip()
    batch = db.get(Batch, batch_id)
    if not batch:
        return {"answer": "I couldn't find that batch.", "data": None}

    matches = db.query(MatchResult).filter(MatchResult.batch_id == batch_id).all()
    exceptions = [m for m in matches if m.status == "exception"]
    matched = [m for m in matches if m.status == "matched"]

    # exceptions / review-related questions
    if any(w in q for w in ["exception", "unresolved", "review queue", "need review", "flagged"]):
        for etype in EXCEPTION_TYPE_WORDS:
            if etype.replace("_", " ") in q or etype in q:
                subset = [m for m in exceptions if m.exception_type == etype]
                return {
                    "answer": f"{len(subset)} exception(s) of type '{etype}'.",
                    "data": [{"match_id": m.match_id, "reason": m.reason} for m in subset[:20]],
                }
        by_type: Dict[str, int] = {}
        for m in exceptions:
            by_type[m.exception_type or "unclassified"] = by_type.get(m.exception_type or "unclassified", 0) + 1
        breakdown = ", ".join(f"{v} {k}" for k, v in sorted(by_type.items(), key=lambda x: -x[1]))
        return {
            "answer": f"{len(exceptions)} exception(s) out of {len(matches)} evaluated relationships. "
                      f"Breakdown: {breakdown or 'none'}.",
            "data": by_type,
        }

    if "high risk" in q or "high-risk" in q or "risk" in q:
        high_risk = [m for m in exceptions if m.severity == "high"]
        return {
            "answer": f"{len(high_risk)} high-risk exception(s) currently open.",
            "data": [{"match_id": m.match_id, "type": m.exception_type, "reason": m.reason}
                     for m in high_risk[:20]],
        }

    if "match rate" in q or ("how many" in q and "match" in q):
        return {
            "answer": f"Match rate is {round((batch.match_rate or 0) * 100, 1)}% "
                      f"({len(matched)} of {len(matches)} evaluated relationships resolved automatically).",
            "data": {"match_rate": batch.match_rate},
        }

    if "manual review" in q or "workload" in q:
        return {
            "answer": f"Manual review reduction is {round((batch.manual_review_reduction or 0) * 100, 1)}% -- "
                      f"{len(exceptions)} item(s) still need a human.",
            "data": {"manual_review_reduction": batch.manual_review_reduction},
        }

    if "throughput" in q or "how fast" in q or "how long" in q:
        return {
            "answer": f"Processed in {round(batch.processing_ms or 0, 1)} ms "
                      f"({round(batch.throughput_per_sec or 0, 1)} records/sec).",
            "data": {"processing_ms": batch.processing_ms, "throughput_per_sec": batch.throughput_per_sec},
        }

    if "settlement variance" in q or ("cash" in q and "variance" in q):
        return {
            "answer": f"Settlement variance (unexplained bank-vs-processor difference) is "
                      f"{batch.settlement_variance if batch.settlement_variance is not None else 'not available'}.",
            "data": {"settlement_variance": batch.settlement_variance},
        }

    if "llm" in q and ("call" in q or "usage" in q or "many" in q):
        return {
            "answer": f"{batch.llm_call_count} LLM call(s) total, {batch.llm_batched_call_count} of them "
                      f"batched (>1 row/call), with {batch.failover_count} failover(s) to the backup provider.",
            "data": {"llm_call_count": batch.llm_call_count, "failover_count": batch.failover_count},
        }

    if "refund" in q:
        refund_matches = [m for m in matches if m.match_stage == "refund"]
        missing = [m for m in refund_matches if m.exception_type == "refund_missing_from_bank"]
        return {
            "answer": f"{len(refund_matches)} refund(s) processed; {len(missing)} not yet reflected in the bank feed.",
            "data": [{"match_id": m.match_id, "reason": m.reason} for m in refund_matches[:20]],
        }

    return {
        "answer": (
            "I can answer questions about match rate, exceptions (by type), high-risk items, "
            "manual review reduction, throughput, refunds, settlement variance, and LLM usage for this "
            "batch. Try rephrasing your question around one of those."
        ),
        "data": None,
    }
