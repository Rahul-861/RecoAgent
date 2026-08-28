from app.exceptions.classifier import classify_exception
from app.exceptions.taxonomy import severity_for
from app.contract.schemas import ExceptionCategory, ExceptionSeverity
from app.exceptions.lifecycle import map_review_status


def test_taxonomy_mapping():
    cat, sev = classify_exception("amount_mismatch")
    assert cat == "AMOUNT_MISMATCH"
    assert sev == "MEDIUM"
    cat, sev = classify_exception("duplicate")
    assert cat == "MULTIPLE_CANDIDATES"
    cat, _ = classify_exception(None, "INVALID")
    assert cat == "INVALID_RECORD"


def test_severity_centralized():
    assert severity_for(ExceptionCategory.DUPLICATE) == ExceptionSeverity.HIGH
    assert severity_for(ExceptionCategory.DATE_MISMATCH) == ExceptionSeverity.LOW


def test_lifecycle_map():
    assert map_review_status("open") == "OPEN"
    assert map_review_status("resolved") == "RESOLVED"
    assert map_review_status("rejected") == "REJECTED"
