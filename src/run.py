"""Entrypoint: run every case in input/ through the agent team into output/.

Usage:
  python src/run.py                 # all cases
  python src/run.py --limit 3       # first 3 cases, for a smoke test
  python src/run.py --case EC_007   # one specific case
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents.coordinator import Coordinator
from data_layer import get_case_bundle, load_data
from llm_client import MODEL_NAME
from trace_logger import TraceLogger

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_DIR = os.path.join(REPO_ROOT, "input")
OUTPUT_DIR = os.path.join(REPO_ROOT, "output")


def load_case_inputs(limit=None, only_case=None):
    filenames = sorted(f for f in os.listdir(INPUT_DIR) if f.endswith(".json"))
    if only_case:
        filenames = [f for f in filenames if f.startswith(only_case)]
    if limit:
        filenames = filenames[:limit]

    cases = []
    for filename in filenames:
        with open(os.path.join(INPUT_DIR, filename), "r", encoding="utf-8") as handle:
            cases.append((filename, json.load(handle)))
    return cases


def write_output(filename, output):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(output, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--case", type=str, default=None)
    parser.add_argument(
        "--trace",
        type=str,
        default=os.path.join(REPO_ROOT, "trace.jsonl"),
        help="trace.jsonl destination; truncated at start of every run",
    )
    parser.add_argument(
        "--no-truncate-trace",
        action="store_true",
        help="append to the existing trace instead of truncating; use when "
        "re-running a subset so the other cases keep their trace records",
    )
    args = parser.parse_args()

    print("Model: %s" % MODEL_NAME)
    print("Loading Olist CSVs...")
    data = load_data()

    cases = load_case_inputs(limit=args.limit, only_case=args.case)
    print("Cases to process: %d" % len(cases))

    tracer = TraceLogger(path=args.trace, truncate=not args.no_truncate_trace)
    if args.no_truncate_trace:
        tracer.drop_cases([case_input["case_id"] for _, case_input in cases])
    coordinator = Coordinator(tracer)

    failed_verification = []
    missing_orders = []
    started = time.time()

    for index, (filename, case_input) in enumerate(cases, start=1):
        case_id = case_input["case_id"]
        order_id = case_input.get("customer_request", {}).get("claimed_order_id")
        bundle = get_case_bundle(data, order_id)

        if bundle is None:
            # An unknown order cannot be investigated; record it rather than
            # inventing an assessment for it.
            missing_orders.append(case_id)
            tracer.log_case(case_id, "order_not_found", {"claimed_order_id": order_id})
            print("[%d/%d] %s ORDER NOT FOUND: %s" % (index, len(cases), case_id, order_id))
            continue

        output, errors = coordinator.process(case_input, bundle)
        write_output(filename, output)

        if errors:
            failed_verification.append((case_id, errors))

        status = "ok" if not errors else "VERIFIER: %d error(s)" % len(errors)
        print(
            "[%d/%d] %s -> %s / %s (%s)"
            % (
                index,
                len(cases),
                case_id,
                output["case_assessment"]["primary_issue"],
                output["case_assessment"]["case_status"],
                status,
            )
        )

    elapsed = time.time() - started
    print("\nDone in %.1fs. Outputs in %s" % (elapsed, OUTPUT_DIR))
    print("Trace: %s" % args.trace)

    if missing_orders:
        print("Orders not found (%d): %s" % (len(missing_orders), missing_orders))
    if failed_verification:
        print("Verifier errors in %d case(s):" % len(failed_verification))
        for case_id, errors in failed_verification:
            print("  %s: %s" % (case_id, errors[:3]))
    else:
        print("Verifier: all cases passed.")


if __name__ == "__main__":
    main()
