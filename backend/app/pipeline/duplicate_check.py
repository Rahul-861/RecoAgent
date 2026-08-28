"""
Duplicate detection (README §18).

Turns a multi-candidate map produced by any fuzzy/semantic pass into
explicit exceptions instead of silently auto-picking the "best" match --
this is the fraud-adjacent "too many matches" failure mode (double-
processed refund, duplicate payout) that naive best-match matching hides.
Source-agnostic: works for bank<->processor or bank<->erp candidate maps.
"""
from __future__ import annotations
from typing import Dict, List, Any


def run_duplicate_check(
    multi_candidate_map: Dict[str, List[Dict[str, Any]]],
    left_source: str,
) -> List[Dict[str, Any]]:
    exceptions = []
    for left_id, candidates in multi_candidate_map.items():
        candidate_rows = []
        for c in candidates:
            candidate_rows.append({
                "transaction_id": c["row"]["source_record_id"],
                "amount": c["row"].get("amount"),
                "date": str(c["row"].get("transaction_date")) if c["row"].get("transaction_date") else None,
                "counterparty": c["row"].get("counterparty"),
                "score": round(c["score"], 3),
                "stage": c["stage"],
            })
        exceptions.append({
            "left_source": left_source,
            "left_txn_id": left_id,
            "match_stage": "unresolved",
            "confidence": 0.0,
            "status": "exception",
            "exception_type": "duplicate",
            "severity": "high",
            "reason": (
                f"{len(candidates)} counterpart rows all cleared the match threshold for this "
                f"{left_source} transaction -- could indicate a duplicate/double-processed record. "
                f"Left for human review rather than auto-picking one."
            ),
            "candidates_shown": candidate_rows,
            "provider_used": None,
        })
    return exceptions
