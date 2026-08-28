"""
Financial event graph (README §7).

Builds a lightweight per-payment chain (Order -> Payment -> Settlement ->
Bank -> ERP) from the persisted matches of a reconciled batch, so the
controller can answer "how did this money move through the systems?"
instead of only "does row A match row B?".

This reads already-persisted MatchResult + TransactionRow data rather
than being a separate matching stage -- the chain is a *view* over the
matches the pipeline already produced.
"""
from __future__ import annotations
from typing import Dict, List, Any
from sqlalchemy.orm import Session

from app.db import MatchResult, TransactionRow, loads


def build_event_graph(db: Session, batch_id: str) -> List[Dict[str, Any]]:
    txns = db.query(TransactionRow).filter(TransactionRow.batch_id == batch_id).all()
    txn_by_key = {(t.source, t.source_record_id): t for t in txns}

    matches = db.query(MatchResult).filter(MatchResult.batch_id == batch_id).all()

    # Index matches by (source, txn_id) on either side for quick lookups.
    match_by_left: Dict[tuple, List[MatchResult]] = {}
    match_by_right: Dict[tuple, List[MatchResult]] = {}
    for m in matches:
        for lid in (loads(m.left_txn_ids_json) or []):
            match_by_left.setdefault((m.left_source, lid), []).append(m)
        for rid in (loads(m.right_txn_ids_json) or []):
            match_by_right.setdefault((m.right_source, rid), []).append(m)

    chains = []
    seen_payments = set()

    processor_txns = [t for t in txns if t.source == "processor" and t.transaction_type == "payment"]

    for p in processor_txns:
        if p.source_record_id in seen_payments:
            continue
        seen_payments.add(p.source_record_id)

        nodes = []
        edges = []

        order_node_id = f"order:{p.order_id or p.source_record_id}"
        if p.order_id:
            nodes.append({"id": order_node_id, "source": "order", "kind": "order",
                          "label": f"Order {p.order_id}", "amount": p.gross_amount})

        payment_node_id = f"processor:{p.source_record_id}"
        nodes.append({"id": payment_node_id, "source": "processor", "kind": "payment",
                      "label": f"Payment {p.source_record_id}", "amount": p.gross_amount})
        if p.order_id:
            edges.append({"source_id": order_node_id, "target_id": payment_node_id, "label": "paid via"})

        settlement_label = p.settlement_id or "(unbatched)"
        settlement_node_id = f"settlement:{p.settlement_id or p.source_record_id}"
        nodes.append({"id": settlement_node_id, "source": "processor", "kind": "settlement",
                      "label": f"Settlement {settlement_label}", "amount": p.net_amount})
        edges.append({
            "source_id": payment_node_id, "target_id": settlement_node_id,
            "label": f"net of fee {p.fee_amount or 0}" + (f" & refund {p.refund_amount}" if p.refund_amount else ""),
        })

        # Find the bank match covering this payment (direct, fee_aware, or many_to_one).
        bank_txn = None
        related = match_by_left.get(("processor", p.source_record_id), [])
        for m in related:
            if m.right_source == "bank" and m.status == "matched":
                rids = loads(m.right_txn_ids_json) or []
                if rids:
                    bank_txn = txn_by_key.get(("bank", rids[0]))
                break

        status = "partial"
        if bank_txn:
            bank_node_id = f"bank:{bank_txn.source_record_id}"
            nodes.append({"id": bank_node_id, "source": "bank", "kind": "bank",
                          "label": f"Bank txn {bank_txn.source_record_id}", "amount": bank_txn.amount})
            edges.append({"source_id": settlement_node_id, "target_id": bank_node_id, "label": "settled to"})

            # Find an ERP match covering that bank transaction.
            erp_txn = None
            for m in match_by_left.get(("bank", bank_txn.source_record_id), []) + \
                      match_by_right.get(("bank", bank_txn.source_record_id), []):
                if m.status != "matched":
                    continue
                other_source = m.right_source if m.left_source == "bank" else m.left_source
                other_ids = (loads(m.right_txn_ids_json) if m.left_source == "bank"
                             else loads(m.left_txn_ids_json)) or []
                if other_source == "erp" and other_ids:
                    erp_txn = txn_by_key.get(("erp", other_ids[0]))
                    break

            if erp_txn:
                erp_node_id = f"erp:{erp_txn.source_record_id}"
                nodes.append({"id": erp_node_id, "source": "erp", "kind": "erp",
                              "label": f"ERP journal {erp_txn.source_record_id}", "amount": erp_txn.amount})
                edges.append({"source_id": bank_node_id, "target_id": erp_node_id, "label": "posted as"})
                status = "complete"
        chains.append({
            "chain_id": f"chain:{p.source_record_id}",
            "nodes": nodes, "edges": edges, "status": status,
        })

    return chains
