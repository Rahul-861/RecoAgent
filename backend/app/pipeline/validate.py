"""Centralized input validation. Invalid records never enter matching."""
from __future__ import annotations

from typing import Any, Dict, List, Set

from app.contract.reconciliation_contract import KNOWN_CURRENCIES, ALLOWED_TRANSACTION_TYPES, REQUIRED_FIELDS


def validate_record(row: Dict[str, Any], seen_ids: Set[str]) -> List[str]:
    errors: List[str] = []
    source = row.get("source") or ""
    sid = row.get("source_record_id")
    if not sid:
        errors.append("Missing transaction ID")
    elif sid in seen_ids:
        errors.append("Duplicate source record ID")

    required = REQUIRED_FIELDS.get(source, ["source_record_id"])
    for field in required:
        if field == "amount":
            if row.get("amount") is None and row.get("gross_amount") is None and row.get("net_amount") is None:
                errors.append("Missing transaction amount")
        elif field == "currency":
            if not row.get("currency"):
                errors.append("Missing currency")
        elif not row.get(field):
            errors.append(f"Missing {field}")

    amt = row.get("amount")
    if amt is not None:
        try:
            float(amt)
        except (TypeError, ValueError):
            errors.append("Invalid amount")

    currency = (row.get("currency") or "").upper()
    if currency and currency not in KNOWN_CURRENCIES:
        errors.append("Unsupported currency")

    txn_type = (row.get("transaction_type") or "").lower()
    if txn_type and txn_type not in ALLOWED_TRANSACTION_TYPES:
        errors.append("Unknown transaction type")

    return errors


def validate_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Set[str] = set()
    out = []
    for row in rows:
        errors = validate_record(row, seen)
        sid = row.get("source_record_id")
        if sid:
            seen.add(sid)
        row = dict(row)
        row["is_valid"] = len(errors) == 0
        row["validation_errors"] = errors
        if not row["is_valid"]:
            row["recon_state"] = "INVALID"
        else:
            row["recon_state"] = "VALIDATED"
        out.append(row)
    return out
