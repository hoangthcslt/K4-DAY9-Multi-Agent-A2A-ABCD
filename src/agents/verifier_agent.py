"""Verifier Agent: the gate every case must pass before a file is written.

Reads: the assembled output plus the case bundle it must be consistent with.
Hands off: pass/fail plus a repaired output to the Coordinator.

Deliberately pure code. A small model cannot be the last line of defence for
schema conformance, so the checks here are regex and set membership against the
bundle that the data layer actually loaded.
"""

import re

TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

EVIDENCE_PATTERNS = [
    re.compile(r"^order:[0-9a-f]{32}$"),
    re.compile(r"^item:[0-9a-f]{32}:\d+$"),
    re.compile(r"^payment:[0-9a-f]{32}:\d+$"),
    re.compile(r"^seller:[0-9a-f]{32}$"),
    re.compile(r"^policy:[A-Z_]+$"),
]

VALID_CASE_STATUS = {"action_required", "no_action"}

VALID_PRIMARY_ISSUES = {
    "canceled_order_paid",
    "unavailable_order_paid",
    "late_delivery_seller",
    "late_delivery_logistics",
    "valid_split_payment",
    "unsupported_late_claim",
}

VALID_SECONDARY_ISSUES = {
    "multi_item_order",
    "multi_seller_order",
    "split_payment",
    "repeat_customer",
    "multiple_categories",
}

VALID_CAUSE_CODES = {
    "SELLER_HANDOFF_AFTER_LIMIT",
    "CARRIER_DELIVERED_AFTER_ESTIMATE",
    "ORDER_CANCELED_AFTER_PAYMENT",
    "ORDER_UNAVAILABLE_AFTER_PAYMENT",
    "MULTIPLE_PAYMENTS_RECONCILED",
    "DELIVERY_WITHIN_ESTIMATE",
}

VALID_ACTIONS = {
    "issue_full_refund",
    "refund_freight",
    "explain_valid_split_payment",
    "reject_late_refund",
    "review_seller_handoff",
    "review_carrier_delay",
    "verify_refund_completion",
    "coordinate_multi_seller_case",
    "verify_payment_allocation",
}

# Array caps from README section 6.
ARRAY_LIMITS = {
    "order_ids": 5,
    "item_ids": 5,
    "seller_ids": 3,
    "payment_ids": 5,
    "related_order_ids": 5,
    "product_ids": 5,
    "category_names": 5,
    "ranked_causes": 3,
    "responsible_parties": 3,
    "evidence_ids": 20,
    "resolution_actions": 5,
}


def _check_timestamp(value, field, errors):
    if value is None:
        return
    if not isinstance(value, str) or not TIMESTAMP_PATTERN.match(value):
        errors.append("%s is not YYYY-MM-DD HH:MM:SS or null: %r" % (field, value))


def _valid_evidence_format(evidence_id):
    return any(pattern.match(evidence_id) for pattern in EVIDENCE_PATTERNS)


def build_valid_evidence_set(bundle):
    """Every evidence ID that the loaded CSV rows can actually justify."""
    order_id = bundle["order_id"]
    valid = {"order:%s" % order_id}
    for item in bundle["items"]:
        valid.add("item:%s:%s" % (order_id, item["order_item_id"]))
    for payment in bundle["payments"]:
        valid.add("payment:%s:%s" % (order_id, payment["payment_sequential"]))
    for seller_id in bundle["seller_ids"]:
        valid.add("seller:%s" % seller_id)
    for code in VALID_CAUSE_CODES:
        valid.add("policy:%s" % code)
    return valid


