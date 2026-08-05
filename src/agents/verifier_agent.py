"""Verifier Agent: assembles the graded JSON and gates it before it is written.

Deliberately pure code, no LLM. A small model cannot be the last line of
defence for schema conformance, so every check here is regex/set-membership
against the data that was actually loaded for this order.
"""

import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.policy_rules import (
    CAUSE_CANCELED,
    CAUSE_CARRIER_LATE,
    CAUSE_PAYMENTS_RECONCILED,
    CAUSE_SELLER_HANDOFF,
    CAUSE_UNAVAILABLE,
    CAUSE_WITHIN_ESTIMATE,
    PRIMARY_CANCELED,
    PRIMARY_LATE_LOGISTICS,
    PRIMARY_LATE_SELLER,
    PRIMARY_UNAVAILABLE,
    PRIMARY_UNSUPPORTED,
    PRIMARY_VALID_SPLIT,
)

# ----------------- OUTPUT SCHEMA (pydantic) -----------------

class RankedCause(BaseModel):
    cause_code: str = ""
    rank: int = 0

class ResponsibleParty(BaseModel):
    party_type: str = ""
    party_id: str = ""

class CaseAssessment(BaseModel):
    primary_issue: str = ""
    secondary_issues: List[str] = Field(default_factory=list)
    case_status: str = "no_action"
    confidence: float = 1.0

class AffectedEntities(BaseModel):
    order_ids: List[str] = Field(default_factory=list)
    item_ids: List[str] = Field(default_factory=list)
    seller_ids: List[str] = Field(default_factory=list)
    payment_ids: List[str] = Field(default_factory=list)

class CustomerContext(BaseModel):
    customer_unique_id: str = ""
    related_order_ids: List[str] = Field(default_factory=list)

class ProductContext(BaseModel):
    product_ids: List[str] = Field(default_factory=list)
    category_names: List[str] = Field(default_factory=list)

class SellerHandoff(BaseModel):
    seller_id: str = ""
    shipping_limit_at: Optional[str] = None
    handoff_variance_hours: Optional[float] = None
    late_handoff: bool = False

class DeliveryAnalysis(BaseModel):
    delivered_at: Optional[str] = None
    estimated_delivery_at: Optional[str] = None
    carrier_handoff_at: Optional[str] = None
    delivery_variance_hours: Optional[float] = None
    seller_handoff_analysis: List[SellerHandoff] = Field(default_factory=list)
    late_handoff_seller_ids: List[str] = Field(default_factory=list)

class PaymentReconciliation(BaseModel):
    currency: str = "BRL"
    item_total_brl: Optional[float] = None
    freight_total_brl: Optional[float] = None
    expected_total_brl: Optional[float] = None
    payment_total_brl: Optional[float] = None
    difference_brl: Optional[float] = None
    reconciled: Optional[bool] = None
    payment_types: List[str] = Field(default_factory=list)

class RootCauseAnalysis(BaseModel):
    ranked_causes: List[RankedCause] = Field(default_factory=list)
    responsible_parties: List[ResponsibleParty] = Field(default_factory=list)

class FinancialResolution(BaseModel):
    currency: str = "BRL"
    recommended_refund_brl: float = 0.0

class FinalResolution(BaseModel):
    case_id: str
    case_assessment: CaseAssessment
    affected_entities: AffectedEntities
    customer_context: CustomerContext
    product_context: ProductContext
    delivery_analysis: DeliveryAnalysis
    payment_reconciliation: PaymentReconciliation
    root_cause_analysis: RootCauseAnalysis
    evidence_ids: List[str] = Field(default_factory=list)
    financial_resolution: FinancialResolution
    resolution_actions: List[str] = Field(default_factory=list)


def build_final(
    case_id: str,
    order_id: str,
    customer_context: Dict,
    order: Dict,
    payment: Dict,
    delivery: Dict,
    resolution: Dict,
    evidence_ids: List[str],
    affected_entities: Dict,
    product_context: Dict,
    confidence: float,
) -> FinalResolution:
    return FinalResolution(
        case_id=case_id,
        case_assessment=CaseAssessment(
            primary_issue=resolution["primary_issue"],
            secondary_issues=resolution["secondary_issues"],
            case_status=resolution["case_status"],
            confidence=confidence,
        ),
        affected_entities=AffectedEntities(**affected_entities),
        customer_context=CustomerContext(**customer_context),
        product_context=ProductContext(**product_context),
        delivery_analysis=DeliveryAnalysis(**delivery),
        payment_reconciliation=PaymentReconciliation(
            currency="BRL",
            item_total_brl=payment.get("item_total_brl"),
            freight_total_brl=payment.get("freight_total_brl"),
            expected_total_brl=payment.get("expected_total_brl"),
            payment_total_brl=payment.get("payment_total_brl"),
            difference_brl=payment.get("difference_brl"),
            reconciled=payment.get("reconciled"),
            payment_types=payment.get("payment_types", []),
        ),
        root_cause_analysis=RootCauseAnalysis(
            ranked_causes=[RankedCause(**rc) for rc in resolution.get("ranked_causes", [])],
            responsible_parties=[ResponsibleParty(**rp) for rp in resolution.get("responsible_parties", [])[:3]],
        ),
        evidence_ids=evidence_ids,
        financial_resolution=FinancialResolution(
            currency="BRL",
            recommended_refund_brl=resolution.get("refund_brl", 0.0),
        ),
        resolution_actions=resolution.get("resolution_actions", [])[:5],
    )


