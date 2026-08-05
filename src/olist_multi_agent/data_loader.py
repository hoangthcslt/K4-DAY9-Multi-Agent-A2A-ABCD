"""CSV loading and read-only indexes used by all agents."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _group(rows: Iterable[dict[str, str]], key: str) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        result.setdefault(row[key], []).append(row)
    return result


@dataclass
class OlistIndexes:
    orders_by_id: dict[str, dict[str, str]]
    customers_by_id: dict[str, dict[str, str]]
    customer_rows_by_unique_id: dict[str, list[dict[str, str]]]
    customer_order_ids_by_unique_id: dict[str, list[str]]
    items_by_order: dict[str, list[dict[str, str]]]
    payments_by_order: dict[str, list[dict[str, str]]]
    products_by_id: dict[str, dict[str, str]]
    sellers_by_id: dict[str, dict[str, str]]
    category_translation_by_name: dict[str, dict[str, str]]
    row_counts: dict[str, int] = field(default_factory=dict)

    @classmethod
    def load(cls, data_dir: Path) -> "OlistIndexes":
        orders = _read_csv(data_dir / "olist_orders_dataset.csv")
        customers = _read_csv(data_dir / "olist_customers_dataset.csv")
        items = _read_csv(data_dir / "olist_order_items_dataset.csv")
        payments = _read_csv(data_dir / "olist_order_payments_dataset.csv")
        products = _read_csv(data_dir / "olist_products_dataset.csv")
        sellers = _read_csv(data_dir / "olist_sellers_dataset.csv")
        translations = _read_csv(data_dir / "product_category_name_translation.csv")

        orders_by_id = {row["order_id"]: row for row in orders}
        customers_by_id = {row["customer_id"]: row for row in customers}
        customer_rows_by_unique_id = _group(customers, "customer_unique_id")
        customer_order_ids_by_unique_id: dict[str, list[str]] = {}
        for row in customers:
            order_id = row["customer_id"]
            customer_order_ids_by_unique_id.setdefault(row["customer_unique_id"], []).append(
                order_id
            )

        return cls(
            orders_by_id=orders_by_id,
            customers_by_id=customers_by_id,
            customer_rows_by_unique_id=customer_rows_by_unique_id,
            customer_order_ids_by_unique_id=customer_order_ids_by_unique_id,
            items_by_order=_group(items, "order_id"),
            payments_by_order=_group(payments, "order_id"),
            products_by_id={row["product_id"]: row for row in products},
            sellers_by_id={row["seller_id"]: row for row in sellers},
            category_translation_by_name={
                row["product_category_name"]: row for row in translations
            },
            row_counts={
                "orders": len(orders),
                "customers": len(customers),
                "items": len(items),
                "payments": len(payments),
                "products": len(products),
                "sellers": len(sellers),
                "translations": len(translations),
            },
        )

    def order(self, order_id: str) -> dict[str, str]:
        try:
            return self.orders_by_id[order_id]
        except KeyError as exc:
            raise KeyError(f"Unknown order_id: {order_id}") from exc
