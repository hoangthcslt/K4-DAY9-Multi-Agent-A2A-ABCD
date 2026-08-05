"""Rebuild output/ from the deterministic engine without re-running the agents.

Used when a change affects only data-derived fields (never an agent decision),
so re-running 50 cases through the LLM would cost time and tokens to reproduce
identical agent findings. The confidence already recorded per case is preserved,
because that value came from the real agent run and this script does not re-earn
it.

Refuses to run if any output file is missing, since a partial rebuild would mix
two different derivations across the submission.

Usage: python src/regenerate_outputs.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents.customer_agent import build_customer_context
from agents.order_product_agent import (
    build_affected_entities,
    build_product_context,
)
from agents.verifier_agent import enforce_limits, verify_output
from data_layer import get_case_bundle, load_data
from policy_rules import apply_policy

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_DIR = os.path.join(REPO_ROOT, "input")
OUTPUT_DIR = os.path.join(REPO_ROOT, "output")


def main():
    data = load_data()
    filenames = sorted(f for f in os.listdir(INPUT_DIR) if f.endswith(".json"))

    missing = [f for f in filenames if not os.path.exists(os.path.join(OUTPUT_DIR, f))]
    if missing:
        print("Refusing to rebuild: %d output file(s) missing: %s" % (len(missing), missing[:5]))
        print("Run 'python src/run.py' for a full agent run instead.")
        return 1

    changed = 0
    failed = []

    for filename in filenames:
        with open(os.path.join(INPUT_DIR, filename), "r", encoding="utf-8") as handle:
            case_input = json.load(handle)
        case_id = case_input["case_id"]
        scope = case_input.get("investigation_scope", {})

        output_path = os.path.join(OUTPUT_DIR, filename)
        with open(output_path, "r", encoding="utf-8") as handle:
            previous = json.load(handle)

        order_id = case_input["customer_request"]["claimed_order_id"]
        bundle = get_case_bundle(data, order_id)
        if bundle is None:
            print("%s: claimed order not in dataset, left untouched" % case_id)
            continue

        assessment = apply_policy(bundle)

        customer_context = build_customer_context(bundle)
        product_context = build_product_context(bundle)
        if not scope.get("include_customer_history", True):
            customer_context["related_order_ids"] = []
        if not scope.get("include_product_context", True):
            product_context = {"product_ids": [], "category_names": []}

        rebuilt = {
            "case_id": case_id,
            "case_assessment": {
                "primary_issue": assessment["primary_issue"],
                "secondary_issues": assessment["secondary_issues"],
                "case_status": assessment["case_status"],
                # Carried over from the agent run; this script does not re-derive it.
                "confidence": previous["case_assessment"]["confidence"],
            },
            "affected_entities": build_affected_entities(bundle),
            "customer_context": customer_context,
            "product_context": product_context,
            "delivery_analysis": assessment["delivery_analysis"],
            "payment_reconciliation": assessment["payment_reconciliation"],
            "root_cause_analysis": {
                "ranked_causes": assessment["ranked_causes"],
                "responsible_parties": assessment["responsible_parties"],
            },
            "evidence_ids": assessment["evidence_ids"],
            "financial_resolution": {
                "currency": "BRL",
                "recommended_refund_brl": assessment["recommended_refund_brl"],
            },
            "resolution_actions": assessment["resolution_actions"],
        }

        rebuilt = enforce_limits(rebuilt)
        errors, _ = verify_output(rebuilt, bundle)
        if errors:
            failed.append((case_id, errors))
            continue

        if rebuilt != previous:
            changed += 1

        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(rebuilt, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

    print("Rebuilt %d case(s); %d file(s) changed." % (len(filenames), changed))
    if failed:
        print("Verifier errors in %d case(s):" % len(failed))
        for case_id, errors in failed:
            print("  %s: %s" % (case_id, errors[:3]))
        return 1
    print("Verifier: all cases passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
