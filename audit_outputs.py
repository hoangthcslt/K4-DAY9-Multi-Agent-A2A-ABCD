"""Independent audit of output/ against the README spec.

Written separately from src/agents/verifier_agent.py on purpose: if the
verifier has a bug, a check that reuses the verifier's own code would not
reveal it. This script re-derives the expected values straight from the CSVs
via src.policy_rules, independently of the coordinator/agent pipeline.

Usage: python audit_outputs.py
"""

import json
import os
import re
import sys

from src.data_loader import DataLoader
from src.policy_rules import apply_policy

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(REPO_ROOT, "input")
OUTPUT_DIR = os.path.join(REPO_ROOT, "output")
DATA_DIR = os.path.join(REPO_ROOT, "data")

REQUIRED_TOP_LEVEL = [
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
]

SECONDARY_ORDER = [
    "multi_item_order",
    "multi_seller_order",
    "split_payment",
    "repeat_customer",
    "multiple_categories",
]

ACTION_ORDER = [
    "review_seller_handoff",
    "review_carrier_delay",
    "verify_refund_completion",
    "coordinate_multi_seller_case",
    "verify_payment_allocation",
]

TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


def audit_case(case_id, output, order_id, raw_customer, raw_items, raw_payments, delivery_info):
    problems = []

    for field in REQUIRED_TOP_LEVEL:
        if field not in output:
            problems.append("missing top-level field: %s" % field)
    if problems:
        return problems

    if output["case_id"] != case_id:
        problems.append("case_id mismatch: %r" % output["case_id"])

    related_order_ids = raw_customer.get("related_order_ids", []) or []
    expected = apply_policy(order_id, delivery_info, raw_items, raw_payments, related_order_ids)
    resolution = expected["resolution"]
    delivery = expected["delivery"]
    payment = expected["payment"]

    assessment = output["case_assessment"]

    if assessment["primary_issue"] != resolution["primary_issue"]:
        problems.append(
            "primary_issue %r != recomputed %r" % (assessment["primary_issue"], resolution["primary_issue"])
        )

    if assessment["secondary_issues"] != resolution["secondary_issues"]:
        problems.append(
            "secondary_issues %r != recomputed %r"
            % (assessment["secondary_issues"], resolution["secondary_issues"])
        )

    indices = [SECONDARY_ORDER.index(i) for i in assessment["secondary_issues"] if i in SECONDARY_ORDER]
    if indices != sorted(indices):
        problems.append("secondary_issues out of policy order")

    delivery_out = output["delivery_analysis"]
    for field in ("delivered_at", "estimated_delivery_at", "carrier_handoff_at", "delivery_variance_hours"):
        if delivery_out.get(field) != delivery.get(field):
            problems.append("delivery_analysis.%s %r != recomputed %r" % (field, delivery_out.get(field), delivery.get(field)))
    if delivery_out.get("late_handoff_seller_ids") != delivery.get("late_handoff_seller_ids"):
        problems.append("late_handoff_seller_ids differs from recomputed")
    if len(delivery_out.get("seller_handoff_analysis", [])) != len(delivery.get("seller_handoff_analysis", [])):
        problems.append("seller_handoff_analysis length differs from recomputed")

    payment_out = output["payment_reconciliation"]
    for field in ("item_total_brl", "freight_total_brl", "expected_total_brl",
                  "payment_total_brl", "difference_brl", "reconciled"):
        if payment_out.get(field) != payment.get(field):
            problems.append("payment_reconciliation.%s %r != recomputed %r" % (field, payment_out.get(field), payment.get(field)))

    refund = output["financial_resolution"]["recommended_refund_brl"]
    if abs(refund - resolution["refund_brl"]) > 1e-9:
        problems.append("refund %r != recomputed %r" % (refund, resolution["refund_brl"]))

    if output["resolution_actions"] != resolution["resolution_actions"]:
        problems.append(
            "actions %r != recomputed %r" % (output["resolution_actions"], resolution["resolution_actions"])
        )

    tail = [a for a in output["resolution_actions"] if a in ACTION_ORDER]
    tail_indices = [ACTION_ORDER.index(a) for a in tail]
    if tail_indices != sorted(tail_indices):
        problems.append("supplementary actions out of policy order")

    if (
        assessment["primary_issue"] == "valid_split_payment"
        and "verify_payment_allocation" in output["resolution_actions"]
    ):
        problems.append("verify_payment_allocation must be suppressed for valid_split_payment")

    if output["evidence_ids"] != expected["evidence_ids"]:
        problems.append("evidence_ids differ from recomputed")

    expected_status = "action_required" if resolution["refund_brl"] > 0 else "no_action"
    if assessment["case_status"] != expected_status:
        problems.append("case_status %r but refund %r" % (assessment["case_status"], resolution["refund_brl"]))

    confidence = assessment["confidence"]
    if not isinstance(confidence, (int, float)) or not 0.0 <= confidence <= 1.0:
        problems.append("confidence out of range: %r" % confidence)

    if output["affected_entities"]["order_ids"] != [order_id]:
        problems.append("affected_entities.order_ids is not exactly the claimed order")

    if order_id in output["customer_context"]["related_order_ids"]:
        problems.append("claimed order leaked into related_order_ids")

    caps = [
        ("affected_entities.order_ids", output["affected_entities"]["order_ids"], 5),
        ("affected_entities.item_ids", output["affected_entities"]["item_ids"], 5),
        ("affected_entities.seller_ids", output["affected_entities"]["seller_ids"], 3),
        ("affected_entities.payment_ids", output["affected_entities"]["payment_ids"], 5),
        ("related_order_ids", output["customer_context"]["related_order_ids"], 5),
        ("product_ids", output["product_context"]["product_ids"], 5),
        ("category_names", output["product_context"]["category_names"], 5),
        ("ranked_causes", output["root_cause_analysis"]["ranked_causes"], 3),
        ("responsible_parties", output["root_cause_analysis"]["responsible_parties"], 3),
        ("evidence_ids", output["evidence_ids"], 20),
        ("resolution_actions", output["resolution_actions"], 5),
    ]
    for name, values, cap in caps:
        if len(values) > cap:
            problems.append("%s exceeds cap %d (%d)" % (name, cap, len(values)))

    for field in ("delivered_at", "estimated_delivery_at", "carrier_handoff_at"):
        value = delivery_out[field]
        if value is not None and not TIMESTAMP_PATTERN.match(value):
            problems.append("%s bad timestamp: %r" % (field, value))

    if not raw_items:
        for field in ("expected_total_brl", "difference_brl", "reconciled"):
            if payment_out[field] is not None:
                problems.append("%s must be null when there are no item rows" % field)
        if delivery_out["seller_handoff_analysis"]:
            problems.append("seller_handoff_analysis must be empty with no item rows")
        if output["affected_entities"]["item_ids"]:
            problems.append("item_ids must be empty with no item rows")
        if output["affected_entities"]["seller_ids"]:
            problems.append("seller_ids must be empty with no item rows")
        if output["product_context"]["product_ids"]:
            problems.append("product_ids must be empty with no item rows")
        if output["product_context"]["category_names"]:
            problems.append("category_names must be empty with no item rows")

    constructible = set(expected["evidence_ids"])
    for evidence_id in output["evidence_ids"]:
        if evidence_id not in constructible:
            problems.append("evidence not backed by data: %r" % evidence_id)

    return problems


