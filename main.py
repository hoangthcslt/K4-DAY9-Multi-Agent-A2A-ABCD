import os
import glob
import json

from src.data_loader import DataLoader
from src.coordinator import Coordinator
from src.trace_logger import TraceLogger


def main():
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    if not os.path.exists(data_dir):
        print(f"Data directory not found at {data_dir}")
        return

    print("Loading Olist Dataset...")
    loader = DataLoader(data_dir)

    input_dir = os.path.join(os.path.dirname(__file__), "input")
    output_dir = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(output_dir, exist_ok=True)

    tracer = TraceLogger()
    coordinator = Coordinator(tracer)

    input_files = sorted(glob.glob(os.path.join(input_dir, "EC_*.json")))
    print(f"Found {len(input_files)} cases to process.\n")

    failed_cases = []
    verifier_errors = []

    for input_file in input_files:
        filename = os.path.basename(input_file)
        print(f"Processing {filename}...")

        with open(input_file, "r", encoding="utf-8") as f:
            case_data = json.load(f)

        case_id = case_data.get("case_id")
        claimed_order_id = case_data.get("customer_request", {}).get("claimed_order_id")

        if not claimed_order_id:
            print(f"  [SKIP] Missing claimed_order_id in {filename}")
            failed_cases.append((case_id or filename, "missing claimed_order_id"))
            continue

        try:
            raw_customer = loader.get_customer_info(claimed_order_id)
            raw_items = loader.get_order_items(claimed_order_id)
            raw_payments = loader.get_payments(claimed_order_id)
            delivery_info = loader.get_delivery_info(claimed_order_id)

            output, errors = coordinator.process(
                case_id, claimed_order_id, raw_customer, raw_items, raw_payments, delivery_info
            )

            output_path = os.path.join(output_dir, filename)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)

            if errors:
                verifier_errors.append((case_id, errors))

            print(f"  -> Done: {output_path}\n")
        except Exception as exc:
            # One bad case must not take down the other 49 - record it and move on.
            print(f"  [ERROR] {case_id or filename} failed: {exc}\n")
            failed_cases.append((case_id or filename, str(exc)))
            tracer.log_case(case_id or filename, "case_failed", {"error": str(exc)})

    print(f"Done. Outputs in {output_dir}")
    print(f"Trace: {tracer.path}")

    if failed_cases:
        print(f"\nFailed cases ({len(failed_cases)}):")
        for case_id, err in failed_cases:
            print(f"  {case_id}: {err}")
    if verifier_errors:
        print(f"\nVerifier errors in {len(verifier_errors)} case(s):")
        for case_id, errors in verifier_errors:
            print(f"  {case_id}: {errors[:3]}")
    if not failed_cases and not verifier_errors:
        print("\nAll cases processed and verified successfully.")


if __name__ == "__main__":
    main()
