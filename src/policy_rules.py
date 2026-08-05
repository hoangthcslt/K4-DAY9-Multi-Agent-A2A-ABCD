"""EC_POLICY_V2 implemented as deterministic code.

Every number in the graded output is produced here from the case bundle. The
LLM agents interpret and narrate these facts but never compute them, because
arithmetic and rule precedence are exactly what a small model gets wrong.
"""

from datetime import datetime

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
RECONCILE_TOLERANCE_BRL = 0.10

PRIMARY_CANCELED = "canceled_order_paid"
PRIMARY_UNAVAILABLE = "unavailable_order_paid"
PRIMARY_LATE_SELLER = "late_delivery_seller"
PRIMARY_LATE_LOGISTICS = "late_delivery_logistics"
PRIMARY_VALID_SPLIT = "valid_split_payment"
PRIMARY_UNSUPPORTED = "unsupported_late_claim"

CAUSE_SELLER_HANDOFF = "SELLER_HANDOFF_AFTER_LIMIT"
CAUSE_CARRIER_LATE = "CARRIER_DELIVERED_AFTER_ESTIMATE"
CAUSE_CANCELED = "ORDER_CANCELED_AFTER_PAYMENT"
CAUSE_UNAVAILABLE = "ORDER_UNAVAILABLE_AFTER_PAYMENT"
CAUSE_PAYMENTS_RECONCILED = "MULTIPLE_PAYMENTS_RECONCILED"
CAUSE_WITHIN_ESTIMATE = "DELIVERY_WITHIN_ESTIMATE"

PLATFORM_PARTY_ID = "OLIST_PLATFORM"
LOGISTICS_PARTY_ID = "LOGISTICS_PROVIDER"


def _parse(timestamp):
    if not timestamp:
        return None
    return datetime.strptime(timestamp, TIMESTAMP_FORMAT)


def _hours_between(later, earlier):
    """Signed hour difference, rounded to 2 decimals. None if either is missing."""
    if later is None or earlier is None:
        return None
    return round((later - earlier).total_seconds() / 3600.0, 2)


def _money(value):
    return round(value + 0.0, 2)


def analyze_delivery(bundle):
    """delivery_analysis block: variance vs estimate and per-seller handoff."""
    order = bundle["order"]
    delivered_at = order["order_delivered_customer_date"]
    estimated_at = order["order_estimated_delivery_date"]
    carrier_at = order["order_delivered_carrier_date"]

    delivery_variance_hours = _hours_between(_parse(delivered_at), _parse(estimated_at))

    # Each seller is judged against its own earliest shipping_limit_date, using
    # the single carrier handoff timestamp the order records.
    earliest_limit_by_seller = {}
    for item in bundle["items"]:
        seller_id = item["seller_id"]
        limit = item["shipping_limit_date"]
        if limit is None:
            continue
        current = earliest_limit_by_seller.get(seller_id)
        if current is None or limit < current:
            earliest_limit_by_seller[seller_id] = limit

    carrier_dt = _parse(carrier_at)
    seller_handoff_analysis = []
    late_handoff_seller_ids = []
    if carrier_dt is not None:
        # handoff_variance_hours needs order_delivered_carrier_date; with no
        # carrier handoff yet (e.g. a canceled order) there is nothing to
        # report, so the array stays empty rather than holding null variances.
        for seller_id in bundle["seller_ids"]:
            shipping_limit_at = earliest_limit_by_seller.get(seller_id)
            handoff_variance_hours = _hours_between(carrier_dt, _parse(shipping_limit_at))
            late_handoff = handoff_variance_hours is not None and handoff_variance_hours > 0
            seller_handoff_analysis.append(
                {
                    "seller_id": seller_id,
                    "shipping_limit_at": shipping_limit_at,
                    "handoff_variance_hours": handoff_variance_hours,
                    "late_handoff": late_handoff,
                }
            )
            if late_handoff:
                late_handoff_seller_ids.append(seller_id)

    return {
        "delivered_at": delivered_at,
        "estimated_delivery_at": estimated_at,
        "carrier_handoff_at": carrier_at,
        "delivery_variance_hours": delivery_variance_hours,
        "seller_handoff_analysis": seller_handoff_analysis,
        "late_handoff_seller_ids": late_handoff_seller_ids,
    }


