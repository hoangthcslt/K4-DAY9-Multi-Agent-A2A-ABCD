"""Independent audit of output/ against the README spec.

Written separately from verifier_agent.py on purpose: if the verifier has a bug,
a check that reuses the verifier's own code would not reveal it. This script
re-derives the expectations straight from the CSVs.

Usage: python src/audit_outputs.py
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_layer import get_case_bundle, load_data
from policy_rules import apply_policy

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_DIR = os.path.join(REPO_ROOT, "input")
OUTPUT_DIR = os.path.join(REPO_ROOT, "output")

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


def audit_case(case_id, output, bundle):
    problems = []

    for field in REQUIRED_TOP_LEVEL:
        if field not in output:
            problems.append("missing top-level field: %s" % field)
    if problems:
        return problems

    if output["case_id"] != case_id:
        problems.append("case_id mismatch: %r" % output["case_id"])

    # Re-derive the whole assessment from the CSVs and compare.
    expected = apply_policy(bundle)
    assessment = output["case_assessment"]

    if assessment["primary_issue"] != expected["primary_issue"]:
        problems.append(
            "primary_issue %r != recomputed %r"
            % (assessment["primary_issue"], expected["primary_issue"])
        )

    if assessment["secondary_issues"] != expected["secondary_issues"]:
        problems.append(
            "secondary_issues %r != recomputed %r"
            % (assessment["secondary_issues"], expected["secondary_issues"])
        )

    # Secondary issues must follow the fixed policy order.
    indices = [SECONDARY_ORDER.index(i) for i in assessment["secondary_issues"]
               if i in SECONDARY_ORDER]
    if indices != sorted(indices):
        problems.append("secondary_issues out of policy order")

    if output["delivery_analysis"] != expected["delivery_analysis"]:
        problems.append("delivery_analysis differs from recomputed")

    if output["payment_reconciliation"] != expected["payment_reconciliation"]:
        problems.append("payment_reconciliation differs from recomputed")

    refund = output["financial_resolution"]["recommended_refund_brl"]
    if abs(refund - expected["recommended_refund_brl"]) > 1e-9:
        problems.append(
            "refund %r != recomputed %r" % (refund, expected["recommended_refund_brl"])
        )

    if output["resolution_actions"] != expected["resolution_actions"]:
        problems.append(
            "actions %r != recomputed %r"
            % (output["resolution_actions"], expected["resolution_actions"])
        )

    # Supplementary actions must follow the fixed order after the primary action.
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

    # Status must agree with the refund.
    expected_status = "action_required" if refund > 0 else "no_action"
    if assessment["case_status"] != expected_status:
        problems.append(
            "case_status %r but refund %r" % (assessment["case_status"], refund)
        )

    confidence = assessment["confidence"]
    if not isinstance(confidence, (int, float)) or not 0.0 <= confidence <= 1.0:
        problems.append("confidence out of range: %r" % confidence)

    # affected_entities holds the claimed order only.
    if output["affected_entities"]["order_ids"] != [bundle["order_id"]]:
        problems.append("affected_entities.order_ids is not exactly the claimed order")

    if bundle["order_id"] in output["customer_context"]["related_order_ids"]:
        problems.append("claimed order leaked into related_order_ids")

    # Array caps.
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

    # Timestamps keep the CSV format or are null.
    delivery = output["delivery_analysis"]
    for field in ("delivered_at", "estimated_delivery_at", "carrier_handoff_at"):
        value = delivery[field]
        if value is not None and not TIMESTAMP_PATTERN.match(value):
            problems.append("%s bad timestamp: %r" % (field, value))

    # No item rows means null money fields and empty arrays.
    if not bundle["items"]:
        payment = output["payment_reconciliation"]
        for field in ("expected_total_brl", "difference_brl", "reconciled"):
            if payment[field] is not None:
                problems.append("%s must be null when there are no item rows" % field)
        if delivery["seller_handoff_analysis"]:
            problems.append("seller_handoff_analysis must be empty with no item rows")
        if output["affected_entities"]["item_ids"]:
            problems.append("item_ids must be empty with no item rows")
        if output["affected_entities"]["seller_ids"]:
            problems.append("seller_ids must be empty with no item rows")
        if output["product_context"]["product_ids"]:
            problems.append("product_ids must be empty with no item rows")
        if output["product_context"]["category_names"]:
            problems.append("category_names must be empty with no item rows")

    # Evidence must be reconstructible from the loaded rows.
    order_id = bundle["order_id"]
    constructible = {"order:%s" % order_id}
    for item in bundle["items"]:
        constructible.add("item:%s:%s" % (order_id, item["order_item_id"]))
    for payment in bundle["payments"]:
        constructible.add("payment:%s:%s" % (order_id, payment["payment_sequential"]))
    for seller_id in bundle["seller_ids"]:
        constructible.add("seller:%s" % seller_id)
    for cause in output["root_cause_analysis"]["ranked_causes"]:
        constructible.add("policy:%s" % cause["cause_code"])

    for evidence_id in output["evidence_ids"]:
        if evidence_id not in constructible:
            problems.append("evidence not backed by data: %r" % evidence_id)

    return problems


def main():
    data = load_data()
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
        bundle = get_case_bundle(data, order_id)
        if bundle is None:
            print("%s: claimed order not in dataset (%s)" % (case_id, order_id))
            continue

        problems = audit_case(case_id, output, bundle)
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
