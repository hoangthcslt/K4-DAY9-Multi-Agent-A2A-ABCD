"""Build the exact README output contract from normalized facts."""

from __future__ import annotations

from typing import Any

from .contracts import AgentHandoff, CaseInput, PolicyDecision
from .data_loader import OlistIndexes


def _facts(handoffs: dict[str, AgentHandoff], name: str) -> dict[str, Any]:
    return handoffs[name].facts


def build_output(
    case: CaseInput,
    handoffs: dict[str, AgentHandoff],
    decision: PolicyDecision,
    indexes: OlistIndexes,
) -> dict[str, Any]:
    order_id = case.claimed_order_id
    customer = _facts(handoffs, "customer")
    order = _facts(handoffs, "order_product")
    payment = _facts(handoffs, "payment")
    delivery = _facts(handoffs, "delivery")

    affected_item_ids = list(order.get("item_ids") or [])[:5]
    affected_seller_ids = list(order.get("seller_ids") or [])[:3]
    affected_payment_ids = list(payment.get("payment_ids") or [])[:5]
    product_ids = list(order.get("product_ids") or [])[:5]
    category_names = list(order.get("category_names") or [])[:5]

    ranked_causes = list(decision.root_causes)[:3]
    evidence_ids = [f"order:{order_id}"]
    evidence_ids.extend(f"item:{item_id}" for item_id in affected_item_ids)
    evidence_ids.extend(f"payment:{payment_id}" for payment_id in affected_payment_ids)
    evidence_ids.extend(
        f"seller:{party['party_id']}"
        for party in decision.responsible_parties
        if party.get("party_type") == "seller"
    )
    evidence_ids.extend(
        f"policy:{cause['cause_code']}"
        for cause in ranked_causes
        if cause.get("cause_code")
    )

    return {
        "case_id": case.case_id,
        "case_assessment": {
            "primary_issue": decision.primary_issue,
            "secondary_issues": decision.secondary_issues,
            "case_status": decision.case_status,
            "confidence": decision.confidence,
        },
        "affected_entities": {
            "order_ids": [order_id],
            "item_ids": affected_item_ids,
            "seller_ids": affected_seller_ids,
            "payment_ids": affected_payment_ids,
        },
        "customer_context": {
            "customer_unique_id": customer.get("customer_unique_id"),
            "related_order_ids": list(customer.get("related_order_ids") or [])[:5],
        },
        "product_context": {
            "product_ids": product_ids,
            "category_names": category_names,
        },
        "delivery_analysis": {
            "delivered_at": delivery.get("delivered_at"),
            "estimated_delivery_at": delivery.get("estimated_delivery_at"),
            "carrier_handoff_at": delivery.get("carrier_handoff_at"),
            "delivery_variance_hours": delivery.get("delivery_variance_hours"),
            "seller_handoff_analysis": list(delivery.get("seller_handoff_analysis") or [])[:3],
            "late_handoff_seller_ids": list(delivery.get("late_handoff_seller_ids") or [])[:3],
        },
        "payment_reconciliation": {
            "currency": "BRL",
            "item_total_brl": payment.get("item_total_brl"),
            "freight_total_brl": payment.get("freight_total_brl"),
            "expected_total_brl": payment.get("expected_total_brl"),
            "payment_total_brl": payment.get("payment_total_brl"),
            "difference_brl": payment.get("difference_brl"),
            "reconciled": payment.get("reconciled"),
            "payment_types": list(payment.get("payment_types") or []),
        },
        "root_cause_analysis": {
            "ranked_causes": ranked_causes,
            "responsible_parties": list(decision.responsible_parties)[:3],
        },
        "evidence_ids": evidence_ids[:20],
        "financial_resolution": {
            "currency": "BRL",
            "recommended_refund_brl": decision.recommended_refund_brl,
        },
        "resolution_actions": list(decision.resolution_actions)[:5],
    }
