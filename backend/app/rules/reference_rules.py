"""Reference identity checks using original and normalized forms."""
from __future__ import annotations

from typing import Optional


def references_match(a: Optional[str], b: Optional[str], a_norm: Optional[str] = None, b_norm: Optional[str] = None) -> bool:
    if a and b and str(a).strip().lower() == str(b).strip().lower():
        return True
    if a_norm and b_norm and a_norm == b_norm:
        return True
    # Compact containment: INV-1094 vs INV1094, PAY1002 inside a longer bank ref.
    compact_a = "".join(ch for ch in str(a_norm or a or "") if ch.isalnum()).upper()
    compact_b = "".join(ch for ch in str(b_norm or b or "") if ch.isalnum()).upper()
    if compact_a and compact_b and len(min(compact_a, compact_b, key=len)) >= 5:
        if compact_a in compact_b or compact_b in compact_a:
            return True
    return False
