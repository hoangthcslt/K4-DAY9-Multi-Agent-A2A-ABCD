import json
import glob
import pandas as pd
from datetime import datetime

# Load CSV data
orders = pd.read_csv('data/olist_orders_dataset.csv')
items = pd.read_csv('data/olist_order_items_dataset.csv')
payments = pd.read_csv('data/olist_order_payments_dataset.csv')
customers = pd.read_csv('data/olist_customers_dataset.csv')

# Load all input/output pairs and verify
inputs = sorted(glob.glob('input/EC_*.json'))
outputs = sorted(glob.glob('output/EC_*.json'))

print("=== CROSS-CHECKING OUTPUT vs RAW DATA ===\n")

wrong_cases = []

for inf, outf in zip(inputs, outputs):
    with open(inf, encoding='utf-8') as fp:
        inp = json.load(fp)
    with open(outf, encoding='utf-8') as fp:
        out = json.load(fp)
    
    cid = inp['case_id']
    order_id = inp['customer_request']['claimed_order_id']
    
    # Get order
    order_row = orders[orders.order_id == order_id]
    if order_row.empty:
        wrong_cases.append(f'{cid}: order_id {order_id} NOT FOUND in CSV!')
        continue
    
    order_status = order_row.order_status.values[0]
    
    # Get items
    item_rows = items[items.order_id == order_id]
    pay_rows = payments[payments.order_id == order_id]
    
    # Compute expected values
    payment_total = round(pay_rows.payment_value.sum(), 2) if not pay_rows.empty else 0
    item_total = round(item_rows.price.sum(), 2) if not item_rows.empty else None
    freight_total = round(item_rows.freight_value.sum(), 2) if not item_rows.empty else None
    expected_total = round(item_total + freight_total, 2) if item_total is not None else None
    difference = round(payment_total - expected_total, 2) if expected_total is not None else None
    reconciled = abs(difference) <= 0.10 if difference is not None else None

    # Compute delivery
    delivered = order_row.order_delivered_customer_date.values[0]
    estimated = order_row.order_estimated_delivery_date.values[0]
    carrier = order_row.order_delivered_carrier_date.values[0]
    
    late_delivery = False
    if delivered and estimated and str(delivered) != 'NaT' and str(estimated) != 'NaT':
        d_dt = pd.to_datetime(delivered)
        e_dt = pd.to_datetime(estimated)
        late_delivery = d_dt > e_dt
        delivery_variance = round((d_dt - e_dt).total_seconds() / 3600, 2)
    else:
        delivery_variance = None

    # Compute seller handoff
    late_sellers = []
    if not item_rows.empty and carrier and str(carrier) != 'NaT':
        c_dt = pd.to_datetime(carrier)
        for _, row in item_rows.iterrows():
            sl_dt = pd.to_datetime(row.shipping_limit_date)
            hv = round((c_dt - sl_dt).total_seconds() / 3600, 2)
            if hv > 0:
                late_sellers.append(row.seller_id)

    # Determine expected primary_issue
    if order_status == 'canceled' and payment_total > 0:
        expected_pi = 'canceled_order_paid'
        expected_refund = payment_total
    elif order_status == 'unavailable' and payment_total > 0:
        expected_pi = 'unavailable_order_paid'
        expected_refund = payment_total
    elif late_delivery and late_sellers:
        expected_pi = 'late_delivery_seller'
        expected_refund = freight_total
    elif late_delivery and not late_sellers:
        expected_pi = 'late_delivery_logistics'
        expected_refund = freight_total
    elif not late_delivery and len(pay_rows) >= 2:
        expected_pi = 'valid_split_payment'
        expected_refund = 0
    else:
        expected_pi = 'unsupported_late_claim'
        expected_refund = 0

    # Check output
    actual_pi = out['case_assessment']['primary_issue']
    actual_refund = out['financial_resolution']['recommended_refund_brl']
    actual_pr = out['payment_reconciliation']
    
    errors = []
    if actual_pi != expected_pi:
        errors.append(f'primary_issue: got={actual_pi}, expected={expected_pi}')
    
    if expected_refund is not None and actual_refund != expected_refund:
        if abs(float(actual_refund) - float(expected_refund)) > 0.01:
            errors.append(f'refund: got={actual_refund}, expected={expected_refund}')
    
    if actual_pr.get('payment_total_brl') != payment_total:
        errors.append(f'payment_total_brl: got={actual_pr.get("payment_total_brl")}, expected={payment_total}')
    
    if item_total is not None and actual_pr.get('item_total_brl') != item_total:
        errors.append(f'item_total_brl: got={actual_pr.get("item_total_brl")}, expected={item_total}')

    if errors:
        wrong_cases.append(f'{cid} [order={order_id[:8]}...] status={order_status}:')
        for e in errors:
            wrong_cases.append(f'   -> {e}')

print(f"Cases with data mismatches: {len([x for x in wrong_cases if not x.startswith(' ')])}")
print()
for w in wrong_cases:
    print(w)