def verify_output(output, bundle):
    """Return (errors, warnings). Errors mean the case would be graded wrong."""
    errors = []
    warnings = []

    if output.get("case_id") != bundle.get("case_id", output.get("case_id")):
        pass  # case_id is set by the coordinator, checked by the caller

    assessment = output.get("case_assessment", {})

    primary = assessment.get("primary_issue")
    if primary not in VALID_PRIMARY_ISSUES:
        errors.append("invalid primary_issue: %r" % primary)

    secondary = assessment.get("secondary_issues", [])
    for issue in secondary:
        if issue not in VALID_SECONDARY_ISSUES:
            errors.append("invalid secondary_issue: %r" % issue)
    if len(set(secondary)) != len(secondary):
        errors.append("duplicate secondary_issues")

    status = assessment.get("case_status")
    if status not in VALID_CASE_STATUS:
        errors.append("invalid case_status: %r" % status)

    confidence = assessment.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0.0 <= confidence <= 1.0:
        errors.append("confidence out of [0,1]: %r" % confidence)

    # Affected entities must describe the claimed order only.
    entities = output.get("affected_entities", {})
    if entities.get("order_ids") != [bundle["order_id"]]:
        errors.append("affected_entities.order_ids must be exactly the claimed order")

    for item_id in entities.get("item_ids", []):
        if not re.match(r"^[0-9a-f]{32}:\d+$", str(item_id)):
            errors.append("malformed item_id: %r" % item_id)

    valid_seller_ids = set(bundle["seller_ids"])
    for seller_id in entities.get("seller_ids", []):
        if seller_id not in valid_seller_ids:
            errors.append("seller_id not in order: %r" % seller_id)

    # History orders belong in customer_context, never in affected_entities.
    context = output.get("customer_context", {})
    related = context.get("related_order_ids", [])
    if bundle["order_id"] in related:
        errors.append("claimed order must not appear in related_order_ids")
    valid_related = set(bundle["related_order_ids"])
    for related_id in related:
        if related_id not in valid_related:
            errors.append("related_order_id not from this customer: %r" % related_id)

    product_context = output.get("product_context", {})
    valid_product_ids = set(bundle["product_ids"])
    for product_id in product_context.get("product_ids", []):
        if product_id not in valid_product_ids:
            errors.append("product_id not in order: %r" % product_id)

    # Delivery timestamps keep the CSV format or are null.
    delivery = output.get("delivery_analysis", {})
    _check_timestamp(delivery.get("delivered_at"), "delivered_at", errors)
    _check_timestamp(delivery.get("estimated_delivery_at"), "estimated_delivery_at", errors)
    _check_timestamp(delivery.get("carrier_handoff_at"), "carrier_handoff_at", errors)
    for entry in delivery.get("seller_handoff_analysis", []):
        _check_timestamp(entry.get("shipping_limit_at"), "shipping_limit_at", errors)

    # No item rows means the money fields must be null, arrays empty.
    payment = output.get("payment_reconciliation", {})
    if not bundle["items"]:
        for field in ("expected_total_brl", "difference_brl", "reconciled"):
            if payment.get(field) is not None:
                errors.append("%s must be null when the order has no item row" % field)
        if delivery.get("seller_handoff_analysis"):
            errors.append("seller_handoff_analysis must be empty with no item rows")
        if entities.get("item_ids") or entities.get("seller_ids"):
            errors.append("item/seller arrays must be empty with no item rows")
        if product_context.get("product_ids") or product_context.get("category_names"):
            errors.append("product/category arrays must be empty with no item rows")

    # Evidence must be well-formed AND constructible from the loaded rows.
    valid_evidence = build_valid_evidence_set(bundle)
    evidence_ids = output.get("evidence_ids", [])
    for evidence_id in evidence_ids:
        if not _valid_evidence_format(evidence_id):
            errors.append("malformed evidence id: %r" % evidence_id)
        elif evidence_id not in valid_evidence:
            errors.append("evidence id not backed by data: %r" % evidence_id)
    if len(set(evidence_ids)) != len(evidence_ids):
        errors.append("duplicate evidence_ids")

    root_cause = output.get("root_cause_analysis", {})
    ranked = root_cause.get("ranked_causes", [])
    for index, cause in enumerate(ranked):
        if cause.get("cause_code") not in VALID_CAUSE_CODES:
            errors.append("invalid cause_code: %r" % cause.get("cause_code"))
        if cause.get("rank") != index + 1:
            errors.append("ranked_causes rank must start at 1 and increment")

    for party in root_cause.get("responsible_parties", []):
        if party.get("party_type") not in ("seller", "platform", "logistics_provider"):
            errors.append("invalid party_type: %r" % party.get("party_type"))
        if party.get("party_type") == "seller" and party.get("party_id") not in valid_seller_ids:
            errors.append("responsible seller not in order: %r" % party.get("party_id"))

    actions = output.get("resolution_actions", [])
    for action in actions:
        if action not in VALID_ACTIONS:
            errors.append("invalid action: %r" % action)
    if len(set(actions)) != len(actions):
        errors.append("duplicate resolution_actions")

    # Refund and case_status must agree.
    refund = output.get("financial_resolution", {}).get("recommended_refund_brl")
    if not isinstance(refund, (int, float)) or refund < 0:
        errors.append("recommended_refund_brl invalid: %r" % refund)
    else:
        expected_status = "action_required" if refund > 0 else "no_action"
        if status != expected_status:
            errors.append(
                "case_status %r disagrees with refund %r" % (status, refund)
            )

    # Array caps.
    countable = {
        "order_ids": entities.get("order_ids", []),
        "item_ids": entities.get("item_ids", []),
        "seller_ids": entities.get("seller_ids", []),
        "payment_ids": entities.get("payment_ids", []),
        "related_order_ids": related,
        "product_ids": product_context.get("product_ids", []),
        "category_names": product_context.get("category_names", []),
        "ranked_causes": ranked,
        "responsible_parties": root_cause.get("responsible_parties", []),
        "evidence_ids": evidence_ids,
        "resolution_actions": actions,
    }
    for field, values in countable.items():
        if len(values) > ARRAY_LIMITS[field]:
            errors.append(
                "%s exceeds limit %d (got %d)" % (field, ARRAY_LIMITS[field], len(values))
            )

    return errors, warnings