def analyze_payment(bundle):
    """payment_reconciliation block. Orders with no item row report nulls."""
    items = bundle["items"]
    payments = bundle["payments"]

    payment_total = _money(sum(p["payment_value"] for p in payments))

    payment_types = []
    for payment in payments:
        if payment["payment_type"] not in payment_types:
            payment_types.append(payment["payment_type"])

    if not items:
        # README section 4: no item row means these fields must be null.
        return {
            "currency": "BRL",
            "item_total_brl": None,
            "freight_total_brl": None,
            "expected_total_brl": None,
            "payment_total_brl": payment_total,
            "difference_brl": None,
            "reconciled": None,
            "payment_types": payment_types,
        }

    item_total = _money(sum(i["price"] for i in items))
    freight_total = _money(sum(i["freight_value"] for i in items))
    expected_total = _money(item_total + freight_total)
    difference = _money(payment_total - expected_total)

    return {
        "currency": "BRL",
        "item_total_brl": item_total,
        "freight_total_brl": freight_total,
        "expected_total_brl": expected_total,
        "payment_total_brl": payment_total,
        "difference_brl": difference,
        "reconciled": abs(difference) <= RECONCILE_TOLERANCE_BRL,
        "payment_types": payment_types,
    }


def _is_delivered_late(delivery):
    variance = delivery["delivery_variance_hours"]
    return variance is not None and variance > 0


def determine_primary_issue(bundle, delivery, payment):
    """Walk the EC_POLICY_V2 table top to bottom; first match wins."""
    status = bundle["order"]["order_status"]
    payment_total = payment["payment_total_brl"]
    reconciled = payment["reconciled"]
    delivered_late = _is_delivered_late(delivery)
    has_late_seller = bool(delivery["late_handoff_seller_ids"])

    if status == "canceled" and payment_total > 0:
        return PRIMARY_CANCELED
    if status == "unavailable" and payment_total > 0:
        return PRIMARY_UNAVAILABLE
    if delivered_late and has_late_seller:
        return PRIMARY_LATE_SELLER
    if delivered_late and not has_late_seller:
        return PRIMARY_LATE_LOGISTICS
    if len(bundle["payments"]) >= 2 and reconciled is True:
        return PRIMARY_VALID_SPLIT
    return PRIMARY_UNSUPPORTED


def determine_secondary_issues(bundle):
    """Fixed evaluation order per README section 4."""
    issues = []
    if len(bundle["items"]) >= 2:
        issues.append("multi_item_order")
    if len(bundle["seller_ids"]) >= 2:
        issues.append("multi_seller_order")
    if len(bundle["payments"]) >= 2:
        issues.append("split_payment")
    if bundle["related_order_ids"]:
        issues.append("repeat_customer")
    if len(bundle["category_names"]) >= 2:
        issues.append("multiple_categories")
    return issues


def determine_responsibility(primary_issue, bundle, delivery):
    """Returns (responsible_parties, ranked_cause_codes) for the primary issue."""
    if primary_issue == PRIMARY_CANCELED:
        return (
            [{"party_type": "platform", "party_id": PLATFORM_PARTY_ID}],
            [CAUSE_CANCELED],
        )

    if primary_issue == PRIMARY_UNAVAILABLE:
        return (
            [{"party_type": "platform", "party_id": PLATFORM_PARTY_ID}],
            [CAUSE_UNAVAILABLE],
        )

    if primary_issue == PRIMARY_LATE_SELLER:
        parties = [
            {"party_type": "seller", "party_id": seller_id}
            for seller_id in delivery["late_handoff_seller_ids"]
        ]
        return parties, [CAUSE_SELLER_HANDOFF]

    if primary_issue == PRIMARY_LATE_LOGISTICS:
        return (
            [{"party_type": "logistics_provider", "party_id": LOGISTICS_PARTY_ID}],
            [CAUSE_CARRIER_LATE],
        )

    if primary_issue == PRIMARY_VALID_SPLIT:
        return [], [CAUSE_PAYMENTS_RECONCILED]

    return [], [CAUSE_WITHIN_ESTIMATE]


