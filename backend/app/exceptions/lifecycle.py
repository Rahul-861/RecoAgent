"""Exception lifecycle: never delete history; map review actions to states."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.contract.schemas import ExceptionLifecycle

_REVIEW_TO_LIFECYCLE = {
    "open": ExceptionLifecycle.OPEN,
    "resolved": ExceptionLifecycle.RESOLVED,
    "rejected": ExceptionLifecycle.REJECTED,
    "in_review": ExceptionLifecycle.IN_REVIEW,
    "escalated": ExceptionLifecycle.ESCALATED,
}


def map_review_status(review_status: Optional[str]) -> str:
    key = (review_status or "open").lower()
    return _REVIEW_TO_LIFECYCLE.get(key, ExceptionLifecycle.OPEN).value


def apply_resolution(match, action: str, note: Optional[str], resolved_by: str = "reviewer", db=None):
    """
    Mutate a MatchResult in place (kept as a cheap "latest state" projection
    for the dashboard/exception-queue reads) and, when a `db` session is
    given, also append an immutable row to `exception_resolutions` so full
    resolution history survives even if the same match is reopened and
    resolved again (Definition of Done: "resolution history is preserved",
    now on a dedicated table rather than only on MatchResult).
    """
    if action not in ("resolved", "rejected", "escalated", "in_review"):
        raise ValueError("action must be resolved, rejected, escalated, or in_review")

    previous_lifecycle = match.exception_lifecycle

    match.review_status = "resolved" if action == "resolved" else (
        "rejected" if action == "rejected" else action
    )
    match.exception_lifecycle = map_review_status(match.review_status)
    match.resolution_note = note
    match.resolved_by = resolved_by
    match.resolved_at = datetime.utcnow()

    if db is not None:
        # Local import avoids a circular import between db.py and this module.
        from app.db import ExceptionResolution

        db.add(ExceptionResolution(
            match_id=match.match_id,
            batch_id=match.batch_id,
            action=action,
            previous_lifecycle=previous_lifecycle,
            new_lifecycle=match.exception_lifecycle,
            note=note,
            resolved_by=resolved_by,
        ))

    return match
