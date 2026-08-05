"""Deterministic validation for the README output contract."""

from __future__ import annotations

from typing import Any

from .contracts import VerificationResult
from .data_loader import OlistIndexes
from .policy_engine import PRIMARY_PRIORITY

REQUIRED_TOP_LEVEL = {
    "case_id",
    "case_assessment",
    "affected_entities",
    "customer_context",
    "product_context",
    "delivery_analysis",
    "payment_reconciliation",
    "root_cause_analysis",
    "evidence_ids",
    "financial_resolution",
    "resolution_actions",
}

ARRAY_LIMITS = {
    "order_ids": 5,
    "item_ids": 5,
    "seller_ids": 3,
    "payment_ids": 5,
    "related_order_ids": 5,
    "product_ids": 5,
    "category_names": 5,
    "evidence_ids": 20,
    "resolution_actions": 5,
    "secondary_issues": 5,
    "ranked_causes": 3,
    "responsible_parties": 3,
}

ROOT_CAUSES = {
    "SELLER_HANDOFF_AFTER_LIMIT",
    "CARRIER_DELIVERED_AFTER_ESTIMATE",
    "ORDER_CANCELED_AFTER_PAYMENT",
    "ORDER_UNAVAILABLE_AFTER_PAYMENT",
    "MULTIPLE_PAYMENTS_RECONCILED",
    "DELIVERY_WITHIN_ESTIMATE",
}


def _array_length(candidate: dict[str, Any], field: str) -> int:
    for container_name in (
        "affected_entities",
        "customer_context",
        "product_context",
        "root_cause_analysis",
        "case_assessment",
    ):
        container = candidate.get(container_name)
        if isinstance(container, dict) and isinstance(container.get(field), list):
            return len(container[field])
    value = candidate.get(field)
    return len(value) if isinstance(value, list) else 0


def _valid_source_evidence(evidence_id: str, indexes: OlistIndexes) -> bool:
    prefix, separator, value = evidence_id.partition(":")
    if not separator:
        return False
    if prefix == "order":
        return value in indexes.orders_by_id
    if prefix == "seller":
        return value in indexes.sellers_by_id
    if prefix == "policy":
        return value in ROOT_CAUSES
    if prefix not in {"item", "payment"}:
        return False
    parts = value.split(":")
    if len(parts) != 2:
        return False
    order_id, row_id = parts
    if prefix == "item":
        rows = indexes.items_by_order.get(order_id, [])
        key = "order_item_id"
    else:
        rows = indexes.payments_by_order.get(order_id, [])
        key = "payment_sequential"
    return any(row.get(key) == row_id for row in rows)


def verify_candidate(
    candidate: dict[str, Any],
    expected_case_id: str,
    expected_order_id: str | None = None,
    indexes: OlistIndexes | None = None,
) -> VerificationResult:
    errors: list[str] = []
    if not isinstance(candidate, dict):
        return VerificationResult(valid=False, errors=["candidate must be an object"])
    if candidate.get("case_id") != expected_case_id:
        errors.append("case_id does not match input")

    missing = REQUIRED_TOP_LEVEL.difference(candidate)
    errors.extend(f"missing top-level field: {field}" for field in sorted(missing))

    assessment = candidate.get("case_assessment", {})
    if not isinstance(assessment, dict):
        errors.append("case_assessment must be an object")
        assessment = {}
    if assessment.get("primary_issue") not in PRIMARY_PRIORITY:
        errors.append("invalid primary_issue")
    if assessment.get("case_status") not in {"action_required", "no_action"}:
        errors.append("invalid case_status")
    confidence = assessment.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        errors.append("confidence must be between 0 and 1")

    for field, limit in ARRAY_LIMITS.items():
        if _array_length(candidate, field) > limit:
            errors.append(f"{field} exceeds limit {limit}")

    entities = candidate.get("affected_entities", {})
    if not isinstance(entities, dict):
        errors.append("affected_entities must be an object")
        entities = {}
    if expected_order_id is not None and entities.get("order_ids") != [expected_order_id]:
        errors.append("affected_entities.order_ids must contain only the claimed order")

    root_analysis = candidate.get("root_cause_analysis", {})
    if not isinstance(root_analysis, dict):
        errors.append("root_cause_analysis must be an object")
        root_analysis = {}
    causes = root_analysis.get("ranked_causes", [])
    if not isinstance(causes, list) or not causes:
        errors.append("ranked_causes must contain at least one cause")
    else:
        for cause in causes:
            if not isinstance(cause, dict) or cause.get("cause_code") not in ROOT_CAUSES:
                errors.append("invalid root cause code")

    evidence = candidate.get("evidence_ids", [])
    if not isinstance(evidence, list) or not evidence:
        errors.append("evidence_ids must be a non-empty array")
    elif indexes is not None:
        errors.extend(
            f"invalid evidence_id: {evidence_id}"
            for evidence_id in evidence
            if not isinstance(evidence_id, str)
            or not _valid_source_evidence(evidence_id, indexes)
        )

    resolution = candidate.get("financial_resolution", {})
    if not isinstance(resolution, dict):
        errors.append("financial_resolution must be an object")
        resolution = {}
    refund = resolution.get("recommended_refund_brl")
    if not isinstance(refund, (int, float)) or refund < 0:
        errors.append("recommended_refund_brl must be a non-negative number")
    elif assessment.get("case_status") == "no_action" and refund > 0:
        errors.append("no_action case cannot have a positive refund")
    elif assessment.get("case_status") == "action_required" and refund <= 0:
        errors.append("action_required case must have a positive refund")

    customer = candidate.get("customer_context", {})
    if isinstance(customer, dict):
        customer_unique_id = customer.get("customer_unique_id")
        if indexes is not None and customer_unique_id is not None:
            if customer_unique_id not in indexes.customer_rows_by_unique_id:
                errors.append("customer_unique_id does not exist in customers")
        related = customer.get("related_order_ids", [])
        order_ids = entities.get("order_ids", [])
        if not isinstance(related, list):
            errors.append("related_order_ids must be an array")
        else:
            if any(order_id in order_ids for order_id in related):
                errors.append("related_order_ids must exclude the affected order")
            if indexes is not None:
                errors.extend(
                    f"related_order_id does not exist: {order_id}"
                    for order_id in related
                    if not isinstance(order_id, str)
                    or order_id not in indexes.orders_by_id
                )

    if indexes is not None and isinstance(entities, dict):
        for order_id in entities.get("order_ids", []):
            if not isinstance(order_id, str) or order_id not in indexes.orders_by_id:
                errors.append(f"affected order_id does not exist: {order_id}")
        for seller_id in entities.get("seller_ids", []):
            if not isinstance(seller_id, str) or seller_id not in indexes.sellers_by_id:
                errors.append(f"affected seller_id does not exist: {seller_id}")
        for item_id in entities.get("item_ids", []):
            if not isinstance(item_id, str) or not _valid_source_evidence(
                f"item:{item_id}", indexes
            ):
                errors.append(f"affected item_id does not exist: {item_id}")
        for payment_id in entities.get("payment_ids", []):
            if not isinstance(payment_id, str) or not _valid_source_evidence(
                f"payment:{payment_id}", indexes
            ):
                errors.append(f"affected payment_id does not exist: {payment_id}")

    product = candidate.get("product_context", {})
    if indexes is not None and isinstance(product, dict):
        errors.extend(
            f"product_id does not exist: {product_id}"
            for product_id in product.get("product_ids", [])
            if not isinstance(product_id, str)
            or product_id not in indexes.products_by_id
        )

    return VerificationResult(valid=not errors, errors=errors, candidate=candidate)
