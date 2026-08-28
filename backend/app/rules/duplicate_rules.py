"""Duplicate / consumption hard constraints."""
from __future__ import annotations

from typing import Set


def is_consumed(record_id: str, consumed: Set[str]) -> bool:
    return record_id in consumed


def reject_if_consumed(record_id: str, consumed: Set[str]) -> bool:
    """True when the candidate must be rejected (R006)."""
    return is_consumed(record_id, consumed)
