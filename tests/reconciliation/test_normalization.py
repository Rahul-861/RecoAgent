from datetime import date

from app.pipeline.normalize import parse_amount, normalize_reference, normalize_counterparty, apply_canonical_fields
from app.pipeline.validate import validate_rows


def test_parse_amount_variants():
    assert parse_amount("₹10,000")[0] == 10000.0
    assert parse_amount("10000")[0] == 10000.0
    assert parse_amount("10000.00")[0] == 10000.0
    assert parse_amount("10,000.00")[0] == 10000.0


def test_reference_formatting_drift():
    _, a = normalize_reference("INV-00123")
    _, b = normalize_reference("INV00123")
    _, c = normalize_reference("Invoice #123")
    _, d = normalize_reference("invoice-123")
    assert a == b == c == d == "123"


def test_counterparty_legal_suffix():
    _, a = normalize_counterparty("ABC Pvt Ltd")
    _, b = normalize_counterparty("ABC PRIVATE LIMITED")
    _, c = normalize_counterparty("A.B.C. PVT. LTD.")
    assert a == b
    assert "LTD" not in a


def test_raw_record_preserved():
    row = apply_canonical_fields({
        "source": "bank", "source_record_id": "B1", "amount": "1,000.00",
        "currency": "inr", "reference": "INV-1", "counterparty": "Acme Ltd",
        "description": "Payment", "transaction_date": date(2024, 1, 1),
        "raw_row": {"orig": True},
    })
    assert row["raw_row"]["orig"] is True
    assert row["normalized_record"]["currency"] == "INR"
    assert row["normalization_version"]


def test_invalid_amount_classified():
    rows = validate_rows([{
        "source": "bank", "source_record_id": "X", "amount": None,
        "currency": "INR", "gross_amount": None, "net_amount": None,
    }])
    assert rows[0]["is_valid"] is False
    assert rows[0]["recon_state"] == "INVALID"
