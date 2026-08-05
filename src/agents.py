import os
import json
import math
from datetime import datetime
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from groq import Groq

# ----------------- PYDANTIC SCHEMAS FOR OUTPUT -----------------

class ResponsibleParty(BaseModel):
    party_type: str
    party_id: str

class RankedCause(BaseModel):
    cause_code: str = ""
    rank: int = 0

class RootCauseAnalysis(BaseModel):
    ranked_causes: List[RankedCause] = Field(default_factory=list)
    responsible_parties: List[ResponsibleParty] = Field(default_factory=list)

class FinancialResolution(BaseModel):
    currency: str = "BRL"
    recommended_refund_brl: float = 0.0

class CaseAssessment(BaseModel):
    primary_issue: str = ""
    secondary_issues: List[str] = Field(default_factory=list)
    case_status: str = "no_action"
    confidence: float = 0.0

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

class FinalResolution(BaseModel):
    case_id: str
    case_assessment: CaseAssessment
    affected_entities: AffectedEntities
    customer_context: CustomerContext
    product_context: ProductContext
    delivery_analysis: DeliveryAnalysis
    payment_reconciliation: PaymentReconciliation
    root_cause_analysis: RootCauseAnalysis
    evidence_ids: List[str]
    financial_resolution: FinancialResolution
    resolution_actions: List[str]

# ----------------- AGENTS -----------------

class BaseAgent:
    def __init__(self, model="llama-3.1-8b-instant"):
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        self.model = model

    def query_llm(self, system_prompt: str, user_content: str, json_schema=None) -> Dict[str, Any]:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]
        
        try:
            chat_completion = self.client.chat.completions.create(
                messages=messages,
                model=self.model,
                response_format={"type": "json_object"} if json_schema is not None else None,
                temperature=0.0
            )
            content = chat_completion.choices[0].message.content
            if json_schema:
                return json.loads(content)
            return {"content": content}
        except Exception as e:
            print(f"Error querying LLM: {e}")
            return {}

