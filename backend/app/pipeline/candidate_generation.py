"""Bounded, deterministic candidate generation. Does not decide matches."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from app.config import settings
from app.pipeline.scoring import score_candidate, currencies_compatible
from app.rules.amount_rules import amounts_compatible
from app.rules.date_rules import dates_compatible

Row = Dict[str, Any]
AmountFn = Callable[[Row], Optional[float]]


def generate_candidates(
    left: Row,
    right_rows: List[Row],
    left_amount_fn: AmountFn,
    right_amount_fn: AmountFn,
    max_candidates: Optional[int] = None,
) -> List[Dict[str, Any]]:
    cap = max_candidates or settings.MAX_CANDIDATES
    l_amt = left_amount_fn(left)
    scored = []
    for r in right_rows:
        if not currencies_compatible(left.get("currency"), r.get("currency")):
            continue
        r_amt = right_amount_fn(r)
        if l_amt is not None and r_amt is not None:
            # Keep amount-near or date-near records; drop distant noise.
            amount_near = amounts_compatible(l_amt, r_amt, max(settings.AMOUNT_TOLERANCE, abs(l_amt) * 0.05 + 1))
            date_near = dates_compatible(left.get("transaction_date"), r.get("transaction_date"))
            if not amount_near and not date_near:
                continue
        detail = score_candidate(left, r, l_amt, r_amt)
        if detail.get("rejected"):
            continue
        scored.append({
            "row": r,
            "id": r["source_record_id"],
            "score": detail["score"],
            "evidence": detail["evidence"],
            "contradictions": detail["contradictions"],
        })
    scored.sort(key=lambda x: (-x["score"], x["id"]))
    return scored[:cap]
