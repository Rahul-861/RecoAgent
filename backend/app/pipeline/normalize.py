"""
Stage 0 -- Schema normalization (README §6, §9).

Maps three arbitrarily-formatted CSVs (bank / processor / ERP) into the
shared canonical transaction schema, regardless of exact column naming.
Each source has its own alias table since bank exports, processor
exports, and ERP exports genuinely use different vocabularies (§4).
"""
from __future__ import annotations
import io
import re
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

import pandas as pd

from app.config import settings

LEGAL_SUFFIXES = (
    "PRIVATE LIMITED", "PVT LTD", "PVT. LTD.", "LIMITED", "LTD", "LLC", "INC", "PLC",
)
BOILERPLATE_REF = ("INVOICE", "INV", "REF", "UTR", "TXN")

# ---- per-source column alias tables -------------------------------------

BANK_ALIASES = {
    "source_record_id": ["transaction_id", "txn_id", "id", "bank_txn_id"],
    "transaction_date": ["transaction_date", "date", "txn_date"],
    "value_date": ["value_date", "posting_date"],
    "amount": ["amount", "credit", "debit_credit", "value"],
    "currency": ["currency", "ccy"],
    "reference": ["reference", "ref", "utr", "narration_ref"],
    "description": ["description", "narration", "particulars", "memo"],
    # Optional canonical fields (README §4) -- only used when present.
    "tax_amount": ["tax", "tax_amount", "gst", "gst_amount"],
    "chargeback_amount": ["chargeback", "chargeback_amount"],
    "parent_transaction_id": ["parent_transaction_id", "parent_txn_id", "original_transaction_id"],
}

PROCESSOR_ALIASES = {
    "source_record_id": ["payment_id", "id", "txn_id"],
    "order_id": ["order_id"],
    "customer_id": ["customer_id"],
    "transaction_date": ["payment_date", "date"],
    "gross_amount": ["gross_amount", "gross"],
    "fee_amount": ["fee", "processing_fee"],
    "refund_amount": ["refund", "refund_amount"],
    "net_amount": ["net_amount", "net"],
    "settlement_id": ["settlement_id"],
    "currency": ["currency", "ccy"],
    "status": ["status"],
    # Optional canonical fields (README §4) -- only used when present.
    "tax_amount": ["tax", "tax_amount", "gst", "gst_amount"],
    "chargeback_amount": ["chargeback", "chargeback_amount"],
    "parent_transaction_id": ["parent_transaction_id", "parent_payment_id", "original_payment_id"],
}

ERP_ALIASES = {
    "source_record_id": ["journal_id", "id"],
    "invoice_id": ["invoice_id"],
    "transaction_date": ["posting_date", "date"],
    "account": ["account"],
    "debit": ["debit"],
    "credit": ["credit"],
    "amount": ["amount"],
    "currency": ["currency", "ccy"],
    "reference": ["reference", "ref"],
    "counterparty": ["counterparty", "vendor", "payee"],
    # Optional canonical fields (README §4) -- only used when present.
    "tax_amount": ["tax", "tax_amount", "gst", "gst_amount"],
    "chargeback_amount": ["chargeback", "chargeback_amount"],
    "parent_transaction_id": ["parent_transaction_id", "parent_journal_id", "original_journal_id"],
}


def _find_column(columns: List[str], aliases: List[str]) -> str | None:
    lower_map = {c.lower().strip(): c for c in columns}
    for alias in aliases:
        if alias in lower_map:
            return lower_map[alias]
    return None


