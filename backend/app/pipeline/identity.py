"""Cross-field identity and text similarity used by exact/fuzzy matching."""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Optional, Set

from rapidfuzz import fuzz

ID_RE = re.compile(
    r"\b(?:PAY|SET|INV|ORD|BANK|JNL|UTR|RF-?PAY)[-A-Z0-9]*\d+[A-Z0-9]*\b",
    re.IGNORECASE,
)
NON_ALNUM = re.compile(r"[^A-Z0-9]")
STOPWORDS = {
    "PAYMENT", "PAYOUT", "SETTLEMENT", "BATCH", "MONTHLY", "CHARGE", "AND", "THE",
    "TO", "FOR", "FROM", "DEBIT", "CREDIT", "NEFT", "UTR", "REF", "INVOICE",
    "PROCESSOR", "ORDER", "PART", "SHORT", "UNIDENTIFIED",
}
SYNONYM_GROUPS = (
    {"VENDOR", "SUPPLIER", "PAYEE"},
    {"COURIER", "LOGISTICS", "FREIGHT"},
    {"ADS", "AD", "ADVERTISING", "MARKETING", "CAMPAIGN", "DIGITAL"},
    {"CLOUD", "HOSTING", "INFRA", "INFRASTRUCTURE"},
    {"STATIONERY", "OFFICE"},
    {"AGENCY", "MEDIA"},
)
SYNONYM_INDEX: Dict[str, Set[str]] = {}
for group in SYNONYM_GROUPS:
    for word in group:
        SYNONYM_INDEX[word] = set(group)


def _norm_token(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    compact = NON_ALNUM.sub("", str(value).upper())
    return compact or None


def _expand_id(token: str) -> Set[str]:
    out = {token}
    for prefix in ("RFPAY", "RF"):
        if token.startswith(prefix) and len(token) > len(prefix) + 2:
            out.add(token[len(prefix):])
    return out


def identity_tokens(row: Dict[str, Any]) -> Set[str]:
    tokens: Set[str] = set()
    for key in (
        "source_record_id", "payment_id", "invoice_id", "order_id",
        "settlement_id", "reference", "reference_normalized", "parent_transaction_id",
    ):
        token = _norm_token(row.get(key))
        if token:
            tokens.update(_expand_id(token))
    blob = " ".join(
        str(row.get(k) or "")
        for k in ("reference", "description", "counterparty", "description_normalized")
    )
    for match in ID_RE.findall(blob):
        token = _norm_token(match)
        if token:
            tokens.update(_expand_id(token))
    tokens.discard("")
    return tokens


def identities_overlap(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    a, b = identity_tokens(left), identity_tokens(right)
    if not a or not b:
        return False
    if a & b:
        return True
    # Containment: PAY1002 inside SETTLEMENTPAYOUTPAY1002-style compacted refs.
    for x in a:
        if len(x) < 5:
            continue
        if any(x in y or y in x for y in b if len(y) >= 5):
            return True
    return False


def _content_tokens(text: str) -> Set[str]:
    words = re.findall(r"[A-Z0-9]{3,}", (text or "").upper())
    return {w for w in words if w not in STOPWORDS}


def _synonym_hit(a: Set[str], b: Set[str]) -> bool:
    for word in a:
        related = SYNONYM_INDEX.get(word)
        if related and related & b:
            return True
    return False


def text_similarity(left: Dict[str, Any], right: Dict[str, Any]) -> float:
    """0-100 combined similarity across name, description, and identity."""
    if identities_overlap(left, right):
        return 100.0

    l_name = (left.get("counterparty_normalized") or left.get("counterparty") or "")
    r_name = (right.get("counterparty_normalized") or right.get("counterparty") or "")
    l_desc = (left.get("description") or left.get("description_normalized") or "")
    r_desc = (right.get("description") or right.get("description_normalized") or "")
    l_text = f"{l_name} {l_desc}".strip().lower()
    r_text = f"{r_name} {r_desc}".strip().lower()
    if not l_text or not r_text:
        return 0.0

    scores = [
        fuzz.token_sort_ratio(l_text, r_text),
        fuzz.token_set_ratio(l_text, r_text),
        fuzz.partial_ratio(l_text, r_text),
        fuzz.token_sort_ratio(str(l_name).lower(), str(r_name).lower()) if l_name and r_name else 0,
    ]
    best = max(scores)

    l_tokens = _content_tokens(l_text)
    r_tokens = _content_tokens(r_text)
    if l_tokens and r_tokens:
        overlap = l_tokens & r_tokens
        distinctive = {t for t in overlap if len(t) >= 5}
        if distinctive:
            best = max(best, 88.0)
        elif overlap:
            best = max(best, 82.0)
        if _synonym_hit(l_tokens, r_tokens):
            best = max(best, 86.0)
        # Substring of a long distinctive token (STATIONERY in STATIONERYSUPPLIER).
        for t in l_tokens:
            if len(t) < 6:
                continue
            if any(t in u or u in t for u in r_tokens if len(u) >= 6):
                best = max(best, 87.0)
                break
    return float(best)


def settlement_amount(row: Dict[str, Any]) -> Optional[float]:
    """Amount the bank is expected to show for a processor (or generic) row."""
    if row.get("source") == "processor" or row.get("net_amount") is not None:
        if row.get("net_amount") is not None:
            return row.get("net_amount")
        return row.get("gross_amount") if row.get("gross_amount") is not None else row.get("amount")
    return row.get("amount")


def amount_close(a: Optional[float], b: Optional[float], tolerance: float) -> bool:
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= tolerance
