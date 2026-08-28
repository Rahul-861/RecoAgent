from datetime import date

from app.pipeline.settlement_match import run_many_to_one_settlement, run_one_to_many_invoice


def test_batch_settlement_many_to_one():
    processor = [
        {"source": "processor", "source_record_id": "P1", "settlement_id": "S1", "net_amount": 10, "fee_amount": 1, "gross_amount": 11, "transaction_date": date(2024, 1, 1)},
        {"source": "processor", "source_record_id": "P2", "settlement_id": "S1", "net_amount": 15, "fee_amount": 1, "gross_amount": 16, "transaction_date": date(2024, 1, 1)},
    ]
    bank = [
        {"source": "bank", "source_record_id": "B1", "amount": 25, "transaction_date": date(2024, 1, 1)},
    ]
    matches, rem_p, rem_b = run_many_to_one_settlement(processor, bank, 0.5, 3, 6)
    assert len(matches) == 1
    assert matches[0]["match_stage"] == "many_to_one"
    assert not rem_p and not rem_b


def test_partial_payment_one_to_many():
    erp = [{"source": "erp", "source_record_id": "E1", "invoice_id": "INV1", "reference": "INV1", "amount": 100, "transaction_date": date(2024, 1, 1)}]
    bank = [
        {"source": "bank", "source_record_id": "B1", "reference": "INV1", "amount": 40, "transaction_date": date(2024, 1, 2)},
        {"source": "bank", "source_record_id": "B2", "reference": "INV1", "amount": 40, "transaction_date": date(2024, 1, 3)},
    ]
    matches, rem_e, rem_b = run_one_to_many_invoice(erp, bank, 0.5, 30, 6)
    assert len(matches) == 1
    assert matches[0]["status"] == "exception"
    assert matches[0]["exception_type"] == "partially_paid"