def _parse_date(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.date()
    try:
        parsed = pd.to_datetime(str(value), errors="coerce")
        return parsed.date() if pd.notna(parsed) else None
    except Exception:
        return None


def parse_amount(value) -> Tuple[Optional[float], Optional[str]]:
    """Normalize ₹10,000 / 10,000.00 / 10000 into a float. Preserve original text."""
    if value is None:
        return None, None
    try:
        if isinstance(value, float) and pd.isna(value):
            return None, None
    except (TypeError, ValueError):
        pass
    original = str(value).strip() if not isinstance(value, (int, float)) else str(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value), original
    s = original.replace("₹", "").replace("$", "").replace("€", "").replace("£", "")
    s = s.replace(",", "").replace(" ", "")
    s = re.sub(r"[^0-9.\-]", "", s)
    if s in ("", "-", ".", "-."):
        return None, original
    try:
        return float(s), original
    except (TypeError, ValueError):
        return None, original


def _num(value):
    amt, _ = parse_amount(value)
    return amt


def normalize_reference(value) -> Tuple[Optional[str], Optional[str]]:
    if value is None:
        return None, None
    try:
        if pd.isna(value):
            return None, None
    except (TypeError, ValueError):
        pass
    original = str(value).strip()
    if not original:
        return None, None
    compact = re.sub(r"[^A-Za-z0-9]", "", original).upper()
    for prefix in BOILERPLATE_REF:
        if compact.startswith(prefix) and len(compact) > len(prefix):
            rest = compact[len(prefix):]
            if rest.isdigit() or rest[:1].isdigit():
                compact = rest
                break
    compact = compact.lstrip("0") or compact
    return original, compact


def normalize_counterparty(value) -> Tuple[Optional[str], Optional[str]]:
    if value is None:
        return None, None
    try:
        if pd.isna(value):
            return None, None
    except (TypeError, ValueError):
        pass
    original = str(value).strip()
    if not original:
        return None, None
    s = original.upper()
    s = s.replace(".", " ")
    s = re.sub(r"[^A-Z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for suffix in LEGAL_SUFFIXES:
        if s.endswith(" " + suffix) or s.endswith(suffix):
            s = s[: -len(suffix)].strip()
    s = re.sub(r"\s+", " ", s).strip()
    s = s.replace(" ", "")
    return original, s


def normalize_description(value) -> Tuple[Optional[str], Optional[str]]:
    if value is None:
        return None, ""
    original = str(value).strip()
    s = original.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return original, s


def apply_canonical_fields(row: Dict[str, Any]) -> Dict[str, Any]:
    row["normalization_version"] = settings.NORMALIZATION_VERSION
    amt, original_amt = parse_amount(row.get("amount"))
    if amt is not None:
        row["amount"] = amt
    if original_amt and row.get("original_amount") is None:
        row["original_amount"] = original_amt
    if row.get("currency"):
        row["currency"] = str(row["currency"]).strip().upper()
    orig_ref, norm_ref = normalize_reference(row.get("reference"))
    if orig_ref is not None:
        row["reference"] = orig_ref
    row["reference_normalized"] = norm_ref
    orig_cp, norm_cp = normalize_counterparty(row.get("counterparty"))
    if orig_cp is not None:
        row["counterparty"] = orig_cp
    row["counterparty_normalized"] = norm_cp
    orig_desc, norm_desc = normalize_description(row.get("description"))
    if orig_desc is not None:
        row["description"] = orig_desc
    row["description_normalized"] = norm_desc
    if row.get("transaction_date") is not None:
        row["original_timestamp"] = str(row["transaction_date"])
    row["normalized_record"] = {
        "amount": row.get("amount"),
        "currency": row.get("currency"),
        "reference_normalized": row.get("reference_normalized"),
        "counterparty_normalized": row.get("counterparty_normalized"),
        "description_normalized": row.get("description_normalized"),
        "transaction_date": str(row.get("transaction_date")) if row.get("transaction_date") else None,
    }
    return row


def _read_df(file_bytes: bytes) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(file_bytes))
    df.columns = [c.strip() for c in df.columns]
    return df


def _base_row(source: str, idx: int, raw_dict: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "source": source,
        "source_record_id": None,
        "transaction_type": None,
        "transaction_date": None,
        "value_date": None,
        "amount": None,
        "gross_amount": None,
        "fee_amount": None,
        "refund_amount": None,
        "net_amount": None,
        "currency": "INR",
        "reference": None,
        "invoice_id": None,
        "order_id": None,
        "payment_id": None,
        "settlement_id": None,
        "counterparty": None,
        "description": None,
        "status": None,
        # Optional canonical fields -- stay None unless the source has them.
        "tax_amount": None,
        "chargeback_amount": None,
        "parent_transaction_id": None,
        "raw_row": raw_dict,
    }


def _apply_optional_canonical_fields(row: Dict[str, Any], raw_dict: Dict[str, Any], col_map: Dict[str, Optional[str]]) -> None:
    """Populate tax/chargeback/parent_transaction_id when the source column exists (README §4, §38 pending item)."""
    if col_map.get("tax_amount"):
        row["tax_amount"] = _num(raw_dict.get(col_map["tax_amount"]))
    if col_map.get("chargeback_amount"):
        row["chargeback_amount"] = _num(raw_dict.get(col_map["chargeback_amount"]))
    if col_map.get("parent_transaction_id"):
        val = raw_dict.get(col_map["parent_transaction_id"])
        row["parent_transaction_id"] = str(val).strip() if val not in (None, "") else None


def normalize_bank_csv(file_bytes: bytes) -> List[Dict[str, Any]]:
    df = _read_df(file_bytes)
    columns = list(df.columns)
    col_map = {f: _find_column(columns, a) for f, a in BANK_ALIASES.items()}
    if col_map.get("amount") is None:
        raise ValueError(f"Bank source: could not find an amount column. Columns found: {columns}")

    rows = []
    for idx, raw in df.iterrows():
        raw_dict = {k: (None if pd.isna(v) else v) for k, v in raw.to_dict().items()}
        row = _base_row("bank", idx, raw_dict)
        row["source_record_id"] = (
            str(raw_dict[col_map["source_record_id"]])
            if col_map.get("source_record_id") and raw_dict.get(col_map["source_record_id"]) is not None
            else f"BANK_{idx}"
        )
        row["transaction_date"] = _parse_date(raw_dict.get(col_map.get("transaction_date")))
        row["value_date"] = _parse_date(raw_dict.get(col_map.get("value_date"))) or row["transaction_date"]
        amt = _num(raw_dict.get(col_map.get("amount")))
        row["amount"] = amt
        row["transaction_type"] = "credit" if (amt or 0) >= 0 else "debit"
        cur = raw_dict.get(col_map.get("currency"))
        row["currency"] = str(cur) if cur else "INR"
        ref = raw_dict.get(col_map.get("reference"))
        row["reference"] = str(ref).strip() if ref else None
        desc = raw_dict.get(col_map.get("description"))
        row["description"] = str(desc).strip() if desc else ""
        row["counterparty"] = row["description"]
        _apply_optional_canonical_fields(row, raw_dict, col_map)
        rows.append(apply_canonical_fields(row))
    return rows


def normalize_processor_csv(file_bytes: bytes) -> List[Dict[str, Any]]:
    df = _read_df(file_bytes)
    columns = list(df.columns)
    col_map = {f: _find_column(columns, a) for f, a in PROCESSOR_ALIASES.items()}
    if col_map.get("gross_amount") is None and col_map.get("net_amount") is None:
        raise ValueError(f"Processor source: could not find gross/net amount column. Columns found: {columns}")

    rows = []
    for idx, raw in df.iterrows():
        raw_dict = {k: (None if pd.isna(v) else v) for k, v in raw.to_dict().items()}
        row = _base_row("processor", idx, raw_dict)
        row["source_record_id"] = (
            str(raw_dict[col_map["source_record_id"]])
            if col_map.get("source_record_id") and raw_dict.get(col_map["source_record_id"]) is not None
            else f"PAY_{idx}"
        )
        row["payment_id"] = row["source_record_id"]
        order_id = raw_dict.get(col_map.get("order_id"))
        row["order_id"] = str(order_id) if order_id else None
        row["transaction_date"] = _parse_date(raw_dict.get(col_map.get("transaction_date")))
        gross = _num(raw_dict.get(col_map.get("gross_amount")))
        fee = _num(raw_dict.get(col_map.get("fee_amount"))) or 0.0
        refund = _num(raw_dict.get(col_map.get("refund_amount"))) or 0.0
        net = _num(raw_dict.get(col_map.get("net_amount")))
        if net is None and gross is not None:
            net = round(gross - fee - refund, 2)
        if gross is None and net is not None:
            gross = round(net + fee + refund, 2)
        row["gross_amount"] = gross
        row["fee_amount"] = fee
        row["refund_amount"] = refund
        row["net_amount"] = net
        row["amount"] = gross
        row["transaction_type"] = "refund" if refund and refund > 0 else "payment"
        settlement_id = raw_dict.get(col_map.get("settlement_id"))
        row["settlement_id"] = str(settlement_id) if settlement_id else None
        cur = raw_dict.get(col_map.get("currency"))
        row["currency"] = str(cur) if cur else "INR"
        status = raw_dict.get(col_map.get("status"))
        row["status"] = str(status) if status else None
        cust = raw_dict.get(col_map.get("customer_id"))
        row["counterparty"] = str(cust) if cust else row["payment_id"]
        row["description"] = (
            f"{row['counterparty']} processor payment {row['payment_id']}"
            + (f" order {row['order_id']}" if row.get("order_id") else "")
            + (f" settlement {row['settlement_id']}" if row.get("settlement_id") else "")
        )
        row["reference"] = row["payment_id"] or row["settlement_id"]
        _apply_optional_canonical_fields(row, raw_dict, col_map)
        rows.append(apply_canonical_fields(row))
    return rows


def normalize_erp_csv(file_bytes: bytes) -> List[Dict[str, Any]]:
    df = _read_df(file_bytes)
    columns = list(df.columns)
    col_map = {f: _find_column(columns, a) for f, a in ERP_ALIASES.items()}
    if col_map.get("amount") is None and col_map.get("debit") is None and col_map.get("credit") is None:
        raise ValueError(f"ERP source: could not find an amount/debit/credit column. Columns found: {columns}")

    rows = []
    for idx, raw in df.iterrows():
        raw_dict = {k: (None if pd.isna(v) else v) for k, v in raw.to_dict().items()}
        row = _base_row("erp", idx, raw_dict)
        row["source_record_id"] = (
            str(raw_dict[col_map["source_record_id"]])
            if col_map.get("source_record_id") and raw_dict.get(col_map["source_record_id"]) is not None
            else f"JNL_{idx}"
        )
        invoice_id = raw_dict.get(col_map.get("invoice_id"))
        row["invoice_id"] = str(invoice_id) if invoice_id else None
        row["transaction_date"] = _parse_date(raw_dict.get(col_map.get("transaction_date")))
        amount = _num(raw_dict.get(col_map.get("amount")))
        debit = _num(raw_dict.get(col_map.get("debit")))
        credit = _num(raw_dict.get(col_map.get("credit")))
        if amount is None:
            amount = credit if credit else (debit if debit else None)
        row["amount"] = amount
        row["transaction_type"] = "journal"
        cur = raw_dict.get(col_map.get("currency"))
        row["currency"] = str(cur) if cur else "INR"
        ref = raw_dict.get(col_map.get("reference"))
        row["reference"] = str(ref).strip() if ref else row["invoice_id"]
        cp = raw_dict.get(col_map.get("counterparty"))
        row["counterparty"] = str(cp).strip() if cp else ""
        row["description"] = f"ERP journal for invoice {row['invoice_id']}"
        _apply_optional_canonical_fields(row, raw_dict, col_map)
        rows.append(apply_canonical_fields(row))
    return rows


NORMALIZERS = {
    "bank": normalize_bank_csv,
    "processor": normalize_processor_csv,
    "erp": normalize_erp_csv,
}
