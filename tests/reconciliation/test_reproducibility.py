from datetime import date

from app.pipeline.matching_core import run_exact_match
from app.accuracy.metrics import fingerprint_decision, repeatability_rate
from app.pipeline.final_validation import validate_batch


def _row(sid, amount, ref, ccy="INR"):
    return {
        "source": "bank", "source_record_id": sid, "amount": amount, "reference": ref,
        "reference_normalized": ref.replace("-", "").upper() if ref else None,
        "currency": ccy, "transaction_date": date(2024, 1, 1),
        "counterparty": "x", "description": "x", "is_valid": True,
    }


def test_exact_match_deterministic_order():
    left = [_row("L1", 10, "ABC")]
    right = [_row("R2", 10, "ABC"), _row("R1", 10, "XYZ")]
    # only R2 has matching ref... wait R1 XYZ won't match. Use two same refs -> ambiguous remaining.
    right = [_row("R9", 10, "NO"), _row("R1", 10, "ABC")]
    m1, _, _ = run_exact_match(left, right, lambda r: r["amount"], lambda r: r["amount"], 0.01, 3)
    m2, _, _ = run_exact_match(left, list(reversed(right)), lambda r: r["amount"], lambda r: r["amount"], 0.01, 3)
    assert m1[0]["right"]["source_record_id"] == m2[0]["right"]["source_record_id"] == "R1"


def test_repeatability_fingerprint():
    a = [{"left_txn_ids": ["L1"], "right_txn_ids": ["R1"], "decision": "MATCH", "rule_id": "R001", "confidence": 1.0}]
    b = [{"left_txn_ids": ["L1"], "right_txn_ids": ["R1"], "decision": "MATCH", "rule_id": "R001", "confidence": 1.0}]
    assert repeatability_rate(a, b) == 1.0
    assert fingerprint_decision(a[0]) == fingerprint_decision(b[0])


def test_currency_conflict_not_matched():
    left = [_row("L1", 10, "ABC", "INR")]
    right = [_row("R1", 10, "ABC", "USD")]
    matches, rem_l, rem_r = run_exact_match(left, right, lambda r: r["amount"], lambda r: r["amount"], 0.01, 3)
    assert matches == []
    assert rem_l and rem_r


def test_final_validator_duplicate_consumption():
    records = [_row("L1", 10, "A"), _row("R1", 10, "A")]
    records[0]["source"] = "processor"
    records[1]["source"] = "bank"
    decisions = [
        {"status": "matched", "decision": "MATCH", "left_source": "processor", "left_txn_ids": ["L1"],
         "right_source": "bank", "right_txn_ids": ["R1"], "evidence": {"amount": "exact"}, "exception_category": None},
        {"status": "matched", "decision": "MATCH", "left_source": "processor", "left_txn_ids": ["L1"],
         "right_source": "bank", "right_txn_ids": ["R1"], "evidence": {"amount": "exact"}, "exception_category": None},
    ]
    result = validate_batch(records, decisions)
    assert result["validation_status"] == "VALIDATION_FAILED"
    assert any("Duplicate" in i for i in result["issues"])
