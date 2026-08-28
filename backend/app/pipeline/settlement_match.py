"""
Stage: Fee-aware + many-to-one/one-to-many settlement matching
(README §13 Fee-Aware Reconciliation, §14 Many-to-One, §15 One-to-Many,
§16 Partial Payments).

Runs BEFORE generic fuzzy/semantic matching so that legitimate batched
settlements (one bank deposit == sum of several processor payments minus
fees) are recognized structurally instead of falling through to fuzzy
text matching or the LLM.
"""
from __future__ import annotations
from itertools import combinations
from typing import List, Dict, Any, Tuple

from app.pipeline.identity import identity_tokens
from app.pipeline.scoring import currencies_compatible

Row = Dict[str, Any]


def _date_close(a, b, tolerance_days: int) -> bool:
    if a is None or b is None:
        return True
    return abs((a - b).days) <= tolerance_days


def run_many_to_one_settlement(
    processor_rows: List[Row], bank_rows: List[Row],
    sum_tolerance: float, timing_tolerance_days: int, max_group_size: int,
) -> Tuple[List[Dict[str, Any]], List[Row], List[Row]]:
    """
    Groups processor rows sharing an explicit settlement_id and looks for a
    single bank row whose amount equals the group's total net_amount. This
    is the safe, high-precision case -- the grouping key comes from the
    data itself, not from a numeric coincidence.

    (The no-settlement_id subset-sum fallback lives in
    `run_many_to_one_fallback_subset_sum` below and is intentionally run
    LAST in the pipeline, over only the small pool of genuinely unmatched
    leftovers -- running an unconstrained subset-sum search over the FULL
    unmatched pool before exact/fuzzy/LLM matching have had a chance to
    claim their 1:1 pairs produces false-positive groupings purely by
    numeric coincidence, which is worse than leaving the rows as
    exceptions for a human to review.)
    """
    matches = []
    used_bank_ids = set()
    used_payment_ids = set()

    by_settlement: Dict[str, List[Row]] = {}
    for p in processor_rows:
        key = p.get("settlement_id")
        if key:
            by_settlement.setdefault(key, []).append(p)

    for settlement_id, group in sorted(by_settlement.items(), key=lambda kv: kv[0]):
        group = sorted(group, key=lambda g: g["source_record_id"])
        if len(group) < 2:
            continue
        total_net = round(sum((g.get("net_amount") or 0.0) for g in group), 2)
        best_bank = None
        for b in bank_rows:
            if b["source_record_id"] in used_bank_ids:
                continue
            if not currencies_compatible(group[0].get("currency"), b.get("currency")):
                continue
            if abs((b.get("amount") or 0.0) - total_net) <= sum_tolerance:
                gdate = group[0].get("transaction_date")
                if _date_close(gdate, b.get("transaction_date"), timing_tolerance_days):
                    best_bank = b
                    break
        if best_bank is not None:
            used_bank_ids.add(best_bank["source_record_id"])
            for g in group:
                used_payment_ids.add(g["source_record_id"])
            fee_total = round(sum((g.get("fee_amount") or 0.0) for g in group), 2)
            gross_total = round(sum((g.get("gross_amount") or 0.0) for g in group), 2)
            matches.append({
                "left_rows": group, "right": best_bank, "match_stage": "many_to_one",
                "confidence": 0.97,
                "reason": (
                    f"{len(group)} processor payments in settlement {settlement_id} "
                    f"(gross {gross_total} - fees {fee_total} = net {total_net}) "
                    f"sum to one bank deposit of {best_bank.get('amount')}."
                ),
                "candidates_shown": [
                    {"payment_id": g["source_record_id"], "net_amount": g.get("net_amount")}
                    for g in group
                ],
                "provider_used": None,
            })

    remaining_processor = [p for p in processor_rows if p["source_record_id"] not in used_payment_ids]
    remaining_bank = [b for b in bank_rows if b["source_record_id"] not in used_bank_ids]
    return matches, remaining_processor, remaining_bank


