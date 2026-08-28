from app.pipeline.duplicate_check import run_duplicate_check
from app.rules.duplicate_rules import reject_if_consumed


def test_duplicate_check_does_not_auto_pick():
    mmap = {
        "P1": [
            {"row": {"source_record_id": "B1", "amount": 10, "transaction_date": None, "counterparty": "a"}, "score": 90, "stage": "fuzzy"},
            {"row": {"source_record_id": "B2", "amount": 10, "transaction_date": None, "counterparty": "b"}, "score": 88, "stage": "fuzzy"},
        ]
    }
    out = run_duplicate_check(mmap, "processor")
    assert len(out) == 1
    assert out[0]["status"] == "exception"
    assert out[0]["exception_type"] == "duplicate"


def test_consumed_candidate_rejected():
    assert reject_if_consumed("B1", {"B1"})
    assert not reject_if_consumed("B2", {"B1"})
