"""Explicit reconciliation lifecycle. Reject contradictory combinations."""
from __future__ import annotations

from typing import Optional, Set

from app.contract.schemas import ReconciliationState, DecisionState

ALLOWED_TRANSITIONS = {
    ReconciliationState.UNPROCESSED: {ReconciliationState.VALIDATED, ReconciliationState.INVALID, ReconciliationState.ERROR},
    ReconciliationState.VALIDATED: {ReconciliationState.NORMALIZED, ReconciliationState.INVALID, ReconciliationState.ERROR},
    ReconciliationState.NORMALIZED: {ReconciliationState.CANDIDATES_FOUND, ReconciliationState.UNMATCHED, ReconciliationState.DUPLICATE, ReconciliationState.ERROR},
    ReconciliationState.CANDIDATES_FOUND: {ReconciliationState.EVALUATED, ReconciliationState.ERROR},
    ReconciliationState.EVALUATED: {
        ReconciliationState.MATCH, ReconciliationState.PARTIAL_MATCH,
        ReconciliationState.AMBIGUOUS, ReconciliationState.UNMATCHED,
        ReconciliationState.DUPLICATE, ReconciliationState.ERROR,
    },
    ReconciliationState.MATCH: {ReconciliationState.RECONCILED},
    ReconciliationState.PARTIAL_MATCH: {ReconciliationState.RECONCILED, ReconciliationState.EXCEPTION},
    ReconciliationState.AMBIGUOUS: {ReconciliationState.REVIEW, ReconciliationState.EXCEPTION},
    ReconciliationState.UNMATCHED: {ReconciliationState.EXCEPTION},
    ReconciliationState.DUPLICATE: {ReconciliationState.EXCEPTION},
    ReconciliationState.INVALID: {ReconciliationState.EXCEPTION},
    ReconciliationState.ERROR: {ReconciliationState.EXCEPTION},
    ReconciliationState.RECONCILED: set(),
    ReconciliationState.REVIEW: set(),
    ReconciliationState.EXCEPTION: set(),
}

CONTRADICTIONS = [
    {ReconciliationState.MATCH, ReconciliationState.INVALID},
    {ReconciliationState.RECONCILED, ReconciliationState.UNMATCHED},
    {ReconciliationState.MATCH, ReconciliationState.DUPLICATE},
]

DECISION_TO_STATE = {
    DecisionState.MATCH: ReconciliationState.MATCH,
    DecisionState.PARTIAL_MATCH: ReconciliationState.PARTIAL_MATCH,
    DecisionState.AMBIGUOUS: ReconciliationState.AMBIGUOUS,
    DecisionState.UNMATCHED: ReconciliationState.UNMATCHED,
    DecisionState.DUPLICATE: ReconciliationState.DUPLICATE,
    DecisionState.INVALID: ReconciliationState.INVALID,
    DecisionState.ERROR: ReconciliationState.ERROR,
}

TERMINAL = {
    ReconciliationState.RECONCILED,
    ReconciliationState.REVIEW,
    ReconciliationState.EXCEPTION,
    ReconciliationState.INVALID,
    ReconciliationState.ERROR,
}


class InvalidStateTransition(ValueError):
    pass


def transition(current: str, nxt: str) -> str:
    cur = ReconciliationState(current) if not isinstance(current, ReconciliationState) else current
    new = ReconciliationState(nxt) if not isinstance(nxt, ReconciliationState) else nxt
    if new == cur:
        return cur.value
    allowed = ALLOWED_TRANSITIONS.get(cur, set())
    if new not in allowed:
        raise InvalidStateTransition(f"Cannot transition {cur.value} -> {new.value}")
    return new.value


def final_state_for_decision(decision: str) -> str:
    d = DecisionState(decision) if not isinstance(decision, DecisionState) else decision
    mid = DECISION_TO_STATE[d]
    if mid == ReconciliationState.MATCH:
        return ReconciliationState.RECONCILED.value
    if mid == ReconciliationState.PARTIAL_MATCH:
        return ReconciliationState.RECONCILED.value
    if mid == ReconciliationState.AMBIGUOUS:
        return ReconciliationState.REVIEW.value
    return ReconciliationState.EXCEPTION.value


def decision_from_match(status: str, match_stage: str, exception_type: Optional[str]) -> str:
    if exception_type in ("invalid",) or status == "invalid":
        return DecisionState.INVALID.value
    if exception_type in ("duplicate", "duplicate_refund"):
        return DecisionState.DUPLICATE.value
    if exception_type in ("ambiguous",) or (exception_type == "duplicate" and match_stage == "unresolved"):
        if exception_type == "duplicate":
            return DecisionState.AMBIGUOUS.value
        return DecisionState.AMBIGUOUS.value
    if exception_type in ("partially_paid",):
        return DecisionState.PARTIAL_MATCH.value
    if status == "matched":
        return DecisionState.MATCH.value
    if exception_type in ("ambiguous",):
        return DecisionState.AMBIGUOUS.value
    return DecisionState.UNMATCHED.value
