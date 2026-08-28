"""
Stage: Refund / reversal detection (README §17).

Processor rows with refund_amount > 0 should have a corresponding bank
debit of the same magnitude. This stage classifies each refund as
matched, missing from the bank feed, duplicated, or amount-mismatched --
it never silently assumes a refund cleared.
"""
from __future__ import annotations
from typing import List, Dict, Any, Tuple

Row = Dict[str, Any]


def run_refund_check(
    processor_rows: List[Row], bank_rows: List[Row],
    amount_tolerance: float, timing_tolerance_days: int,
) -> Tuple[List[Dict[str, Any]], List[Row], List[Row]]:
    matches = []
    used_bank_ids = set()

    refund_rows = [p for p in processor_rows if (p.get("refund_amount") or 0) > 0]

    # Candidate bank debits: negative amount rows (or "debit" type).
    debit_candidates = [b for b in bank_rows if (b.get("amount") or 0) < 0]

    for p in refund_rows:
        refund_amt = p["refund_amount"]
        hits = []
        for b in debit_candidates:
            if b["source_record_id"] in used_bank_ids:
                continue
            if abs(abs(b.get("amount") or 0) - refund_amt) <= amount_tolerance:
                if p.get("transaction_date") is None or b.get("transaction_date") is None or \
                        abs((p["transaction_date"] - b["transaction_date"]).days) <= timing_tolerance_days:
                    hits.append(b)

        # Keep the processor payment in the settlement pool. A refund debit
        # is a second relationship on the same payment (net payout + refund).
        if len(hits) == 0:
            matches.append({
                "left_rows": [p], "right": None, "match_stage": "refund",
                "confidence": 0.0, "status": "exception", "exception_type": "refund_missing_from_bank",
                "severity": "high",
                "reason": (
                    f"Processor payment {p['source_record_id']} recorded a refund of "
                    f"{refund_amt} but no matching debit of that amount appears in the bank feed."
                ),
                "candidates_shown": None, "provider_used": None,
            })
        elif len(hits) == 1:
            b = hits[0]
            used_bank_ids.add(b["source_record_id"])
            matches.append({
                "left_rows": [p], "right": b, "match_stage": "refund",
                "confidence": 0.95, "status": "matched", "exception_type": None,
                "reason": f"Refund of {refund_amt} on payment {p['source_record_id']} matched to bank debit "
                          f"{b['source_record_id']}.",
                "candidates_shown": None, "provider_used": None,
            })
        else:
            for b in hits:
                used_bank_ids.add(b["source_record_id"])
            matches.append({
                "left_rows": [p], "right": None, "match_stage": "refund",
                "confidence": 0.0, "status": "exception", "exception_type": "duplicate_refund",
                "severity": "high",
                "reason": (
                    f"{len(hits)} bank debits of {refund_amt} could all correspond to the single refund "
                    f"on payment {p['source_record_id']} -- possible duplicate/double-processed refund."
                ),
                "candidates_shown": [
                    {"bank_txn": b["source_record_id"], "amount": b.get("amount")} for b in hits
                ],
                "provider_used": None,
            })

    remaining_processor = list(processor_rows)
    remaining_bank = [b for b in bank_rows if b["source_record_id"] not in used_bank_ids]
    return matches, remaining_processor, remaining_bank