def enforce_limits(output):
    """Trim every array to its cap. Applied before verification so an oversized
    order cannot fail the gate on length alone."""
    entities = output.get("affected_entities", {})
    entities["order_ids"] = entities.get("order_ids", [])[: ARRAY_LIMITS["order_ids"]]
    entities["item_ids"] = entities.get("item_ids", [])[: ARRAY_LIMITS["item_ids"]]
    entities["seller_ids"] = entities.get("seller_ids", [])[: ARRAY_LIMITS["seller_ids"]]
    entities["payment_ids"] = entities.get("payment_ids", [])[: ARRAY_LIMITS["payment_ids"]]

    context = output.get("customer_context", {})
    context["related_order_ids"] = context.get("related_order_ids", [])[
        : ARRAY_LIMITS["related_order_ids"]
    ]

    product_context = output.get("product_context", {})
    product_context["product_ids"] = product_context.get("product_ids", [])[
        : ARRAY_LIMITS["product_ids"]
    ]
    product_context["category_names"] = product_context.get("category_names", [])[
        : ARRAY_LIMITS["category_names"]
    ]

    root_cause = output.get("root_cause_analysis", {})
    root_cause["ranked_causes"] = root_cause.get("ranked_causes", [])[
        : ARRAY_LIMITS["ranked_causes"]
    ]
    root_cause["responsible_parties"] = root_cause.get("responsible_parties", [])[
        : ARRAY_LIMITS["responsible_parties"]
    ]

    output["evidence_ids"] = output.get("evidence_ids", [])[: ARRAY_LIMITS["evidence_ids"]]
    output["resolution_actions"] = output.get("resolution_actions", [])[
        : ARRAY_LIMITS["resolution_actions"]
    ]
    return output
