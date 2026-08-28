"""Central exception taxonomy and severity rules."""
from __future__ import annotations

from app.contract.schemas import ExceptionCategory, ExceptionSeverity

LEGACY_TYPE_TO_CATEGORY = {
    "duplicate": ExceptionCategory.MULTIPLE_CANDIDATES,
    "missing_counterpart": ExceptionCategory.UNMATCHED_SOURCE,
    "amount_mismatch": ExceptionCategory.AMOUNT_MISMATCH,
    "timing_difference": ExceptionCategory.DATE_MISMATCH,
    "ambiguous": ExceptionCategory.MULTIPLE_CANDIDATES,
    "unidentified_cash": ExceptionCategory.UNMATCHED_TARGET,
    "refund_missing_from_bank": ExceptionCategory.REFUND,
    "duplicate_refund": ExceptionCategory.DUPLICATE,
    "partially_paid": ExceptionCategory.PARTIAL_PAYMENT,
    "overpaid": ExceptionCategory.AMOUNT_MISMATCH,
    "invalid": ExceptionCategory.INVALID_RECORD,
    "currency_mismatch": ExceptionCategory.CURRENCY_MISMATCH,
    "validation_failed": ExceptionCategory.VALIDATION_FAILED,
}

CATEGORY_SEVERITY = {
    ExceptionCategory.INVALID_RECORD: ExceptionSeverity.HIGH,
    ExceptionCategory.UNMATCHED_SOURCE: ExceptionSeverity.MEDIUM,
    ExceptionCategory.UNMATCHED_TARGET: ExceptionSeverity.MEDIUM,
    ExceptionCategory.AMOUNT_MISMATCH: ExceptionSeverity.MEDIUM,
    ExceptionCategory.DATE_MISMATCH: ExceptionSeverity.LOW,
    ExceptionCategory.CURRENCY_MISMATCH: ExceptionSeverity.HIGH,
    ExceptionCategory.REFERENCE_MISMATCH: ExceptionSeverity.MEDIUM,
    ExceptionCategory.MISSING_REFERENCE: ExceptionSeverity.LOW,
    ExceptionCategory.DUPLICATE: ExceptionSeverity.HIGH,
    ExceptionCategory.MULTIPLE_CANDIDATES: ExceptionSeverity.HIGH,
    ExceptionCategory.PARTIAL_PAYMENT: ExceptionSeverity.MEDIUM,
    ExceptionCategory.MISSING_SETTLEMENT: ExceptionSeverity.MEDIUM,
    ExceptionCategory.FEE_MISMATCH: ExceptionSeverity.MEDIUM,
    ExceptionCategory.REFUND: ExceptionSeverity.HIGH,
    ExceptionCategory.CHARGEBACK: ExceptionSeverity.HIGH,
    ExceptionCategory.AGGREGATION_REQUIRED: ExceptionSeverity.MEDIUM,
    ExceptionCategory.AI_UNCERTAIN: ExceptionSeverity.MEDIUM,
    ExceptionCategory.VALIDATION_FAILED: ExceptionSeverity.CRITICAL,
    ExceptionCategory.SYSTEM_ERROR: ExceptionSeverity.CRITICAL,
}


def severity_for(category: ExceptionCategory) -> ExceptionSeverity:
    return CATEGORY_SEVERITY.get(category, ExceptionSeverity.MEDIUM)
