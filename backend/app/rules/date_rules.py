"""Date-window hard constraints."""
from __future__ import annotations

from datetime import date
from typing import Optional

from app.config import settings


def dates_compatible(a: Optional[date], b: Optional[date], tolerance_days: Optional[int] = None) -> bool:
    if a is None or b is None:
        return True
    window = settings.TIMING_TOLERANCE_DAYS if tolerance_days is None else tolerance_days
    return abs((a - b).days) <= window


def impossible_date_relationship(a: Optional[date], b: Optional[date], max_days: int = 366) -> bool:
    if a is None or b is None:
        return False
    return abs((a - b).days) > max_days
