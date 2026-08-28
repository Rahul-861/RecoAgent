"""Process-level consistency metrics helpers."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple


def fingerprint_decision(d: Dict[str, Any]) -> Tuple:
    return (
        tuple(sorted(d.get("left_txn_ids") or [])),
        tuple(sorted(d.get("right_txn_ids") or [])),
        d.get("decision") or d.get("status"),
        d.get("exception_category") or d.get("exception_type"),
        d.get("rule_id"),
        round(float(d.get("confidence") or 0), 4),
    )


def repeatability_rate(run_a: List[Dict[str, Any]], run_b: List[Dict[str, Any]]) -> float:
    if not run_a:
        return 1.0
    fa = set(fingerprint_decision(d) for d in run_a)
    fb = set(fingerprint_decision(d) for d in run_b)
    if not fa:
        return 1.0
    return round(len(fa & fb) / len(fa), 4)
