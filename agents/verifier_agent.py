"""
Verifier Agent — Validates output schema, evidence IDs, limits.
Purely deterministic rule-based validation.
"""


class VerifierAgent:
    AGENT_NAME = "VerifierAgent"

    VALID_PRIMARY = {
        "canceled_order_paid", "unavailable_order_paid",
        "late_delivery_seller", "late_delivery_logistics",
        "valid_split_payment", "unsupported_late_claim",
    }
    VALID_SECONDARY = {
        "multi_item_order", "multi_seller_order", "split_payment",
        "repeat_customer", "multiple_categories",
    }
    VALID_STATUS = {"action_required", "no_action"}
    VALID_ROOT_CAUSES = {
        "SELLER_HANDOFF_AFTER_LIMIT", "CARRIER_DELIVERED_AFTER_ESTIMATE",
        "ORDER_CANCELED_AFTER_PAYMENT", "ORDER_UNAVAILABLE_AFTER_PAYMENT",
        "MULTIPLE_PAYMENTS_RECONCILED", "DELIVERY_WITHIN_ESTIMATE",
    }
    LIMITS = {
        "order_ids": 5, "item_ids": 5, "seller_ids": 3,
        "payment_ids": 5, "related_order_ids": 5,
        "product_ids": 5, "category_names": 5,
        "ranked_causes": 3, "responsible_parties": 3,
        "evidence_ids": 20, "resolution_actions": 5,
    }

    def validate(self, output: dict) -> tuple[bool, list[str]]:
        """Validate output JSON. Returns (is_valid, list_of_errors)."""
        print(f"  [{self.AGENT_NAME}] Validating output for {output.get('case_id', '?')}...")
        errors = []

        # Required top-level keys
        required = [
            "case_id", "case_assessment", "affected_entities",
            "customer_context", "product_context", "delivery_analysis",
            "payment_reconciliation", "root_cause_analysis",
            "evidence_ids", "financial_resolution", "resolution_actions",
        ]
        for key in required:
            if key not in output:
                errors.append(f"Missing required key: {key}")

        if errors:
            return False, errors

        # Case assessment
        ca = output["case_assessment"]
        if ca.get("primary_issue") not in self.VALID_PRIMARY:
            errors.append(f"Invalid primary_issue: {ca.get('primary_issue')}")
        for si in ca.get("secondary_issues", []):
            if si not in self.VALID_SECONDARY:
                errors.append(f"Invalid secondary_issue: {si}")
        if ca.get("case_status") not in self.VALID_STATUS:
            errors.append(f"Invalid case_status: {ca.get('case_status')}")
        conf = ca.get("confidence", -1)
        if not (0 <= conf <= 1):
            errors.append(f"Confidence out of range: {conf}")

        # Case status consistency
        refund = output.get("financial_resolution", {}).get("recommended_refund_brl", 0)
        if refund > 0 and ca.get("case_status") != "action_required":
            errors.append("Refund > 0 but case_status != action_required")
        if refund == 0 and ca.get("case_status") != "no_action":
            errors.append("Refund = 0 but case_status != no_action")

        # Array limits
        ae = output.get("affected_entities", {})
        for key, limit in self.LIMITS.items():
            arr = None
            if key in ae:
                arr = ae[key]
            elif key == "related_order_ids":
                arr = output.get("customer_context", {}).get(key, [])
            elif key == "product_ids":
                arr = output.get("product_context", {}).get(key, [])
            elif key == "category_names":
                arr = output.get("product_context", {}).get(key, [])
            elif key == "ranked_causes":
                arr = output.get("root_cause_analysis", {}).get(key, [])
            elif key == "responsible_parties":
                arr = output.get("root_cause_analysis", {}).get(key, [])
            elif key in output:
                arr = output[key]

            if arr is not None and isinstance(arr, list) and len(arr) > limit:
                errors.append(f"Array {key} exceeds limit {limit}: got {len(arr)}")

        # Evidence ID format
        for eid in output.get("evidence_ids", []):
            if not any(eid.startswith(p) for p in ["order:", "item:", "payment:", "seller:", "policy:"]):
                errors.append(f"Invalid evidence ID format: {eid}")

        # Root cause codes
        for rc in output.get("root_cause_analysis", {}).get("ranked_causes", []):
            if rc.get("cause_code") not in self.VALID_ROOT_CAUSES:
                errors.append(f"Invalid root cause code: {rc.get('cause_code')}")

        # verify_payment_allocation check
        if ca.get("primary_issue") == "valid_split_payment":
            if "verify_payment_allocation" in output.get("resolution_actions", []):
                errors.append("verify_payment_allocation should not appear when primary is valid_split_payment")

        return len(errors) == 0, errors

    def fix_limits(self, output: dict) -> dict:
        """Auto-fix array limits by truncating."""
        ae = output.get("affected_entities", {})
        ae["order_ids"] = ae.get("order_ids", [])[:5]
        ae["item_ids"] = ae.get("item_ids", [])[:5]
        ae["seller_ids"] = ae.get("seller_ids", [])[:3]
        ae["payment_ids"] = ae.get("payment_ids", [])[:5]

        cc = output.get("customer_context", {})
        cc["related_order_ids"] = cc.get("related_order_ids", [])[:5]

        pc = output.get("product_context", {})
        pc["product_ids"] = pc.get("product_ids", [])[:5]
        pc["category_names"] = pc.get("category_names", [])[:5]

        rca = output.get("root_cause_analysis", {})
        rca["ranked_causes"] = rca.get("ranked_causes", [])[:3]
        rca["responsible_parties"] = rca.get("responsible_parties", [])[:3]

        output["evidence_ids"] = output.get("evidence_ids", [])[:20]
        output["resolution_actions"] = output.get("resolution_actions", [])[:5]

        return output
