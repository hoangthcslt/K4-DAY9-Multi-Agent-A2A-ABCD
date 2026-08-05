"""Data layer: load the 9 Olist CSVs once, index them, and expose a single
join entrypoint `get_case_bundle(order_id)`.

Every agent reads from the bundle this module produces. No agent touches the
CSVs directly, so all agents in a case see exactly the same facts.
"""

import csv
import os
import sys

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# csv fields can exceed the default limit on the review comments file
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


def _read_csv(filename):
    path = os.path.join(DATA_DIR, filename)
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class OlistData:
    """Holds every CSV in memory, indexed for O(1) lookup by join key."""

    def __init__(self):
        self.orders_by_id = {}
        self.customers_by_id = {}
        self.items_by_order = {}
        self.payments_by_order = {}
        self.reviews_by_order = {}
        self.products_by_id = {}
        self.sellers_by_id = {}
        self.category_translation = {}
        self.orders_by_customer_unique = {}
        self._load()

    def _load(self):
        for row in _read_csv("olist_orders_dataset.csv"):
            self.orders_by_id[row["order_id"]] = row

        for row in _read_csv("olist_customers_dataset.csv"):
            self.customers_by_id[row["customer_id"]] = row

        for row in _read_csv("olist_order_items_dataset.csv"):
            self.items_by_order.setdefault(row["order_id"], []).append(row)

        for row in _read_csv("olist_order_payments_dataset.csv"):
            self.payments_by_order.setdefault(row["order_id"], []).append(row)

        for row in _read_csv("olist_order_reviews_dataset.csv"):
            self.reviews_by_order.setdefault(row["order_id"], []).append(row)

        for row in _read_csv("olist_products_dataset.csv"):
            self.products_by_id[row["product_id"]] = row

        for row in _read_csv("olist_sellers_dataset.csv"):
            self.sellers_by_id[row["seller_id"]] = row

        for row in _read_csv("product_category_name_translation.csv"):
            self.category_translation[row["product_category_name"]] = row[
                "product_category_name_english"
            ]

        # customer_unique_id -> every order that customer ever placed
        for order_id, order in self.orders_by_id.items():
            customer = self.customers_by_id.get(order["customer_id"])
            if not customer:
                continue
            unique_id = customer["customer_unique_id"]
            self.orders_by_customer_unique.setdefault(unique_id, []).append(order_id)

        # item rows must be ordered by order_item_id so array order is stable
        for order_id in self.items_by_order:
            self.items_by_order[order_id].sort(key=lambda r: int(r["order_item_id"]))

        # payment rows ordered by payment_sequential for the same reason
        for order_id in self.payments_by_order:
            self.payments_by_order[order_id].sort(
                key=lambda r: int(r["payment_sequential"])
            )


def _blank_to_none(value):
    """CSV writes missing timestamps as an empty string; the schema wants null."""
    if value is None:
        return None
    value = value.strip()
    return value if value else None


def get_case_bundle(data, order_id):
    """Join every table for one order into the structure agents consume.

    Returns None when the order_id does not exist in the orders table.
    """
    order = data.orders_by_id.get(order_id)
    if order is None:
        return None

    customer = data.customers_by_id.get(order["customer_id"])
    customer_unique_id = customer["customer_unique_id"] if customer else None

    # Historical orders of the same shopper, excluding the claimed order itself.
    related_order_ids = []
    if customer_unique_id:
        for other_id in data.orders_by_customer_unique.get(customer_unique_id, []):
            if other_id != order_id:
                related_order_ids.append(other_id)

    items = []
    for row in data.items_by_order.get(order_id, []):
        product = data.products_by_id.get(row["product_id"])
        category = product["product_category_name"] if product else ""
        items.append(
            {
                "order_item_id": row["order_item_id"],
                "product_id": row["product_id"],
                "seller_id": row["seller_id"],
                "shipping_limit_date": _blank_to_none(row["shipping_limit_date"]),
                "price": float(row["price"]),
                "freight_value": float(row["freight_value"]),
                "product_category_name": _blank_to_none(category),
            }
        )

    payments = []
    for row in data.payments_by_order.get(order_id, []):
        payments.append(
            {
                "payment_sequential": row["payment_sequential"],
                "payment_type": row["payment_type"],
                "payment_installments": int(row["payment_installments"]),
                "payment_value": float(row["payment_value"]),
            }
        )

    # Distinct ids, first-seen order preserved so output arrays stay stable.
    seller_ids = []
    product_ids = []
    category_names = []
    for item in items:
        if item["seller_id"] not in seller_ids:
            seller_ids.append(item["seller_id"])
        if item["product_id"] not in product_ids:
            product_ids.append(item["product_id"])
        category = item["product_category_name"]
        if category and category not in category_names:
            category_names.append(category)

    return {
        "order_id": order_id,
        "order": {
            "order_id": order_id,
            "customer_id": order["customer_id"],
            "order_status": order["order_status"],
            "order_purchase_timestamp": _blank_to_none(order["order_purchase_timestamp"]),
            "order_approved_at": _blank_to_none(order["order_approved_at"]),
            "order_delivered_carrier_date": _blank_to_none(
                order["order_delivered_carrier_date"]
            ),
            "order_delivered_customer_date": _blank_to_none(
                order["order_delivered_customer_date"]
            ),
            "order_estimated_delivery_date": _blank_to_none(
                order["order_estimated_delivery_date"]
            ),
        },
        "customer": {
            "customer_id": order["customer_id"],
            "customer_unique_id": customer_unique_id,
            "customer_city": customer["customer_city"] if customer else None,
            "customer_state": customer["customer_state"] if customer else None,
        },
        "related_order_ids": related_order_ids,
        "items": items,
        "payments": payments,
        "seller_ids": seller_ids,
        "product_ids": product_ids,
        "category_names": category_names,
    }


_DATA_SINGLETON = None


def load_data():
    """Load the CSVs once per process and reuse across all 50 cases."""
    global _DATA_SINGLETON
    if _DATA_SINGLETON is None:
        _DATA_SINGLETON = OlistData()
    return _DATA_SINGLETON
