"""Permanent regression cases for previously specified failure modes."""
from datetime import date

from app.pipeline.matching_core import run_exact_match, run_fuzzy_semantic_match
from app.pipeline.normalize import parse_amount, normalize_reference
from app.pipeline.validate import validate_record


def test_fee_difference_uses_net():
    left = [{
        "source": "processor", "source_record_id": "P1", "amount": 105, "gross_amount": 105,
        "fee_amount": 5, "refund_amount": 0, "net_amount": 100, "reference": "R1",
        "currency": "INR", "transaction_date": date(2024, 1, 1),
    }]
    right = [{
        "source": "bank", "source_record_id": "B1", "amount": 100, "reference": "R1",
        "currency": "INR", "transaction_date": date(2024, 1, 2),
    }]
    matches, _, _ = run_exact_match(
        left, right, lambda r: r.get("net_amount"), lambda r: r.get("amount"), 0.01, 3
    )
    assert matches and matches[0]["match_stage"] == "fee_aware"


def test_date_lag_within_window():
    left = [{"source": "a", "source_record_id": "L", "amount": 10, "reference": "X", "currency": "INR", "transaction_date": date(2024, 1, 1)}]
    right = [{"source": "b", "source_record_id": "R", "amount": 10, "reference": "X", "currency": "INR", "transaction_date": date(2024, 1, 3)}]
    matches, _, _ = run_exact_match(left, right, lambda r: r["amount"], lambda r: r["amount"], 0.01, 3)
    assert matches


def test_same_description_different_amount_not_exact():
    left = [{"source": "a", "source_record_id": "L", "amount": 10, "reference": "X", "currency": "INR", "transaction_date": date(2024, 1, 1), "counterparty": "Acme"}]
    right = [{"source": "b", "source_record_id": "R", "amount": 999, "reference": "X", "currency": "INR", "transaction_date": date(2024, 1, 1), "counterparty": "Acme"}]
    matches, rem, _ = run_exact_match(left, right, lambda r: r["amount"], lambda r: r["amount"], 0.01, 3)
    assert not matches


def test_same_amount_different_reference_not_exact():
    left = [{"source": "a", "source_record_id": "L", "amount": 50, "reference": "AAA", "currency": "INR", "transaction_date": date(2024, 1, 1)}]
    right = [{"source": "b", "source_record_id": "R", "amount": 50, "reference": "BBB", "currency": "INR", "transaction_date": date(2024, 1, 1)}]
    matches, _, _ = run_exact_match(left, right, lambda r: r["amount"], lambda r: r["amount"], 0.01, 3)
    assert not matches


def test_missing_reference_is_not_exact_identity():
    left = [{"source": "a", "source_record_id": "L", "amount": 50, "reference": None, "currency": "INR", "transaction_date": date(2024, 1, 1)}]
    right = [{"source": "b", "source_record_id": "R", "amount": 50, "reference": None, "currency": "INR", "transaction_date": date(2024, 1, 1)}]
    matches, _, _ = run_exact_match(left, right, lambda r: r["amount"], lambda r: r["amount"], 0.01, 3)
    assert not matches


def test_multiple_candidates_go_to_fuzzy_multi_map():
    left = [{"source": "a", "source_record_id": "L", "amount": 10, "reference": "Z", "currency": "INR",
             "transaction_date": date(2024, 1, 1), "counterparty": "Acme Corp", "description": "Acme Corp"}]
    right = [
        {"source": "b", "source_record_id": "R1", "amount": 10, "reference": "A", "currency": "INR",
         "transaction_date": date(2024, 1, 1), "counterparty": "Acme Corp", "description": "Acme Corp"},
        {"source": "b", "source_record_id": "R2", "amount": 10, "reference": "B", "currency": "INR",
         "transaction_date": date(2024, 1, 1), "counterparty": "Acme Corp", "description": "Acme Corp"},
    ]
    matches, still, still_r, multi = run_fuzzy_semantic_match(
        left, right, lambda r: r["amount"], lambda r: r["amount"], 85, 0.8, 0.01, 3
    )
    assert not matches
    assert "L" in multi


def test_unsupported_currency_invalid():
    errs = validate_record({"source": "bank", "source_record_id": "1", "amount": 1, "currency": "XXX"}, set())
    assert any("currency" in e.lower() for e in errs)
