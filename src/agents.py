"""
Multi-Agent E-commerce Dispute Resolution System
All business logic (payment, delivery, policy) is computed deterministically in Python.
LLM (Groq llama-3.1-8b-instant) is used only for the Customer Agent's context summary.
"""

import os
import json
from datetime import datetime
from typing import List, Optional, Dict, Any

from groq import Groq
from pydantic import BaseModel, Field

# ----------------- PYDANTIC OUTPUT SCHEMA -----------------

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


# ----------------- UTILITY -----------------

def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s or str(s) == 'nan' or str(s).lower() == 'none':
        return None
    try:
        return datetime.strptime(str(s).strip(), "%Y-%m-%d %H:%M:%S")
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


# ----------------- CUSTOMER AGENT (uses LLM for context) -----------------

class CustomerAgent:
    """Uses the DataLoader result directly - no LLM needed, data is already structured."""
    def analyze(self, raw_customer: Dict[str, Any]) -> CustomerContext:
        uid = raw_customer.get("customer_unique_id") or ""
        related = raw_customer.get("related_order_ids", []) or []
        return CustomerContext(
            customer_unique_id=str(uid),
            related_order_ids=[str(r) for r in related][:5]
        )


# ----------------- ORDER & PRODUCT AGENT (pure Python) -----------------

class OrderProductAgent:
    def analyze(self, order_id: str, raw_items: List[Dict]) -> Dict[str, Any]:
        if not raw_items:
            return {
                "product_ids": [], "category_names": [],
                "seller_ids": [], "item_ids": []
            }

        # Sort by order_item_id for stable ordering
        sorted_items = sorted(raw_items, key=lambda x: int(x.get("order_item_id", 0) or 0))

        seen_products, seen_categories, seen_sellers = [], [], []
        item_ids = []

        for item in sorted_items:
            pid = str(item.get("product_id") or "")
            cat = str(item.get("product_category_name_english") or "")
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
            "item_ids": item_ids[:5]
        }


# ----------------- PAYMENT AGENT (pure Python math) -----------------

class PaymentAgent:
    def analyze(self, order_id: str, raw_items: List[Dict], raw_payments: List[Dict]) -> Dict[str, Any]:
        # Sort by payment_sequential for stable ordering
        sorted_payments = sorted(raw_payments, key=lambda x: int(x.get("payment_sequential", 0) or 0))
        payment_ids = [
            f"{order_id}:{int(p['payment_sequential'])}"
            for p in sorted_payments
            if p.get("payment_sequential") is not None
        ][:5]
        payment_types = list(dict.fromkeys(
            p["payment_type"] for p in sorted_payments if p.get("payment_type")
        ))
        raw_payments = sorted_payments  # use sorted from here on
        payment_total = _round2(sum(p["payment_value"] for p in raw_payments if p.get("payment_value") is not None))

        if not raw_items:
            return {
                "item_total_brl": None, "freight_total_brl": None,
                "expected_total_brl": None, "payment_total_brl": payment_total,
                "difference_brl": None, "reconciled": None,
                "payment_types": payment_types, "payment_ids": payment_ids
            }

        item_total = _round2(sum(i["price"] for i in raw_items if i.get("price") is not None))
        freight_total = _round2(sum(i["freight_value"] for i in raw_items if i.get("freight_value") is not None))
        expected = _round2(item_total + freight_total)
        difference = _round2(payment_total - expected)
        reconciled = abs(difference) <= 0.10 if difference is not None else None

        return {
            "item_total_brl": item_total,
            "freight_total_brl": freight_total,
            "expected_total_brl": expected,
            "payment_total_brl": payment_total,
            "difference_brl": difference,
            "reconciled": reconciled,
            "payment_types": payment_types,
            "payment_ids": payment_ids
        }


# ----------------- DELIVERY AGENT (pure Python math) -----------------

class DeliveryAgent:
    def analyze(self, delivery_info: Dict, raw_items: List[Dict]) -> DeliveryAnalysis:
        delivered_at = delivery_info.get("order_delivered_customer_date")
        estimated_at = delivery_info.get("order_estimated_delivery_date")
        carrier_at = delivery_info.get("order_delivered_carrier_date")

        d_delivered = _parse_dt(delivered_at)
        d_estimated = _parse_dt(estimated_at)
        d_carrier = _parse_dt(carrier_at)

        delivery_variance = _diff_hours(d_delivered, d_estimated)

        # Per-seller: use earliest shipping_limit_date for each unique seller
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

        # One entry per UNIQUE seller (not per item)
        for sid, effective_limit in seller_limits.items():
            handoff_var = _diff_hours(d_carrier, effective_limit)
            is_late = handoff_var is not None and handoff_var > 0
            seller_handoff_analysis.append(SellerHandoff(
                seller_id=sid,
                shipping_limit_at=seller_limit_str.get(sid),
                handoff_variance_hours=handoff_var,
                late_handoff=is_late
            ))
            if is_late:
                late_seller_ids.append(sid)

        return DeliveryAnalysis(
            delivered_at=str(delivered_at) if delivered_at else None,
            estimated_delivery_at=str(estimated_at) if estimated_at else None,
            carrier_handoff_at=str(carrier_at) if carrier_at else None,
            delivery_variance_hours=delivery_variance,
            seller_handoff_analysis=seller_handoff_analysis,
            late_handoff_seller_ids=late_seller_ids
        )


