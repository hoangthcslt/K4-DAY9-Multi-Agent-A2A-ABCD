import os
import glob
import json
import time
from datetime import datetime

from dotenv import load_dotenv
from src.data_loader import DataLoader
from src.agents import (
    CustomerAgent, OrderProductAgent, PaymentAgent,
    DeliveryAgent, PolicyAgent, VerifierAgent
)

def main():
    load_dotenv()

    data_dir = os.path.join(os.path.dirname(__file__), "data")
    if not os.path.exists(data_dir):
        print(f"Data directory not found at {data_dir}")
        return

    print("Loading Olist Dataset...")
    loader = DataLoader(data_dir)

    customer_agent   = CustomerAgent()
    order_agent      = OrderProductAgent()
    payment_agent    = PaymentAgent()
    delivery_agent   = DeliveryAgent()
    policy_agent     = PolicyAgent()
    verifier_agent   = VerifierAgent()

    input_dir  = os.path.join(os.path.dirname(__file__), "input")
    output_dir = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(output_dir, exist_ok=True)

    trace_file = os.path.join(os.path.dirname(__file__), "logging", "trace.jsonl")
    if os.path.exists(trace_file):
        os.remove(trace_file)

    input_files = sorted(glob.glob(os.path.join(input_dir, "EC_*.json")))
    print(f"Found {len(input_files)} cases to process.\n")

    for input_file in input_files:
        filename  = os.path.basename(input_file)
        print(f"Processing {filename}...")

        with open(input_file, 'r', encoding='utf-8') as f:
            case_data = json.load(f)

        case_id         = case_data.get("case_id")
        claimed_order_id = case_data.get("customer_request", {}).get("claimed_order_id")

        if not claimed_order_id:
            print(f"  [SKIP] Missing claimed_order_id in {filename}")
            continue

        # 1. Data Router
        raw_customer = loader.get_customer_info(claimed_order_id)
        raw_items    = loader.get_order_items(claimed_order_id)
        raw_payments = loader.get_payments(claimed_order_id)
        delivery_info = loader.get_delivery_info(claimed_order_id)

        # 2. Domain Agents (all deterministic except confidence LLM call)
        print("  - Customer Agent...")
        customer = customer_agent.analyze(raw_customer)

        print("  - Order & Product Agent...")
        order = order_agent.analyze(claimed_order_id, raw_items)

        print("  - Payment Agent...")
        payment = payment_agent.analyze(claimed_order_id, raw_items, raw_payments)

        print("  - Delivery Agent...")
        delivery = delivery_agent.analyze(delivery_info, raw_items)

        # 3. Policy Agent
        print("  - Policy Agent...")
        policy = policy_agent.determine_resolution(
            delivery_info=delivery_info,
            delivery=delivery,
            payment=payment,
            order=order,
            customer=customer,
            raw_items=raw_items
        )
        time.sleep(0.5)  # light rate-limit only for the confidence LLM call

        # 4. Verifier Agent
        print("  - Verifying & Formatting...")
        final = verifier_agent.build_final(
            case_id=case_id,
            order_id=claimed_order_id,
            customer=customer,
            order=order,
            payment=payment,
            delivery=delivery,
            policy=policy
        )

        # Write output JSON
        output_path = os.path.join(output_dir, filename)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(final.model_dump_json(indent=2))

        # Write trace
        trace = {
            "case_id": case_id,
            "timestamp": datetime.now().isoformat(),
            "inputs": case_data,
            "raw_data": {
                "customer": raw_customer,
                "items": raw_items,
                "payments": raw_payments,
                "delivery": delivery_info
            },
            "agent_outputs": {
                "customer": customer.model_dump(),
                "order": order,
                "payment": payment,
                "delivery": delivery.model_dump(),
                "policy": policy
            },
            "final_output": final.model_dump()
        }
        with open(trace_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(trace) + "\n")

        print(f"  -> Done: {output_path}\n")

if __name__ == "__main__":
    main()