def run_many_to_one_fallback_subset_sum(
    processor_rows: List[Row], bank_rows: List[Row],
    sum_tolerance: float, timing_tolerance_days: int, max_group_size: int,
) -> Tuple[List[Dict[str, Any]], List[Row], List[Row]]:
    """
    Bounded subset-sum search for batches with no shared settlement_id.
    Deliberately run LAST, after exact/fee-aware/fuzzy/semantic/LLM have
    already claimed their 1:1 matches, so this only ever searches the
    small residual pool of genuine leftovers -- keeping the combinatorial
    search (and its false-positive risk) bounded and low-stakes. Confidence
    is capped below the settlement_id-grouped case and flagged as inferred.
    """
    matches = []
    used_bank_ids = set()
    used_payment_ids = set()

    pool = [p for p in processor_rows if not p.get("settlement_id")]
    for b in bank_rows:
        b_amt = b.get("amount") or 0.0
        candidates = [
            p for p in pool
            if p["source_record_id"] not in used_payment_ids
            and _date_close(p.get("transaction_date"), b.get("transaction_date"), timing_tolerance_days)
        ]
        candidates.sort(key=lambda p: p["source_record_id"])
        if len(candidates) > 12:
            # Too large a pool for a bounded search to be trustworthy --
            # leave these as individual exceptions instead of guessing.
            continue
        found_group = None
        for size in range(2, min(max_group_size, len(candidates)) + 1):
            for combo in combinations(candidates, size):
                total = round(sum((c.get("net_amount") or 0.0) for c in combo), 2)
                if abs(total - b_amt) <= sum_tolerance:
                    found_group = combo
                    break
            if found_group:
                break
        if found_group:
            used_bank_ids.add(b["source_record_id"])
            for g in found_group:
                used_payment_ids.add(g["source_record_id"])
            total_net = round(sum((g.get("net_amount") or 0.0) for g in found_group), 2)
            matches.append({
                "left_rows": list(found_group), "right": b, "match_stage": "many_to_one",
                "confidence": 0.75,
                "reason": (
                    f"{len(found_group)} processor payments with no shared settlement_id "
                    f"sum to {total_net}, matching one bank deposit of {b_amt} "
                    f"(inferred grouping from remaining unmatched rows, not an explicit "
                    f"settlement batch -- verify before relying on this)."
                ),
                "candidates_shown": [
                    {"payment_id": g["source_record_id"], "net_amount": g.get("net_amount")}
                    for g in found_group
                ],
                "provider_used": None,
            })

    remaining_processor = [p for p in processor_rows if p["source_record_id"] not in used_payment_ids]
    remaining_bank = [b for b in bank_rows if b["source_record_id"] not in used_bank_ids]
    return matches, remaining_processor, remaining_bank


def run_one_to_many_invoice(
    erp_rows: List[Row], bank_rows: List[Row],
    sum_tolerance: float, timing_tolerance_days: int, max_group_size: int,
) -> Tuple[List[Dict[str, Any]], List[Row], List[Row]]:
    """
    One invoice (ERP row) paid via several bank credits (partial
    payments, README §15-16). Groups bank rows sharing the same reference
    / invoice_id pointing at one ERP row and checks whether they sum to
    the invoice amount -- classifying FULLY_RECONCILED / PARTIALLY_PAID /
    OVERPAID as appropriate.
    """
    matches = []
    used_bank_ids = set()
    used_erp_ids = set()

    bank_by_ref: Dict[str, List[Row]] = {}
    for b in bank_rows:
        keys = {(b.get("reference") or "").strip().lower(), (b.get("invoice_id") or "").strip().lower()}
        keys |= {t.lower() for t in identity_tokens(b)}
        for key in keys:
            if key:
                bank_by_ref.setdefault(key, []).append(b)

    for erp in erp_rows:
        keys = {
            (erp.get("invoice_id") or "").strip().lower(),
            (erp.get("reference") or "").strip().lower(),
        }
        keys |= {t.lower() for t in identity_tokens(erp)}
        group = []
        seen = set()
        for key in keys:
            if not key:
                continue
            for b in bank_by_ref.get(key, []):
                rid = b["source_record_id"]
                if rid in used_bank_ids or rid in seen:
                    continue
                if not currencies_compatible(erp.get("currency"), b.get("currency")):
                    continue
                seen.add(rid)
                group.append(b)
        if len(group) < 2:
            continue
        total_paid = round(sum((g.get("amount") or 0.0) for g in group), 2)
        invoice_amt = erp.get("amount") or 0.0
        if abs(total_paid - invoice_amt) <= sum_tolerance:
            status = "FULLY_RECONCILED"
        elif total_paid < invoice_amt:
            status = "PARTIALLY_PAID"
        else:
            status = "OVERPAID"

        used_erp_ids.add(erp["source_record_id"])
        for g in group:
            used_bank_ids.add(g["source_record_id"])
        matches.append({
            "left_rows": group, "right": erp, "match_stage": "one_to_many",
            "confidence": 0.95 if status == "FULLY_RECONCILED" else 0.7,
            "status": "matched" if status == "FULLY_RECONCILED" else "exception",
            "exception_type": None if status == "FULLY_RECONCILED" else status.lower(),
            "reason": (
                f"{len(group)} bank credits totalling {total_paid} against ERP invoice "
                f"{erp.get('invoice_id')} (amount {invoice_amt}) -> {status}."
            ),
            "candidates_shown": [
                {"bank_txn": g["source_record_id"], "amount": g.get("amount")} for g in group
            ],
            "provider_used": None,
        })

    remaining_erp = [e for e in erp_rows if e["source_record_id"] not in used_erp_ids]
    remaining_bank = [b for b in bank_rows if b["source_record_id"] not in used_bank_ids]
    return matches, remaining_erp, remaining_bank
