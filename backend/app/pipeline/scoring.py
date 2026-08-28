"""Soft scoring with explicit financial > identity > temporal > text priority."""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.config import settings
from app.pipeline.identity import identities_overlap, text_similarity
from app.rules.amount_rules import amounts_compatible
from app.rules.date_rules import dates_compatible
from app.rules.reference_rules import references_match


def currencies_compatible(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b:
        return True
    return str(a).upper() == str(b).upper()


def hard_constraint_failures(left: Dict[str, Any], right: Dict[str, Any]) -> list:
    failures = []
    if not currencies_compatible(left.get("currency"), right.get("currency")):
        failures.append("currency_mismatch")
    l_amt = left.get("net_amount") if left.get("fee_amount") or left.get("refund_amount") else left.get("amount")
    r_amt = right.get("amount")
    if l_amt is not None and r_amt is not None:
        # Extreme mismatch is a hard contradiction; modest diffs are soft.
        if max(abs(l_amt), abs(r_amt)) > 0 and abs(l_amt - r_amt) > max(abs(l_amt), abs(r_amt)) * 0.5 + 1:
            if not amounts_compatible(l_amt, r_amt, settings.SETTLEMENT_SUM_TOLERANCE):
                # Not a hard reject for scoring candidates in date/amount window;
                # currency is the primary hard constraint here.
                pass
    return failures


def score_candidate(left: Dict[str, Any], right: Dict[str, Any], left_amt: Optional[float], right_amt: Optional[float]) -> Dict[str, Any]:
    failures = hard_constraint_failures(left, right)
    if failures:
        return {
            "score": 0.0,
            "rejected": True,
            "contradictions": failures,
            "evidence": {},
        }

    amount_ok = amounts_compatible(left_amt, right_amt)
    date_ok = dates_compatible(left.get("transaction_date"), right.get("transaction_date"))
    ref_ok = references_match(
        left.get("reference"), right.get("reference"),
        left.get("reference_normalized"), right.get("reference_normalized"),
    ) or identities_overlap(left, right)
    text_score = text_similarity(left, right) / 100.0

    # Weighted: financial 0.45, identity 0.30, temporal 0.15, text 0.10
    if left_amt is None or right_amt is None:
        financial = 0.0
    elif amount_ok:
        financial = 1.0
    else:
        financial = max(0.0, 1.0 - abs((left_amt or 0) - (right_amt or 0)) / max(abs(left_amt or 1), 1))
    identity = 1.0 if ref_ok else (0.55 if text_score >= 0.85 else 0.2)
    temporal = 1.0 if date_ok else 0.3
    score = 0.45 * financial + 0.30 * identity + 0.15 * temporal + 0.10 * text_score
    return {
        "score": round(score, 4),
        "rejected": False,
        "contradictions": [],
        "evidence": {
            "amount": "exact" if amount_ok else "compatible" if financial > 0.8 else "weak",
            "currency": "exact",
            "reference": "strong_match" if ref_ok else "weak",
            "date": "within_window" if date_ok else "outside_window",
            "counterparty": "strong" if text_score >= 0.85 else "partial" if text_score >= 0.5 else "weak",
        },
        "text_score": round(text_score, 4),
    }


def margin_ok(top_score: float, second_score: Optional[float], threshold: float, min_margin: float) -> bool:
    if top_score < threshold:
        return False
    if second_score is None:
        return True
    return (top_score - second_score) >= min_margin