class CustomerAgent(BaseAgent):
    def analyze(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        prompt = "You are the Customer Agent. Extract customer_unique_id and related_order_ids. Output strictly JSON with keys 'customer_unique_id' and 'related_order_ids'."
        return self.query_llm(prompt, json.dumps(raw_data), json_schema=True)

class OrderProductAgent(BaseAgent):
    def analyze(self, order_id: str, raw_items: List[Dict[str, Any]]) -> Dict[str, Any]:
        # Since we just need to aggregate lists, we can use LLM to summarize
        prompt = """You are the Order & Product Agent.
        Given the raw items, extract unique product_ids, category_names (english), seller_ids, and item_ids (format: order_id:order_item_id).
        Output strictly JSON with keys: 'product_ids', 'category_names', 'seller_ids', 'item_ids'."""
        
        user_msg = json.dumps({"order_id": order_id, "items": raw_items})
        return self.query_llm(prompt, user_msg, json_schema=True)

class PaymentAgent(BaseAgent):
    def analyze(self, order_id: str, raw_items: List[Dict], raw_payments: List[Dict]) -> Dict[str, Any]:
        # Calculate exactly in python to augment the LLM
        item_total = sum(i['price'] for i in raw_items if i['price'])
        freight_total = sum(i['freight_value'] for i in raw_items if i['freight_value'])
        expected = item_total + freight_total
        payment_total = sum(p['payment_value'] for p in raw_payments if p['payment_value'])
        diff = payment_total - expected
        reconciled = abs(diff) <= 0.10
        
        if not raw_items:
            expected = diff = reconciled = None

        payment_types = list(set(p['payment_type'] for p in raw_payments))
        payment_ids = [f"{order_id}:{p['payment_sequential']}" for p in raw_payments]

        prompt = f"""You are the Payment Agent. Based on the calculated data, return a structured JSON representing the payment reconciliation.
        Output keys: item_total_brl, freight_total_brl, expected_total_brl, payment_total_brl, difference_brl, reconciled, payment_types, payment_ids.
        Round floats to 2 decimals."""
        
        context = {
            "item_total": round(item_total, 2) if raw_items else None,
            "freight_total": round(freight_total, 2) if raw_items else None,
            "expected_total": round(expected, 2) if raw_items else None,
            "payment_total": round(payment_total, 2) if raw_items else None,
            "difference": round(diff, 2) if raw_items else None,
            "reconciled": reconciled,
            "payment_types": payment_types,
            "payment_ids": payment_ids
        }
        
        return self.query_llm(prompt, json.dumps(context), json_schema=True)

class DeliveryAgent(BaseAgent):
    def __init__(self):
        super().__init__()
        
    def _parse_date(self, d_str):
        if not d_str:
            return None
        return datetime.strptime(d_str, "%Y-%m-%d %H:%M:%S")

    def _diff_hours(self, d1, d2):
        if not d1 or not d2:
            return None
        return round((d1 - d2).total_seconds() / 3600.0, 2)

    def analyze(self, delivery_info: Dict, items: List[Dict]) -> Dict[str, Any]:
        # Tool: Exact math calculation
        delivered_at = self._parse_date(delivery_info.get('order_delivered_customer_date'))
        estimated_at = self._parse_date(delivery_info.get('order_estimated_delivery_date'))
        carrier_at = self._parse_date(delivery_info.get('order_delivered_carrier_date'))
        
        delivery_var = self._diff_hours(delivered_at, estimated_at)
        
        # Calculate seller handoff variance
        seller_analysis = []
        late_sellers = []
        for i in items:
            limit_at = self._parse_date(i['shipping_limit_date'])
            handoff_var = self._diff_hours(carrier_at, limit_at)
            is_late = handoff_var is not None and handoff_var > 0
            if is_late:
                late_sellers.append(i['seller_id'])
            seller_analysis.append({
                "seller_id": i['seller_id'],
                "shipping_limit_at": i['shipping_limit_date'],
                "handoff_variance_hours": handoff_var,
                "late_handoff": is_late
            })
            
        context = {
            "delivered_at": delivery_info.get('order_delivered_customer_date'),
            "estimated_delivery_at": delivery_info.get('order_estimated_delivery_date'),
            "carrier_handoff_at": delivery_info.get('order_delivered_carrier_date'),
            "delivery_variance_hours": delivery_var,
            "seller_handoff_analysis": seller_analysis,
            "late_handoff_seller_ids": list(set(late_sellers))
        }

        prompt = "You are the Delivery Agent. Structure the provided delivery analysis data into JSON. Output keys: delivered_at, estimated_delivery_at, carrier_handoff_at, delivery_variance_hours, seller_handoff_analysis, late_handoff_seller_ids."
        return self.query_llm(prompt, json.dumps(context), json_schema=True)

class PolicyAgent(BaseAgent):
    def determine_resolution(self, aggregated_evidence: Dict[str, Any]) -> Dict[str, Any]:
        prompt = """You are the Policy Agent for Brazilian E-commerce. 
        Apply EC_POLICY_V2 strictly based on the provided evidence.
        
        Rules:
        1. canceled_order_paid: status=canceled and payment > 0 -> platform refund payment, action: issue_full_refund
        2. unavailable_order_paid: status=unavailable and payment > 0 -> platform refund payment, action: issue_full_refund
        3. late_delivery_seller: delivered after estimate AND carrier received after shipping_limit -> seller refund freight, action: refund_freight
        4. late_delivery_logistics: delivered after estimate AND NO seller handoff late -> logistics_provider refund freight, action: refund_freight
        5. valid_split_payment: >=2 payments AND reconciled -> no responsible party, refund 0, action: explain_valid_split_payment
        6. unsupported_late_claim: not late AND reconciled -> no responsible party, refund 0, action: reject_late_refund
        
        Secondary issues (add in order if true):
        1. multi_item_order: >=2 items
        2. multi_seller_order: >=2 unique sellers
        3. split_payment: >=2 payments
        4. repeat_customer: related_orders > 0
        5. multiple_categories: >=2 unique categories
        
        If action_required, case_status = 'action_required', else 'no_action'.
        Confidence is a float [0, 1].
        
        Output strictly JSON with exactly these keys and types:
        - primary_issue (str)
        - secondary_issues (list of str)
        - case_status (str)
        - confidence (float)
        - root_cause_analysis (dict containing: 'ranked_causes' [list of dicts with 'cause_code'(str), 'rank'(int)] and 'responsible_parties' [list of dicts with 'party_type'(str), 'party_id'(str)])
        - financial_resolution (dict containing: 'currency'='BRL', 'recommended_refund_brl'(float))
        - resolution_actions (list of str)
        """
        return self.query_llm(prompt, json.dumps(aggregated_evidence), json_schema=True)

class VerifierAgent:
    def verify_and_format(self, case_id: str, policy_output: Dict, customer: Dict, order: Dict, payment: Dict, delivery: Dict) -> FinalResolution:
        # Build evidence IDs
        evidences = [f"order:{case_id}"]
        for item in order.get('item_ids', [])[:5]:
            evidences.append(f"item:{item}")
        for p in payment.get('payment_ids', [])[:5]:
            evidences.append(f"payment:{p}")
        for s in order.get('seller_ids', [])[:3]:
            evidences.append(f"seller:{s}")
            
        rca = policy_output.get('root_cause_analysis', {})
        ranked_causes = rca.get('ranked_causes', []) if isinstance(rca, dict) else []
        safe_rcs = []
        for rc in ranked_causes[:3]:
            if isinstance(rc, dict):
                cause_code = rc.get('cause_code', '')
                if cause_code: evidences.append(f"policy:{cause_code}")
                safe_rcs.append({"cause_code": cause_code, "rank": int(rc.get('rank', 0))})
            elif isinstance(rc, str):
                evidences.append(f"policy:{rc}")
                safe_rcs.append({"cause_code": rc, "rank": 0})
                
        safe_rps = []
        responsible_parties = rca.get('responsible_parties', []) if isinstance(rca, dict) else []
        for rp in responsible_parties[:3]:
            if isinstance(rp, dict):
                safe_rps.append({"party_type": str(rp.get('party_type', '')), "party_id": str(rp.get('party_id', ''))})
            elif isinstance(rp, str):
                safe_rps.append({"party_type": rp, "party_id": ""})
                
        financial = policy_output.get('financial_resolution', {})
        if not isinstance(financial, dict): financial = {}
                
        full_data = {
            "case_id": case_id,
            "case_assessment": {
                "primary_issue": str(policy_output.get('primary_issue', '')),
                "secondary_issues": policy_output.get('secondary_issues', []) if isinstance(policy_output.get('secondary_issues'), list) else [],
                "case_status": str(policy_output.get('case_status', 'no_action')),
                "confidence": float(policy_output.get('confidence', 0.9)) if isinstance(policy_output.get('confidence'), (int, float)) else 0.9
            },
            "affected_entities": {
                "order_ids": [case_id][:5],
                "item_ids": order.get('item_ids', [])[:5],
                "seller_ids": order.get('seller_ids', [])[:3],
                "payment_ids": payment.get('payment_ids', [])[:5]
            },
            "customer_context": {
                "customer_unique_id": str(customer.get('customer_unique_id', '')),
                "related_order_ids": customer.get('related_order_ids', [])[:5]
            },
            "product_context": {
                "product_ids": order.get('product_ids', [])[:5],
                "category_names": order.get('category_names', [])[:5]
            },
            "delivery_analysis": delivery,
            "payment_reconciliation": {
                "currency": "BRL",
                "item_total_brl": payment.get('item_total_brl'),
                "freight_total_brl": payment.get('freight_total_brl'),
                "expected_total_brl": payment.get('expected_total_brl'),
                "payment_total_brl": payment.get('payment_total_brl'),
                "difference_brl": payment.get('difference_brl'),
                "reconciled": payment.get('reconciled'),
                "payment_types": payment.get('payment_types', [])
            },
            "root_cause_analysis": {
                "ranked_causes": safe_rcs,
                "responsible_parties": safe_rps
            },
            "evidence_ids": evidences[:20],
            "financial_resolution": {
                "currency": "BRL",
                "recommended_refund_brl": float(financial.get('recommended_refund_brl', 0.0)) if isinstance(financial.get('recommended_refund_brl'), (int, float)) else 0.0
            },
            "resolution_actions": policy_output.get('resolution_actions', [])[:5] if isinstance(policy_output.get('resolution_actions'), list) else []
        }
        
        # Pydantic will validate
        return FinalResolution(**full_data)