def main():
    loader = DataLoader(DATA_DIR)
    input_files = sorted(f for f in os.listdir(INPUT_DIR) if f.endswith(".json"))

    total_problems = 0
    issue_counts = {}
    status_counts = {}
    missing_outputs = []

    for filename in input_files:
        with open(os.path.join(INPUT_DIR, filename), "r", encoding="utf-8") as handle:
            case_input = json.load(handle)
        case_id = case_input["case_id"]

        output_path = os.path.join(OUTPUT_DIR, filename)
        if not os.path.exists(output_path):
            missing_outputs.append(filename)
            continue

        with open(output_path, "r", encoding="utf-8") as handle:
            output = json.load(handle)

        order_id = case_input["customer_request"]["claimed_order_id"]
        raw_customer = loader.get_customer_info(order_id)
        raw_items = loader.get_order_items(order_id)
        raw_payments = loader.get_payments(order_id)
        delivery_info = loader.get_delivery_info(order_id)

        problems = audit_case(case_id, output, order_id, raw_customer, raw_items, raw_payments, delivery_info)
        issue = output["case_assessment"]["primary_issue"]
        issue_counts[issue] = issue_counts.get(issue, 0) + 1
        status = output["case_assessment"]["case_status"]
        status_counts[status] = status_counts.get(status, 0) + 1

        if problems:
            total_problems += len(problems)
            print("%s: %d problem(s)" % (case_id, len(problems)))
            for problem in problems:
                print("    - %s" % problem)

    print("\n=== AUDIT SUMMARY ===")
    print("Input cases:   %d" % len(input_files))
    print("Outputs found: %d" % (len(input_files) - len(missing_outputs)))
    if missing_outputs:
        print("MISSING OUTPUTS: %s" % missing_outputs)
    print("Problems:      %d" % total_problems)
    print("\nPrimary issue distribution:")
    for issue, count in sorted(issue_counts.items(), key=lambda kv: -kv[1]):
        print("  %-26s %d" % (issue, count))
    print("\nCase status distribution:")
    for status, count in sorted(status_counts.items()):
        print("  %-16s %d" % (status, count))

    if total_problems == 0 and not missing_outputs:
        print("\nAll outputs conform to the spec.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