# ----------------- VALIDATION GATE (regex + business-rule cross-check) -----------------

ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
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
    PRIMARY_CANCELED,
    PRIMARY_UNAVAILABLE,
    PRIMARY_LATE_SELLER,
    PRIMARY_LATE_LOGISTICS,
    PRIMARY_VALID_SPLIT,
    PRIMARY_UNSUPPORTED,
}

VALID_SECONDARY_ISSUES = {
    "multi_item_order",
    "multi_seller_order",
    "split_payment",
    "repeat_customer",
    "multiple_categories",
}

VALID_CAUSE_CODES = {
    CAUSE_SELLER_HANDOFF,
    CAUSE_CARRIER_LATE,
    CAUSE_CANCELED,
    CAUSE_UNAVAILABLE,
    CAUSE_PAYMENTS_RECONCILED,
    CAUSE_WITHIN_ESTIMATE,
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


def enforce_limits(output: Dict) -> Dict:
    """Trim every array to its cap. Applied before verification so an
    oversized case cannot fail the gate on length alone."""
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


def _check_timestamp(value, field, errors):
    if value is None:
        return
    if not isinstance(value, str) or not TIMESTAMP_PATTERN.match(value):
        errors.append("%s is not YYYY-MM-DD HH:MM:SS or null: %r" % (field, value))


def _valid_evidence_format(evidence_id):
    return any(pattern.match(evidence_id) for pattern in EVIDENCE_PATTERNS)


def build_valid_evidence_set(order_id, raw_items, raw_payments, seller_ids):
    """Every evidence ID that the loaded CSV rows can actually justify."""
    valid = {"order:%s" % order_id}
    for item in raw_items:
        iid = item.get("order_item_id")
        if iid is not None:
            valid.add("item:%s:%s" % (order_id, int(iid)))
    for payment in raw_payments:
        seq = payment.get("payment_sequential")
        if seq is not None:
            valid.add("payment:%s:%s" % (order_id, int(seq)))
    for seller_id in seller_ids:
        valid.add("seller:%s" % seller_id)
    for code in VALID_CAUSE_CODES:
        valid.add("policy:%s" % code)
    return valid


def verify_output(output: Dict, order_id: str, raw_items: List[Dict],
                   raw_payments: List[Dict], related_order_ids: List[str],
                   seller_ids: List[str]) -> (List[str], List[str]):
    """Return (errors, warnings). Errors mean the case would be graded wrong."""
    errors: List[str] = []
    warnings: List[str] = []

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

    entities = output.get("affected_entities", {})
    if entities.get("order_ids") != [order_id]:
        errors.append("affected_entities.order_ids must be exactly the claimed order")

    for item_id in entities.get("item_ids", []):
        if not re.match(r"^[0-9a-f]{32}:\d+$", str(item_id)):
            errors.append("malformed item_id: %r" % item_id)

    valid_seller_ids = set(seller_ids)
    for seller_id in entities.get("seller_ids", []):
        if seller_id not in valid_seller_ids:
            errors.append("seller_id not in order: %r" % seller_id)

    context = output.get("customer_context", {})
    related = context.get("related_order_ids", [])
    if order_id in related:
        errors.append("claimed order must not appear in related_order_ids")
    valid_related = set(related_order_ids)
    for related_id in related:
        if related_id not in valid_related:
            errors.append("related_order_id not from this customer: %r" % related_id)

    product_context = output.get("product_context", {})

    delivery = output.get("delivery_analysis", {})
    _check_timestamp(delivery.get("delivered_at"), "delivered_at", errors)
    _check_timestamp(delivery.get("estimated_delivery_at"), "estimated_delivery_at", errors)
    _check_timestamp(delivery.get("carrier_handoff_at"), "carrier_handoff_at", errors)
    for entry in delivery.get("seller_handoff_analysis", []):
        _check_timestamp(entry.get("shipping_limit_at"), "shipping_limit_at", errors)

    payment = output.get("payment_reconciliation", {})
    if not raw_items:
        for field in ("expected_total_brl", "difference_brl", "reconciled"):
            if payment.get(field) is not None:
                errors.append("%s must be null when the order has no item row" % field)
        if delivery.get("seller_handoff_analysis"):
            errors.append("seller_handoff_analysis must be empty with no item rows")
        if entities.get("item_ids") or entities.get("seller_ids"):
            errors.append("item/seller arrays must be empty with no item rows")
        if product_context.get("product_ids") or product_context.get("category_names"):
            errors.append("product/category arrays must be empty with no item rows")

    valid_evidence = build_valid_evidence_set(order_id, raw_items, raw_payments, seller_ids)
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

    refund = output.get("financial_resolution", {}).get("recommended_refund_brl")
    if not isinstance(refund, (int, float)) or refund < 0:
        errors.append("recommended_refund_brl invalid: %r" % refund)
    else:
        expected_status = "action_required" if refund > 0 else "no_action"
        if status != expected_status:
            errors.append("case_status %r disagrees with refund %r" % (status, refund))

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
            errors.append("%s exceeds limit %d (got %d)" % (field, ARRAY_LIMITS[field], len(values)))

    return errors, warnings
