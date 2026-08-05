import os
import glob
import json
import time
from datetime import datetime
from dotenv import load_dotenv
from src.data_loader import DataLoader
from src.agents import CustomerAgent, OrderProductAgent, PaymentAgent, DeliveryAgent, PolicyAgent, VerifierAgent

def main():
    load_dotenv()
    
    # Initialize DataLoader
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    if not os.path.exists(data_dir):
        print(f"Data directory not found at {data_dir}. Please ensure CSVs are present.")
        return
        
    print("Loading Olist Dataset...")
    loader = DataLoader(data_dir)
    
    # Initialize Agents
    customer_agent = CustomerAgent()
    order_agent = OrderProductAgent()
    payment_agent = PaymentAgent()
    delivery_agent = DeliveryAgent()
    policy_agent = PolicyAgent()
    verifier_agent = VerifierAgent()
    
    input_dir = os.path.join(os.path.dirname(__file__), "input")
    output_dir = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(output_dir, exist_ok=True)
    
    trace_file = os.path.join(os.path.dirname(__file__), "logging", "trace.jsonl")
    
    # Clear old trace file if exists
    if os.path.exists(trace_file):
        os.remove(trace_file)

    input_files = sorted(glob.glob(os.path.join(input_dir, "EC_*.json")))
    print(f"Found {len(input_files)} cases to process.")
    
    for input_file in input_files:
        filename = os.path.basename(input_file)
        print(f"\nProcessing {filename}...")
        
        with open(input_file, 'r', encoding='utf-8') as f:
            case_data = json.load(f)
            
        case_id = case_data.get('case_id')
        claimed_order_id = case_data.get('customer_request', {}).get('claimed_order_id')
        
        if not claimed_order_id:
            print(f"Missing claimed_order_id in {filename}")
            continue
            
        # 1. Data Router extracts specific order data
        raw_customer = loader.get_customer_info(claimed_order_id)
        raw_items = loader.get_order_items(claimed_order_id)
        raw_payments = loader.get_payments(claimed_order_id)
        raw_delivery = loader.get_delivery_info(claimed_order_id)
        
        # 2. Domain Agents analyze
        print("  - Running Customer Agent...")
        customer_context = customer_agent.analyze(raw_customer)
        time.sleep(1) # Simple rate limiting for free Groq API
        
        print("  - Running Order & Product Agent...")
        order_context = order_agent.analyze(claimed_order_id, raw_items)
        time.sleep(1)
        
        print("  - Running Payment Agent...")
        payment_context = payment_agent.analyze(claimed_order_id, raw_items, raw_payments)
        time.sleep(1)
        
        print("  - Running Delivery Agent...")
        delivery_context = delivery_agent.analyze(raw_delivery, raw_items)
        time.sleep(1)
        
        # 3. Aggregate Evidence
        aggregated_evidence = {
            "customer_analysis": customer_context,
            "order_analysis": order_context,
            "payment_analysis": payment_context,
            "delivery_analysis": delivery_context
        }
        
        # 4. Policy Agent decides
        print("  - Running Policy Agent...")
        policy_decision = policy_agent.determine_resolution(aggregated_evidence)
        time.sleep(1)
        
        # 5. Verifier Agent finalizes JSON schema
        print("  - Verifying and Formatting Output...")
        final_resolution = verifier_agent.verify_and_format(
            case_id=case_id,
            policy_output=policy_decision,
            customer=customer_context,
            order=order_context,
            payment=payment_context,
            delivery=delivery_context
        )
        
        # Save Output JSON
        output_path = os.path.join(output_dir, filename)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(final_resolution.model_dump_json(indent=2))
            
        # Save Trace
        trace_record = {
            "case_id": case_id,
            "timestamp": datetime.utcnow().isoformat(),
            "inputs": case_data,
            "raw_data_router": {
                "customer": raw_customer,
                "items": raw_items,
                "payments": raw_payments,
                "delivery": raw_delivery
            },
            "agent_handoffs": aggregated_evidence,
            "policy_decision": policy_decision,
            "final_output": final_resolution.model_dump()
        }
        with open(trace_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(trace_record) + "\n")
            
        print(f"  -> Successfully generated {output_path}")

if __name__ == "__main__":
    main()
