"""Amount hard constraints and compatibility checks."""
from __future__ import annotations

from typing import Optional

from app.config import settings


def amounts_compatible(a: Optional[float], b: Optional[float], tolerance: Optional[float] = None) -> bool:
    if a is None or b is None:
        return False
    tol = settings.AMOUNT_TOLERANCE if tolerance is None else tolerance
    return abs(a - b) <= tol


def net_from_gross(gross: Optional[float], fee: Optional[float], refund: Optional[float]) -> Optional[float]:
    if gross is None:
        return None
    return round(gross - (fee or 0.0) - (refund or 0.0), 2)


def impossible_amount_relationship(left: Optional[float], right: Optional[float], max_ratio: float = 50.0) -> bool:
    if left is None or right is None:
        return False
    if left == 0 or right == 0:
        return abs(left - right) > (settings.AMOUNT_TOLERANCE * 100)
    ratio = max(abs(left), abs(right)) / max(min(abs(left), abs(right)), 1e-9)
    return ratio > max_ratio
