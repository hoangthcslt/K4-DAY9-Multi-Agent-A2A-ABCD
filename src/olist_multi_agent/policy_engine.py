"""Deterministic implementation of EC_POLICY_V2."""

from __future__ import annotations

from typing import Any

from .contracts import AgentHandoff, PolicyDecision


PRIMARY_PRIORITY = (
    "canceled_order_paid",
    "unavailable_order_paid",
    "late_delivery_seller",
    "late_delivery_logistics",
    "valid_split_payment",
    "unsupported_late_claim",
)

SECONDARY_ORDER = (
    "multi_item_order",
    "multi_seller_order",
    "split_payment",
    "repeat_customer",
    "multiple_categories",
)


def _facts(handoffs: dict[str, AgentHandoff], agent: str) -> dict[str, Any]:
    return handoffs.get(agent, AgentHandoff(case_id="unknown", agent=agent)).facts


def _confidence(
    *,
    matched_cleanly: bool,
    primary: str,
    delivery: dict[str, Any],
    payment: dict[str, Any],
    handoffs: dict[str, AgentHandoff],
) -> float:
    """Calibrate confidence from real uncertainty signals instead of a fixed value.

    A rule that only ever reports 1.0 is indistinguishable from a model that
    never checks its own inputs. This lowers confidence when the case fell
    through to the unmatched fallback, when the decisive variance sits close
    to its threshold, when timestamps needed for the decision are missing, or
    when an upstream agent already raised a warning.
    """
    score = 0.97

    if not matched_cleanly:
        score -= 0.35

    if primary in ("late_delivery_seller", "late_delivery_logistics"):
        variance = delivery.get("delivery_variance_hours")
        if variance is None or abs(float(variance)) < 2.0:
            score -= 0.10
        if delivery.get("delivered_at") is None or delivery.get("carrier_handoff_at") is None:
            score -= 0.10

    if primary in ("valid_split_payment", "unsupported_late_claim"):
        difference = payment.get("difference_brl")
        if difference is not None and 0.05 <= abs(float(difference)) <= 0.10:
            score -= 0.08

    for handoff in handoffs.values():
        if handoff.warnings:
            score -= 0.05

    return round(max(0.55, min(0.99, score)), 2)


def resolve_policy(handoffs: dict[str, AgentHandoff]) -> PolicyDecision:
    """Apply the README priority order to normalized agent facts."""
    order = _facts(handoffs, "order_product")
    payment = _facts(handoffs, "payment")
    delivery = _facts(handoffs, "delivery")
    customer = _facts(handoffs, "customer")

    status = order.get("order_status")
    payment_total = float(payment.get("payment_total_brl") or 0.0)
    delivery_late = bool(delivery.get("delivery_late"))
    late_sellers = list(delivery.get("late_handoff_seller_ids") or [])
    reconciled = payment.get("reconciled")
    payment_count = int(payment.get("payment_count") or 0)
    delivery_variance = delivery.get("delivery_variance_hours")

    matched_cleanly = True
    if status == "canceled" and payment_total > 0:
        primary = "canceled_order_paid"
        cause = "ORDER_CANCELED_AFTER_PAYMENT"
        refund = payment_total
        responsible = [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}]
        primary_action = "issue_full_refund"
    elif status == "unavailable" and payment_total > 0:
        primary = "unavailable_order_paid"
        cause = "ORDER_UNAVAILABLE_AFTER_PAYMENT"
        refund = payment_total
        responsible = [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}]
        primary_action = "issue_full_refund"
    elif delivery_late and late_sellers:
        primary = "late_delivery_seller"
        cause = "SELLER_HANDOFF_AFTER_LIMIT"
        refund = float(payment.get("freight_total_brl") or 0.0)
        responsible = [
            {"party_type": "seller", "party_id": seller_id}
            for seller_id in late_sellers[:3]
        ]
        primary_action = "refund_freight"
    elif delivery_late:
        primary = "late_delivery_logistics"
        cause = "CARRIER_DELIVERED_AFTER_ESTIMATE"
        refund = float(payment.get("freight_total_brl") or 0.0)
        responsible = [
            {"party_type": "logistics_provider", "party_id": "LOGISTICS_PROVIDER"}
        ]
        primary_action = "refund_freight"
    elif payment_count >= 2 and reconciled is True:
        primary = "valid_split_payment"
        cause = "MULTIPLE_PAYMENTS_RECONCILED"
        refund = 0.0
        responsible = []
        primary_action = "explain_valid_split_payment"
    elif delivery_variance is not None and float(delivery_variance) <= 0 and reconciled is True:
        primary = "unsupported_late_claim"
        cause = "DELIVERY_WITHIN_ESTIMATE"
        refund = 0.0
        responsible = []
        primary_action = "reject_late_refund"
    else:
        # The supplied 50 cases are expected to match one of the rules above.
        # Keep a safe no-refund result for an unforeseen/missing-data case,
        # but mark it as an unclean match so confidence reflects the guess.
        matched_cleanly = False
        primary = "unsupported_late_claim"
        cause = "DELIVERY_WITHIN_ESTIMATE"
        refund = 0.0
        responsible = []
        primary_action = "reject_late_refund"

    secondary: list[str] = []
    if order.get("multi_item_order"):
        secondary.append("multi_item_order")
    if order.get("multi_seller_order"):
        secondary.append("multi_seller_order")
    if payment.get("split_payment"):
        secondary.append("split_payment")
    if customer.get("repeat_customer"):
        secondary.append("repeat_customer")
    if order.get("multiple_categories"):
        secondary.append("multiple_categories")

    actions = [primary_action]
    if primary == "late_delivery_seller":
        actions.append("review_seller_handoff")
    elif primary == "late_delivery_logistics":
        actions.append("review_carrier_delay")
    if refund > 0:
        actions.append("verify_refund_completion")
    if order.get("multi_seller_order"):
        actions.append("coordinate_multi_seller_case")
    if payment.get("split_payment") and primary != "valid_split_payment":
        actions.append("verify_payment_allocation")

    confidence = _confidence(
        matched_cleanly=matched_cleanly,
        primary=primary,
        delivery=delivery,
        payment=payment,
        handoffs=handoffs,
    )

    return PolicyDecision(
        primary_issue=primary,
        secondary_issues=secondary,
        case_status="action_required" if refund > 0 else "no_action",
        confidence=confidence,
        root_causes=[{"cause_code": cause, "rank": 1}],
        responsible_parties=responsible[:3],
        recommended_refund_brl=round(refund, 2),
        resolution_actions=actions[:5],
    )