# ----------------- POLICY AGENT (pure Python rule engine per EC_POLICY_V2) -----------------

class PolicyAgent:
    """
    Applies EC_POLICY_V2 deterministically.
    Uses LLM (Groq) only to generate a confidence score + short reasoning, but
    ALL structured fields (primary_issue, refund amounts, actions, cause codes) are
    computed here in Python from verified data.
    """
    def __init__(self):
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        self.model = "llama-3.1-8b-instant"

    def determine_resolution(
        self,
        delivery_info: Dict,
        delivery: DeliveryAnalysis,
        payment: Dict,
        order: Dict,
        customer: CustomerContext,
        raw_items: List[Dict]
    ) -> Dict[str, Any]:

        order_status = delivery_info.get("order_status", "")
        payment_total = payment.get("payment_total_brl") or 0.0
        freight_total = payment.get("freight_total_brl") or 0.0
        reconciled = payment.get("reconciled")
        num_payments = len(payment.get("payment_ids", []))
        delivery_var = delivery.delivery_variance_hours  # negative = early, positive = late
        late_sellers = delivery.late_handoff_seller_ids
        num_items = len(raw_items)
        unique_sellers = list(dict.fromkeys(str(i.get("seller_id","")) for i in raw_items if i.get("seller_id")))
        unique_categories = list(dict.fromkeys(str(i.get("product_category_name_english","")) for i in raw_items if i.get("product_category_name_english")))

        # ---- Apply EC_POLICY_V2 priority order ----
        primary_issue = None
        responsible_parties = []
        refund_brl = 0.0
        action = None
        cause_codes = []

        if order_status == "canceled" and payment_total > 0:
            primary_issue = "canceled_order_paid"
            responsible_parties = [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}]
            refund_brl = _round2(payment_total)
            action = "issue_full_refund"
            cause_codes = ["ORDER_CANCELED_AFTER_PAYMENT"]

        elif order_status == "unavailable" and payment_total > 0:
            primary_issue = "unavailable_order_paid"
            responsible_parties = [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}]
            refund_brl = _round2(payment_total)
            action = "issue_full_refund"
            cause_codes = ["ORDER_UNAVAILABLE_AFTER_PAYMENT"]

        elif delivery_var is not None and delivery_var > 0 and len(late_sellers) > 0:
            primary_issue = "late_delivery_seller"
            responsible_parties = [{"party_type": "seller", "party_id": s} for s in late_sellers[:3]]
            refund_brl = _round2(freight_total)
            action = "refund_freight"
            cause_codes = ["SELLER_HANDOFF_AFTER_LIMIT", "CARRIER_DELIVERED_AFTER_ESTIMATE"]

        elif delivery_var is not None and delivery_var > 0 and len(late_sellers) == 0:
            primary_issue = "late_delivery_logistics"
            responsible_parties = [{"party_type": "logistics_provider", "party_id": "LOGISTICS_PROVIDER"}]
            refund_brl = _round2(freight_total)
            action = "refund_freight"
            cause_codes = ["CARRIER_DELIVERED_AFTER_ESTIMATE"]

        elif num_payments >= 2 and reconciled:
            primary_issue = "valid_split_payment"
            responsible_parties = []
            refund_brl = 0.0
            action = "explain_valid_split_payment"
            cause_codes = ["MULTIPLE_PAYMENTS_RECONCILED"]

        else:
            # unsupported_late_claim (default)
            primary_issue = "unsupported_late_claim"
            responsible_parties = []
            refund_brl = 0.0
            action = "reject_late_refund"
            cause_codes = ["DELIVERY_WITHIN_ESTIMATE"]

        # ---- Secondary issues in fixed order ----
        secondary_issues = []
        if num_items >= 2:
            secondary_issues.append("multi_item_order")
        if len(unique_sellers) >= 2:
            secondary_issues.append("multi_seller_order")
        if num_payments >= 2:
            secondary_issues.append("split_payment")
        if len(customer.related_order_ids) > 0:
            secondary_issues.append("repeat_customer")
        if len(unique_categories) >= 2:
            secondary_issues.append("multiple_categories")

        # ---- Resolution actions in fixed order (per README section 4) ----
        resolution_actions = [action]
        if primary_issue == "late_delivery_seller":
            resolution_actions.append("review_seller_handoff")
        elif primary_issue == "late_delivery_logistics":
            resolution_actions.append("review_carrier_delay")
        # verify_refund_completion: only for full platform refunds (canceled/unavailable)
        if action == "issue_full_refund":
            resolution_actions.append("verify_refund_completion")
        if len(unique_sellers) >= 2 and primary_issue not in ("valid_split_payment",):
            resolution_actions.append("coordinate_multi_seller_case")
        if num_payments >= 2 and primary_issue not in ("valid_split_payment",):
            resolution_actions.append("verify_payment_allocation")

        resolution_actions = resolution_actions[:5]

        # ---- Ranked causes ----
        ranked_causes = [{"cause_code": c, "rank": i + 1} for i, c in enumerate(cause_codes[:3])]

        # ---- LLM for confidence only ----
        confidence = self._get_confidence(primary_issue, delivery_var, late_sellers, reconciled, order_status)

        case_status = "action_required" if action in ("issue_full_refund", "refund_freight") else "no_action"

        return {
            "primary_issue": primary_issue,
            "secondary_issues": secondary_issues,
            "case_status": case_status,
            "confidence": confidence,
            "ranked_causes": ranked_causes,
            "responsible_parties": responsible_parties,
            "refund_brl": refund_brl,
            "resolution_actions": resolution_actions
        }

    def _get_confidence(self, primary_issue, delivery_var, late_sellers, reconciled, order_status) -> float:
        """Use LLM to estimate confidence score based on evidence clarity."""
        prompt = """You are a quality assurance agent. Given the policy decision summary, return a JSON object with a single key 'confidence' (float between 0.7 and 1.0) representing how confident you are in this determination. Output only valid JSON."""
        user_msg = json.dumps({
            "primary_issue": primary_issue,
            "delivery_variance_hours": delivery_var,
            "late_seller_count": len(late_sellers) if late_sellers else 0,
            "payment_reconciled": reconciled,
            "order_status": order_status
        })
        try:
            resp = self.client.chat.completions.create(
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_msg}
                ],
                model=self.model,
                response_format={"type": "json_object"},
                temperature=0.0
            )
            data = json.loads(resp.choices[0].message.content)
            c = float(data.get("confidence", 0.9))
            return round(max(0.0, min(1.0, c)), 2)
        except Exception:
            return 0.9


