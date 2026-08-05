import json
import glob

files = sorted(glob.glob('output/EC_*.json'))
issues_found = []

VALID_PRIMARY = {
    'canceled_order_paid', 'unavailable_order_paid', 'late_delivery_seller',
    'late_delivery_logistics', 'valid_split_payment', 'unsupported_late_claim'
}
VALID_SECONDARY = ['multi_item_order', 'multi_seller_order', 'split_payment', 'repeat_customer', 'multiple_categories']
VALID_CAUSES = {
    'SELLER_HANDOFF_AFTER_LIMIT', 'CARRIER_DELIVERED_AFTER_ESTIMATE',
    'ORDER_CANCELED_AFTER_PAYMENT', 'ORDER_UNAVAILABLE_AFTER_PAYMENT',
    'MULTIPLE_PAYMENTS_RECONCILED', 'DELIVERY_WITHIN_ESTIMATE'
}
VALID_STATUS = {'action_required', 'no_action'}

for f in files:
    with open(f) as fp:
        d = json.load(fp)
    cid = d.get('case_id', '?')
    fname_id = f.replace('output/', '').replace('output\\', '').replace('.json', '')

    # 1. case_id matches filename
    if d.get('case_id') != fname_id:
        issues_found.append(f'{cid}: case_id mismatch vs filename {fname_id}')

    ca = d.get('case_assessment', {})
    pi = ca.get('primary_issue')
    cs = ca.get('case_status')
    conf = ca.get('confidence')
    fr = d.get('financial_resolution', {})
    refund = fr.get('recommended_refund_brl')
    pr = d.get('payment_reconciliation', {})
    rc = d.get('root_cause_analysis', {})

    # 2. Primary issue valid?
    if pi not in VALID_PRIMARY:
        issues_found.append(f'{cid}: INVALID primary_issue: {pi}')

    # 3. case_status valid?
    if cs not in VALID_STATUS:
        issues_found.append(f'{cid}: INVALID case_status: {cs}')

    # 4. confidence in [0,1]
    if not isinstance(conf, (int, float)) or not (0 <= conf <= 1):
        issues_found.append(f'{cid}: confidence invalid: {conf}')

    # 5. canceled/unavailable must be action_required
    if pi in ('canceled_order_paid', 'unavailable_order_paid') and cs != 'action_required':
        issues_found.append(f'{cid}: {pi} should be action_required, got {cs}')

    # 6. no_action should have refund=0, action_required should have refund>0
    if cs == 'no_action' and refund is not None and refund != 0:
        issues_found.append(f'{cid}: no_action but recommended_refund_brl={refund}')
    if cs == 'action_required' and (refund is None or refund == 0):
        issues_found.append(f'{cid}: action_required but recommended_refund_brl={refund}')

    # 7. Root cause codes valid
    for cause in rc.get('ranked_causes', []):
        code = cause.get('cause_code', '')
        if code not in VALID_CAUSES:
            issues_found.append(f'{cid}: invalid cause_code: {code}')

    # 8. Array limits
    ae = d.get('affected_entities', {})
    cc = d.get('customer_context', {})
    pc = d.get('product_context', {})
    checks = [
        (ae.get('order_ids', []), 5, 'order_ids'),
        (ae.get('item_ids', []), 5, 'item_ids'),
        (ae.get('seller_ids', []), 3, 'seller_ids'),
        (ae.get('payment_ids', []), 5, 'payment_ids'),
        (cc.get('related_order_ids', []), 5, 'related_order_ids'),
        (pc.get('product_ids', []), 5, 'product_ids'),
        (pc.get('category_names', []), 5, 'category_names'),
        (d.get('evidence_ids', []), 20, 'evidence_ids'),
        (d.get('resolution_actions', []), 5, 'resolution_actions'),
        (rc.get('ranked_causes', []), 3, 'ranked_causes'),
        (rc.get('responsible_parties', []), 3, 'responsible_parties'),
    ]
    for arr, limit, name in checks:
        if len(arr) > limit:
            issues_found.append(f'{cid}: too many {name}: {len(arr)} > {limit}')

    # 9. valid_split_payment should NOT have verify_payment_allocation
    if pi == 'valid_split_payment':
        actions = d.get('resolution_actions', [])
        if 'verify_payment_allocation' in actions:
            issues_found.append(f'{cid}: valid_split_payment should NOT have verify_payment_allocation')

    # 10. late_delivery: refund = freight_total_brl
    if pi in ('late_delivery_seller', 'late_delivery_logistics'):
        freight = pr.get('freight_total_brl')
        if freight is not None and refund is not None and abs(refund - freight) > 0.01:
            issues_found.append(f'{cid}: {pi} refund={refund} but freight_total={freight} (mismatch)')

    # 11. canceled/unavailable: refund = payment_total_brl
    if pi in ('canceled_order_paid', 'unavailable_order_paid'):
        pay_total = pr.get('payment_total_brl')
        if pay_total is not None and refund is not None and abs(refund - pay_total) > 0.01:
            issues_found.append(f'{cid}: {pi} refund={refund} but payment_total={pay_total} (mismatch)')

    # 12. Secondary issues ordering
    si = ca.get('secondary_issues', [])
    prev = -1
    for s in si:
        if s in VALID_SECONDARY:
            idx = VALID_SECONDARY.index(s)
            if idx < prev:
                issues_found.append(f'{cid}: secondary_issues wrong order: {si}')
                break
            prev = idx
        else:
            issues_found.append(f'{cid}: invalid secondary_issue: {s}')

print(f'Total files checked: {len(files)}')
print(f'Total issues found: {len(issues_found)}')
print()
for i in issues_found:
    print(' ', i)
