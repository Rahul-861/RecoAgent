"""Final batch validator. Failures prevent a successful reconciliation status."""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Set, Tuple

from app.contract.schemas import DecisionState


FINAL_DECISIONS = {s.value for s in DecisionState}


def _consumption_axis(d: Dict[str, Any]) -> str:
    stage = d.get("match_stage") or ""
    if stage == "refund":
        return "refund"
    sources = {d.get("left_source"), d.get("right_source")}
    if "erp" in sources:
        return "ledger"
    return "settlement"


def validate_batch(
    records: List[Dict[str, Any]],
    decisions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    issues: List[str] = []

    consumed: List[Tuple[str, str, str]] = []
    for d in decisions:
        if d.get("status") != "matched" and d.get("decision") not in (
            DecisionState.MATCH.value, DecisionState.PARTIAL_MATCH.value,
        ):
            # Partial matches still consume involved rows.
            if d.get("decision") != DecisionState.PARTIAL_MATCH.value:
                continue
        axis = _consumption_axis(d)
        for tid in d.get("left_txn_ids") or []:
            consumed.append((d.get("left_source"), tid, axis))
        for tid in d.get("right_txn_ids") or []:
            consumed.append((d.get("right_source"), tid, axis))

    counts = Counter(consumed)
    # A bank deposit may close processor settlement and ERP ledger.
    # A processor payment may have both a net payout and a refund debit.
    doubles = [k for k, n in counts.items() if n > 1 and k[0] and k[1]]
    if doubles:
        issues.append(f"Duplicate consumption: {doubles[:8]}")

    accounted: Set[Tuple[str, str]] = set()
    for d in decisions:
        for tid in d.get("left_txn_ids") or []:
            accounted.add((d.get("left_source"), tid))
        for tid in d.get("right_txn_ids") or []:
            accounted.add((d.get("right_source"), tid))

    missing_state = []
    for r in records:
        key = (r.get("source"), r.get("source_record_id"))
        if key not in accounted and r.get("is_valid", True):
            missing_state.append(key)
    if missing_state:
        issues.append(f"Records without final state: {missing_state[:8]}")

    for d in decisions:
        if d.get("status") == "matched" and not d.get("evidence"):
            issues.append(f"Match without evidence: {d.get('left_txn_ids')}")
            break
        if d.get("status") == "exception" and not d.get("exception_category") and not d.get("exception_type"):
            issues.append(f"Exception without category: {d.get('left_txn_ids')}")
            break
        if d.get("match_stage") == "llm" and d.get("status") == "matched":
            cand_ids = set(d.get("candidate_ids") or [])
            right_ids = d.get("right_txn_ids") or []
            if cand_ids and right_ids and not set(right_ids).issubset(cand_ids):
                issues.append("AI decision used a candidate ID that was not provided")
                break

    totals = _control_totals(records, decisions)
    unexplained = abs(
        (totals["source_total"] or 0)
        - (totals["reconciled_value"] or 0)
        - (totals["unmatched_value"] or 0)
        - (totals["exception_value"] or 0)
    )
    # Allow tiny float residue.
    if unexplained > 0.05:
        totals["unexplained_difference"] = round(unexplained, 2)
    else:
        totals["unexplained_difference"] = 0.0

    passed = len(issues) == 0
    return {
        "validation_status": "PASSED" if passed else "VALIDATION_FAILED",
        "issues": issues,
        "control_totals": totals,
    }


def _signed_amount(row: Dict[str, Any]) -> float:
    return float(row.get("amount") or row.get("net_amount") or row.get("gross_amount") or 0)


def _control_totals(records: List[Dict[str, Any]], decisions: List[Dict[str, Any]]) -> Dict[str, Any]:
    record_count = len(records)
    debit = sum(abs(_signed_amount(r)) for r in records if (_signed_amount(r) or 0) < 0)
    credit = sum(_signed_amount(r) for r in records if (_signed_amount(r) or 0) >= 0)
    total_abs = sum(abs(_signed_amount(r)) for r in records)
    source_total = round(sum(_signed_amount(r) for r in records), 2)

    matched_ids = set()
    unmatched_ids = set()
    exception_ids = set()
    for d in decisions:
        keys = [(d.get("left_source"), tid) for tid in d.get("left_txn_ids") or []]
        keys += [(d.get("right_source"), tid) for tid in d.get("right_txn_ids") or []]
        if d.get("status") == "matched":
            matched_ids.update(keys)
        elif d.get("decision") == DecisionState.UNMATCHED.value:
            unmatched_ids.update(keys)
        else:
            exception_ids.update(keys)

    by_key = {(r.get("source"), r.get("source_record_id")): r for r in records}

    def value_of(keys):
        return round(sum(abs(_signed_amount(by_key[k])) for k in keys if k in by_key), 2)

    return {
        "record_count": record_count,
        "total_debit": round(debit, 2),
        "total_credit": round(credit, 2),
        "total_absolute_amount": round(total_abs, 2),
        "source_total": source_total,
        "reconciled_value": value_of(matched_ids),
        "unmatched_value": value_of(unmatched_ids),
        "exception_value": value_of(exception_ids - matched_ids),
    }
