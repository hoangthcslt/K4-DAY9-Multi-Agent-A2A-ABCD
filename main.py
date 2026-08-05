"""
Main Runner — Processes all 50 cases and generates output, trace, and metadata.
"""

import json
import os
import time
from datetime import datetime

from agents.data_access import DataAccessLayer
from agents.llm_client import LLMClient, MODEL_NAME, MODEL_PARAMS, FRAMEWORK
from agents.coordinator_agent import CoordinatorAgent

# Paths
BASE_DIR = os.path.dirname(__file__)
INPUT_DIR = os.path.join(BASE_DIR, "input")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
LOGGING_DIR = os.path.join(BASE_DIR, "logging")
TRACE_FILE = os.path.join(LOGGING_DIR, "trace.jsonl")
METADATA_FILE = os.path.join(LOGGING_DIR, "metadata.json")


def main():
    print("=" * 60)
    print("Multi-Agent E-commerce Dispute Resolution System")
    print(f"Model: {MODEL_NAME} ({MODEL_PARAMS} params)")
    print("=" * 60)

    # Initialize shared components
    dal = DataAccessLayer()
    llm = LLMClient()
    coordinator = CoordinatorAgent(dal, llm)

    # Ensure output directory exists
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(LOGGING_DIR, exist_ok=True)

    # Collect input files
    input_files = sorted([
        f for f in os.listdir(INPUT_DIR)
        if f.startswith("EC_") and f.endswith(".json")
    ])

    print(f"\nFound {len(input_files)} input cases.")

    # Process each case
    all_traces = []
    start_total = time.time()

    for i, filename in enumerate(input_files):
        filepath = os.path.join(INPUT_DIR, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            case_input = json.load(f)

        try:
            output, trace = coordinator.process_case(case_input)

            # Write output
            out_path = os.path.join(OUTPUT_DIR, filename)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(output, f, indent=2, ensure_ascii=False)

            all_traces.append(trace)
            print(f"  [OK] [{i+1}/{len(input_files)}] {filename} -> output written")

        except Exception as e:
            print(f"  [FAIL] [{i+1}/{len(input_files)}] {filename} FAILED: {e}")
            all_traces.append({
                "case_id": case_input.get("case_id", filename),
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            })

    total_time = round(time.time() - start_total, 2)

    # Write trace.jsonl (overwrite, not append — per spec)
    with open(TRACE_FILE, "w", encoding="utf-8") as f:
        for trace in all_traces:
            f.write(json.dumps(trace, ensure_ascii=False) + "\n")

    # Write metadata.json
    llm_stats = llm.get_stats()
    metadata = {
        "model": MODEL_NAME,
        "parameter_size": MODEL_PARAMS,
        "framework": FRAMEWORK,
        "runtime": {
            "total_duration_s": total_time,
            "cases_processed": len(input_files),
            "avg_case_duration_s": round(total_time / max(len(input_files), 1), 2),
        },
        "llm_stats": llm_stats,
        "timestamp": datetime.now().isoformat(),
    }
    with open(METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    # Summary
    print(f"\n{'='*60}")
    print(f"COMPLETED: {len(input_files)} cases in {total_time}s")
    print(f"LLM calls: {llm_stats['total_calls']}, tokens: {llm_stats['total_tokens']}")
    print(f"Output: {OUTPUT_DIR}")
    print(f"Trace: {TRACE_FILE}")
    print(f"Metadata: {METADATA_FILE}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