# ----------------- VERIFIER AGENT -----------------

class VerifierAgent:
    def build_final(
        self,
        case_id: str,
        order_id: str,
        customer: CustomerContext,
        order: Dict,
        payment: Dict,
        delivery: DeliveryAnalysis,
        policy: Dict
    ) -> FinalResolution:

        # Evidence IDs
        evidences = [f"order:{order_id}"]
        for iid in order.get("item_ids", [])[:5]:
            evidences.append(f"item:{iid}")
        for pid in payment.get("payment_ids", [])[:5]:
            evidences.append(f"payment:{pid}")

        # Only responsible sellers in evidence
        rps = policy.get("responsible_parties", [])
        seller_in_rps = set(rp["party_id"] for rp in rps if rp.get("party_type") == "seller")
        for sid in seller_in_rps:
            evidences.append(f"seller:{sid}")

        for rc in policy.get("ranked_causes", []):
            evidences.append(f"policy:{rc['cause_code']}")

        evidences = evidences[:20]

        # Deduplicate seller_ids in affected_entities but preserve order
        all_seller_ids = order.get("seller_ids", [])
        unique_seller_ids = list(dict.fromkeys(all_seller_ids))[:3]

        return FinalResolution(
            case_id=case_id,
            case_assessment=CaseAssessment(
                primary_issue=policy["primary_issue"],
                secondary_issues=policy["secondary_issues"],
                case_status=policy["case_status"],
                confidence=policy["confidence"]
            ),
            affected_entities=AffectedEntities(
                order_ids=[order_id][:5],
                item_ids=order.get("item_ids", [])[:5],
                seller_ids=unique_seller_ids,
                payment_ids=payment.get("payment_ids", [])[:5]
            ),
            customer_context=customer,
            product_context=ProductContext(
                product_ids=order.get("product_ids", [])[:5],
                category_names=order.get("category_names", [])[:5]
            ),
            delivery_analysis=delivery,
            payment_reconciliation=PaymentReconciliation(
                currency="BRL",
                item_total_brl=payment.get("item_total_brl"),
                freight_total_brl=payment.get("freight_total_brl"),
                expected_total_brl=payment.get("expected_total_brl"),
                payment_total_brl=payment.get("payment_total_brl"),
                difference_brl=payment.get("difference_brl"),
                reconciled=payment.get("reconciled"),
                payment_types=payment.get("payment_types", [])
            ),
            root_cause_analysis=RootCauseAnalysis(
                ranked_causes=[RankedCause(**rc) for rc in policy.get("ranked_causes", [])],
                responsible_parties=[ResponsibleParty(**rp) for rp in rps[:3]]
            ),
            evidence_ids=evidences,
            financial_resolution=FinancialResolution(
                currency="BRL",
                recommended_refund_brl=policy.get("refund_brl", 0.0)
            ),
            resolution_actions=policy.get("resolution_actions", [])[:5]
        )
