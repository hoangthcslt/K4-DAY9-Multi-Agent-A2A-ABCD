"""EC_POLICY_V2 implemented as deterministic code.

Every number and category in the graded output is produced here, ported
unchanged in substance from the original single-file src/agents.py so none of
the already-verified 50 outputs change value. The LLM agents in src/agents/
interpret and narrate these facts but never compute or override them -
arithmetic and rule precedence are exactly what a small model gets wrong.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

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


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s or str(s) == "nan" or str(s).lower() == "none":
        return None
    try:
        return datetime.strptime(str(s).strip(), TIMESTAMP_FORMAT)
    except ValueError:
        return None


def _diff_hours(d1: Optional[datetime], d2: Optional[datetime]) -> Optional[float]:
    if d1 is None or d2 is None:
        return None
    return round((d1 - d2).total_seconds() / 3600.0, 2)


def _round2(v) -> Optional[float]:
    if v is None:
        return None
    return round(float(v), 2)


def analyze_order_product(order_id: str, raw_items: List[Dict]) -> Dict[str, Any]:
    """Order composition: item/product/seller/category ids."""
    if not raw_items:
        return {"product_ids": [], "category_names": [], "seller_ids": [], "item_ids": []}

    sorted_items = sorted(raw_items, key=lambda x: int(x.get("order_item_id", 0) or 0))

    seen_products, seen_categories, seen_sellers = [], [], []
    item_ids = []

    for item in sorted_items:
        pid = str(item.get("product_id") or "")
        cat = str(item.get("product_category_name") or "")
        sid = str(item.get("seller_id") or "")
        iid = item.get("order_item_id")
        item_ids.append(f"{order_id}:{int(iid)}" if iid else f"{order_id}:?")
        if pid and pid not in seen_products:
            seen_products.append(pid)
        if cat and cat not in seen_categories:
            seen_categories.append(cat)
        if sid and sid not in seen_sellers:
            seen_sellers.append(sid)

    return {
        "product_ids": seen_products[:5],
        "category_names": seen_categories[:5],
        "seller_ids": seen_sellers[:3],
        "item_ids": item_ids[:5],
    }


def analyze_payment(order_id: str, raw_items: List[Dict], raw_payments: List[Dict]) -> Dict[str, Any]:
    """payment_reconciliation block. Orders with no item row report nulls per
    README section 4."""
    sorted_payments = sorted(raw_payments, key=lambda x: int(x.get("payment_sequential", 0) or 0))
    payment_ids = [
        f"{order_id}:{int(p['payment_sequential'])}"
        for p in sorted_payments
        if p.get("payment_sequential") is not None
    ][:5]
    payment_types = list(dict.fromkeys(
        p["payment_type"] for p in sorted_payments if p.get("payment_type")
    ))
    raw_payments = sorted_payments
    payment_total = _round2(sum(p["payment_value"] for p in raw_payments if p.get("payment_value") is not None))

    if not raw_items:
        return {
            "item_total_brl": 0.0, "freight_total_brl": 0.0,
            "expected_total_brl": None, "payment_total_brl": payment_total,
            "difference_brl": None, "reconciled": None,
            "payment_types": payment_types, "payment_ids": payment_ids,
        }

    item_total = _round2(sum(i["price"] for i in raw_items if i.get("price") is not None))
    freight_total = _round2(sum(i["freight_value"] for i in raw_items if i.get("freight_value") is not None))
    expected = _round2(item_total + freight_total)
    difference = _round2(payment_total - expected)
    reconciled = abs(difference) <= RECONCILE_TOLERANCE_BRL if difference is not None else None

    return {
        "item_total_brl": item_total,
        "freight_total_brl": freight_total,
        "expected_total_brl": expected,
        "payment_total_brl": payment_total,
        "difference_brl": difference,
        "reconciled": reconciled,
        "payment_types": payment_types,
        "payment_ids": payment_ids,
    }


def analyze_delivery(delivery_info: Dict, raw_items: List[Dict]) -> Dict[str, Any]:
    """delivery_analysis block: variance vs estimate and per-seller handoff.

    Only sellers with at least one item row whose shipping_limit_date can be
    parsed get an entry in seller_handoff_analysis (matches the original
    agents.py behaviour exactly - do not switch to "one entry per seller even
    with a null limit", which would change output for edge-case orders).
    """
    delivered_at = delivery_info.get("order_delivered_customer_date")
    estimated_at = delivery_info.get("order_estimated_delivery_date")
    carrier_at = delivery_info.get("order_delivered_carrier_date")

    d_delivered = _parse_dt(delivered_at)
    d_estimated = _parse_dt(estimated_at)
    d_carrier = _parse_dt(carrier_at)

    delivery_variance = _diff_hours(d_delivered, d_estimated)

    seller_limits: Dict[str, datetime] = {}
    seller_limit_str: Dict[str, str] = {}
    for item in raw_items:
        sid = str(item.get("seller_id") or "")
        sld_str = item.get("shipping_limit_date")
        sld = _parse_dt(sld_str)
        if sid and sld:
            if sid not in seller_limits or sld < seller_limits[sid]:
                seller_limits[sid] = sld
                seller_limit_str[sid] = str(sld_str)

    seller_handoff_analysis = []
    late_seller_ids = []

    for sid, effective_limit in seller_limits.items():
        handoff_var = _diff_hours(d_carrier, effective_limit)
        is_late = handoff_var is not None and handoff_var > 0
        seller_handoff_analysis.append({
            "seller_id": sid,
            "shipping_limit_at": seller_limit_str.get(sid),
            "handoff_variance_hours": handoff_var,
            "late_handoff": is_late,
        })
        if is_late:
            late_seller_ids.append(sid)

    return {
        "delivered_at": str(delivered_at) if delivered_at else None,
        "estimated_delivery_at": str(estimated_at) if estimated_at else None,
        "carrier_handoff_at": str(carrier_at) if carrier_at else None,
        "delivery_variance_hours": delivery_variance,
        "seller_handoff_analysis": seller_handoff_analysis,
        "late_handoff_seller_ids": late_seller_ids,
    }


def determine_primary_issue(delivery_info: Dict, delivery: Dict, payment: Dict) -> str:
    """Walk the EC_POLICY_V2 table top to bottom; first match wins."""
    order_status = delivery_info.get("order_status", "")
    payment_total = payment.get("payment_total_brl") or 0.0
    reconciled = payment.get("reconciled")
    num_payments = len(payment.get("payment_ids", []))
    delivery_var = delivery["delivery_variance_hours"]
    late_sellers = delivery["late_handoff_seller_ids"]

    if order_status == "canceled" and payment_total > 0:
        return PRIMARY_CANCELED
    if order_status == "unavailable" and payment_total > 0:
        return PRIMARY_UNAVAILABLE
    if delivery_var is not None and delivery_var > 0 and len(late_sellers) > 0:
        return PRIMARY_LATE_SELLER
    if delivery_var is not None and delivery_var > 0 and len(late_sellers) == 0:
        return PRIMARY_LATE_LOGISTICS
    if num_payments >= 2 and reconciled:
        return PRIMARY_VALID_SPLIT
    return PRIMARY_UNSUPPORTED


def determine_resolution(
    delivery_info: Dict,
    delivery: Dict,
    payment: Dict,
    related_order_ids: List[str],
    raw_items: List[Dict],
) -> Dict[str, Any]:
    """Apply EC_POLICY_V2 priority order: primary/secondary issues,
    responsibility, refund and actions. Confidence is NOT produced here - it
    comes from src/agents/policy_agent.py's LLM cross-check against
    determine_primary_issue()."""
    payment_total = payment.get("payment_total_brl") or 0.0
    freight_total = payment.get("freight_total_brl") or 0.0
    num_payments = len(payment.get("payment_ids", []))
    late_sellers = delivery["late_handoff_seller_ids"]
    num_items = len(raw_items)
    unique_sellers = list(dict.fromkeys(str(i.get("seller_id", "")) for i in raw_items if i.get("seller_id")))
    unique_categories = list(dict.fromkeys(str(i.get("product_category_name", "")) for i in raw_items if i.get("product_category_name")))

    primary_issue = determine_primary_issue(delivery_info, delivery, payment)

    if primary_issue == PRIMARY_CANCELED:
        responsible_parties = [{"party_type": "platform", "party_id": PLATFORM_PARTY_ID}]
        refund_brl = _round2(payment_total)
        action = "issue_full_refund"
        cause_codes = [CAUSE_CANCELED]

    elif primary_issue == PRIMARY_UNAVAILABLE:
        responsible_parties = [{"party_type": "platform", "party_id": PLATFORM_PARTY_ID}]
        refund_brl = _round2(payment_total)
        action = "issue_full_refund"
        cause_codes = [CAUSE_UNAVAILABLE]

    elif primary_issue == PRIMARY_LATE_SELLER:
        responsible_parties = [{"party_type": "seller", "party_id": s} for s in late_sellers[:3]]
        refund_brl = _round2(freight_total)
        action = "refund_freight"
        cause_codes = [CAUSE_SELLER_HANDOFF]

    elif primary_issue == PRIMARY_LATE_LOGISTICS:
        responsible_parties = [{"party_type": "logistics_provider", "party_id": LOGISTICS_PARTY_ID}]
        refund_brl = _round2(freight_total)
        action = "refund_freight"
        cause_codes = [CAUSE_CARRIER_LATE]

    elif primary_issue == PRIMARY_VALID_SPLIT:
        responsible_parties = []
        refund_brl = 0.0
        action = "explain_valid_split_payment"
        cause_codes = [CAUSE_PAYMENTS_RECONCILED]

    else:
        responsible_parties = []
        refund_brl = 0.0
        action = "reject_late_refund"
        cause_codes = [CAUSE_WITHIN_ESTIMATE]

    secondary_issues = []
    if num_items >= 2:
        secondary_issues.append("multi_item_order")
    if len(unique_sellers) >= 2:
        secondary_issues.append("multi_seller_order")
    if num_payments >= 2:
        secondary_issues.append("split_payment")
    if len(related_order_ids) > 0:
        secondary_issues.append("repeat_customer")
    if len(unique_categories) >= 2:
        secondary_issues.append("multiple_categories")

    resolution_actions = [action]
    if primary_issue == PRIMARY_LATE_SELLER:
        resolution_actions.append("review_seller_handoff")
    elif primary_issue == PRIMARY_LATE_LOGISTICS:
        resolution_actions.append("review_carrier_delay")
    if action == "issue_full_refund":
        resolution_actions.append("verify_refund_completion")
    if len(unique_sellers) >= 2:
        resolution_actions.append("coordinate_multi_seller_case")
    if num_payments >= 2 and primary_issue != PRIMARY_VALID_SPLIT:
        resolution_actions.append("verify_payment_allocation")

    resolution_actions = resolution_actions[:5]

    ranked_causes = [{"cause_code": c, "rank": i + 1} for i, c in enumerate(cause_codes[:3])]

    case_status = "action_required" if action in ("issue_full_refund", "refund_freight") else "no_action"

    return {
        "primary_issue": primary_issue,
        "secondary_issues": secondary_issues,
        "case_status": case_status,
        "ranked_causes": ranked_causes,
        "responsible_parties": responsible_parties,
        "refund_brl": refund_brl,
        "resolution_actions": resolution_actions,
    }


def build_evidence_ids(order_id: str, order: Dict, payment: Dict, resolution: Dict) -> List[str]:
    """Only evidence IDs that can be constructed straight from the CSV rows."""
    evidences = [f"order:{order_id}"]
    for iid in order.get("item_ids", [])[:5]:
        evidences.append(f"item:{iid}")
    for pid in payment.get("payment_ids", [])[:5]:
        evidences.append(f"payment:{pid}")

    rps = resolution.get("responsible_parties", [])
    seller_in_rps = set(rp["party_id"] for rp in rps if rp.get("party_type") == "seller")
    for sid in seller_in_rps:
        evidences.append(f"seller:{sid}")

    for rc in resolution.get("ranked_causes", []):
        evidences.append(f"policy:{rc['cause_code']}")

    return evidences[:20]


def apply_policy(
    order_id: str,
    delivery_info: Dict,
    raw_items: List[Dict],
    raw_payments: List[Dict],
    related_order_ids: List[str],
) -> Dict[str, Any]:
    """Full deterministic assessment for one case, combining every step above.
    Used by the domain agents (each reads the slice it needs) and by
    audit_outputs.py to independently re-derive the expected output."""
    order = analyze_order_product(order_id, raw_items)
    payment = analyze_payment(order_id, raw_items, raw_payments)
    delivery = analyze_delivery(delivery_info, raw_items)
    resolution = determine_resolution(delivery_info, delivery, payment, related_order_ids, raw_items)
    evidence_ids = build_evidence_ids(order_id, order, payment, resolution)

    return {
        "order": order,
        "payment": payment,
        "delivery": delivery,
        "resolution": resolution,
        "evidence_ids": evidence_ids,
    }
