"""Map pipeline outcomes onto the standard exception taxonomy."""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from app.contract.schemas import DecisionState, ExceptionCategory, ExceptionSeverity
from app.exceptions.taxonomy import LEGACY_TYPE_TO_CATEGORY, severity_for


def classify_exception(
    exception_type: Optional[str],
    decision: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    if decision == DecisionState.INVALID.value:
        cat = ExceptionCategory.INVALID_RECORD
        return cat.value, severity_for(cat).value
    if not exception_type:
        if decision in (DecisionState.AMBIGUOUS.value,):
            cat = ExceptionCategory.MULTIPLE_CANDIDATES
            return cat.value, severity_for(cat).value
        if decision == DecisionState.DUPLICATE.value:
            cat = ExceptionCategory.DUPLICATE
            return cat.value, severity_for(cat).value
        if decision == DecisionState.UNMATCHED.value:
            cat = ExceptionCategory.UNMATCHED_SOURCE
            return cat.value, severity_for(cat).value
        return None, None
    key = exception_type.lower()
    cat = LEGACY_TYPE_TO_CATEGORY.get(key)
    if cat is None:
        cat = ExceptionCategory.SYSTEM_ERROR
    sev = severity_for(cat)
    return cat.value, sev.value


def exception_payload(
    *,
    exception_id: str,
    batch_id: str,
    transaction_id: str,
    category: str,
    severity: str,
    reason: str,
    evidence: Any,
    related_transaction_ids: list,
) -> Dict[str, Any]:
    return {
        "exception_id": exception_id,
        "batch_id": batch_id,
        "transaction_id": transaction_id,
        "category": category,
        "severity": severity,
        "status": "OPEN",
        "reason": reason,
        "evidence": evidence,
        "related_transaction_ids": related_transaction_ids,
        "created_at": None,
        "resolved_at": None,
        "resolution": None,
    }
