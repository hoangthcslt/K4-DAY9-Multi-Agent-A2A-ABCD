"""
Kiểm tra kỹ các hard gate conditions theo đúng README:
- Priority rule: canceled > unavailable > late_seller > late_logistics > valid_split > unsupported
- valid_split: phải có >= 2 payment rows VÀ payment khớp
- unsupported: KHÔNG muộn VÀ payment khớp  
- Kiểm tra handoff_variance_hours: phải dùng EARLIEST shipping_limit_date của từng seller
"""
import json
import glob
import pandas as pd

orders = pd.read_csv('data/olist_orders_dataset.csv')
items = pd.read_csv('data/olist_order_items_dataset.csv')
payments = pd.read_csv('data/olist_order_payments_dataset.csv')
customers = pd.read_csv('data/olist_customers_dataset.csv')

inputs = sorted(glob.glob('input/EC_*.json'))
outputs = sorted(glob.glob('output/EC_*.json'))

issues = []

for inf, outf in zip(inputs, outputs):
    with open(inf, encoding='utf-8') as fp:
        inp = json.load(fp)
    with open(outf, encoding='utf-8') as fp:
        out = json.load(fp)

    cid = inp['case_id']
    order_id = inp['customer_request']['claimed_order_id']

    order_row = orders[orders.order_id == order_id]
    if order_row.empty:
        issues.append(f'{cid}: order not found')
        continue

    order_status = order_row.order_status.values[0]
    item_rows = items[items.order_id == order_id]
    pay_rows = payments[payments.order_id == order_id]

    payment_total = round(pay_rows.payment_value.sum(), 2) if not pay_rows.empty else 0
    item_total = round(item_rows.price.sum(), 2) if not item_rows.empty else None
    freight_total = round(item_rows.freight_value.sum(), 2) if not item_rows.empty else None
    expected_total = round(item_total + freight_total, 2) if item_total is not None else None
    difference = round(payment_total - expected_total, 2) if expected_total is not None else None
    reconciled = abs(difference) <= 0.10 if difference is not None else None

    delivered = str(order_row.order_delivered_customer_date.values[0])
    estimated = str(order_row.order_estimated_delivery_date.values[0])
    carrier = str(order_row.order_delivered_carrier_date.values[0])

    late_delivery = False
    if delivered != 'NaT' and estimated != 'NaT':
        d_dt = pd.to_datetime(delivered)
        e_dt = pd.to_datetime(estimated)
        late_delivery = d_dt > e_dt

    # Seller handoff: so sánh carrier nhận hàng vs shipping_limit của MỖI seller (earliest per seller)
    late_sellers = set()
    seller_analysis = {}
    if not item_rows.empty and carrier != 'NaT':
        c_dt = pd.to_datetime(carrier)
        # Group by seller, get earliest shipping_limit_date per seller
        seller_limits = item_rows.groupby('seller_id')['shipping_limit_date'].min()
        for seller_id, sl in seller_limits.items():
            sl_dt = pd.to_datetime(sl)
            hv = round((c_dt - sl_dt).total_seconds() / 3600, 2)
            seller_analysis[seller_id] = {'hv': hv, 'late': hv > 0, 'sl': sl}
            if hv > 0:
                late_sellers.add(seller_id)

    # Determine primary_issue by priority
    if order_status == 'canceled' and payment_total > 0:
        expected_pi = 'canceled_order_paid'
    elif order_status == 'unavailable' and payment_total > 0:
        expected_pi = 'unavailable_order_paid'
    elif late_delivery and late_sellers:
        expected_pi = 'late_delivery_seller'
    elif late_delivery and not late_sellers:
        expected_pi = 'late_delivery_logistics'
    elif len(pay_rows) >= 2 and reconciled:
        expected_pi = 'valid_split_payment'
    else:
        expected_pi = 'unsupported_late_claim'

    actual_pi = out['case_assessment']['primary_issue']

    if actual_pi != expected_pi:
        issues.append(f'{cid}: primary_issue WRONG -> actual={actual_pi}, expected={expected_pi}')
        issues.append(f'       status={order_status}, late_delivery={late_delivery}, late_sellers={late_sellers}')
        issues.append(f'       pay_rows={len(pay_rows)}, reconciled={reconciled}, pay_total={payment_total}')

    # Check seller_handoff_analysis in output
    out_da = out.get('delivery_analysis', {})
    out_sha = out_da.get('seller_handoff_analysis', [])
    
    for sha_item in out_sha:
        sid = sha_item.get('seller_id')
        out_hv = sha_item.get('handoff_variance_hours')
        out_late = sha_item.get('late_handoff')
        if sid in seller_analysis:
            exp = seller_analysis[sid]
            if out_hv is not None and abs(out_hv - exp['hv']) > 0.1:
                issues.append(f'{cid}: seller {sid[:8]}... handoff_variance WRONG: got={out_hv}, expected={exp["hv"]}')
            if out_late != exp['late']:
                issues.append(f'{cid}: seller {sid[:8]}... late_handoff WRONG: got={out_late}, expected={exp["late"]}')

    # Check late_handoff_seller_ids
    out_late_ids = set(out_da.get('late_handoff_seller_ids', []))
    if out_late_ids != late_sellers:
        issues.append(f'{cid}: late_handoff_seller_ids WRONG: got={out_late_ids}, expected={late_sellers}')

print(f"Total issues: {len(issues)}")
if issues:
    for i in issues:
        print(i)
else:
    print("All primary_issues and seller handoffs are CORRECT!")