def determine_refund(primary_issue, payment):
    """Refund amount per the policy table."""
    if primary_issue in (PRIMARY_CANCELED, PRIMARY_UNAVAILABLE):
        return _money(payment["payment_total_brl"])
    if primary_issue in (PRIMARY_LATE_SELLER, PRIMARY_LATE_LOGISTICS):
        freight_total = payment["freight_total_brl"]
        return _money(freight_total) if freight_total is not None else 0.0
    return 0.0


def determine_actions(primary_issue, bundle, delivery):
    """Primary action first, then the fixed-order supplementary actions."""
    if primary_issue in (PRIMARY_CANCELED, PRIMARY_UNAVAILABLE):
        actions = ["issue_full_refund"]
    elif primary_issue in (PRIMARY_LATE_SELLER, PRIMARY_LATE_LOGISTICS):
        actions = ["refund_freight"]
    elif primary_issue == PRIMARY_VALID_SPLIT:
        actions = ["explain_valid_split_payment"]
    else:
        actions = ["reject_late_refund"]

    # Order fixed by README section 4.
    if primary_issue == PRIMARY_LATE_SELLER:
        actions.append("review_seller_handoff")
    elif primary_issue == PRIMARY_LATE_LOGISTICS:
        actions.append("review_carrier_delay")

    if primary_issue in (PRIMARY_CANCELED, PRIMARY_UNAVAILABLE):
        actions.append("verify_refund_completion")

    if len(bundle["seller_ids"]) >= 2:
        actions.append("coordinate_multi_seller_case")

    # The valid_split_payment primary action already explains the split, so the
    # policy explicitly suppresses this one.
    if len(bundle["payments"]) >= 2 and primary_issue != PRIMARY_VALID_SPLIT:
        actions.append("verify_payment_allocation")

    return actions


def build_evidence_ids(bundle, responsible_parties, cause_codes):
    """Only IDs that can be constructed straight from the CSV rows."""
    order_id = bundle["order_id"]
    evidence = ["order:%s" % order_id]

    for item in bundle["items"]:
        evidence.append("item:%s:%s" % (order_id, item["order_item_id"]))

    for payment in bundle["payments"]:
        evidence.append("payment:%s:%s" % (order_id, payment["payment_sequential"]))

    for party in responsible_parties:
        if party["party_type"] == "seller":
            evidence.append("seller:%s" % party["party_id"])

    for cause_code in cause_codes:
        evidence.append("policy:%s" % cause_code)

    return evidence


def apply_policy(bundle):
    """Full deterministic assessment for one case bundle."""
    delivery = analyze_delivery(bundle)
    payment = analyze_payment(bundle)

    primary_issue = determine_primary_issue(bundle, delivery, payment)
    secondary_issues = determine_secondary_issues(bundle)
    responsible_parties, cause_codes = determine_responsibility(
        primary_issue, bundle, delivery
    )
    refund = determine_refund(primary_issue, payment)
    actions = determine_actions(primary_issue, bundle, delivery)
    evidence_ids = build_evidence_ids(bundle, responsible_parties, cause_codes)

    case_status = "action_required" if refund > 0 else "no_action"

    ranked_causes = [
        {"cause_code": code, "rank": index + 1}
        for index, code in enumerate(cause_codes)
    ]

    return {
        "primary_issue": primary_issue,
        "secondary_issues": secondary_issues,
        "case_status": case_status,
        "delivery_analysis": delivery,
        "payment_reconciliation": payment,
        "ranked_causes": ranked_causes,
        "responsible_parties": responsible_parties,
        "evidence_ids": evidence_ids,
        "recommended_refund_brl": refund,
        "resolution_actions": actions,
    }
