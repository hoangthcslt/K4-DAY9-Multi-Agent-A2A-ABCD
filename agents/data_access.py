"""
DataAccessLayer — Shared data access for all agents.
Loads all 9 Olist CSV files into pandas DataFrames once,
provides lookup functions for each domain.
"""

import pandas as pd
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


class DataAccessLayer:
    """Singleton-like shared data layer. Load once, query many times."""

    def __init__(self):
        print("[DataAccessLayer] Loading CSV files...")
        self.orders = pd.read_csv(os.path.join(DATA_DIR, "olist_orders_dataset.csv"))
        self.order_items = pd.read_csv(os.path.join(DATA_DIR, "olist_order_items_dataset.csv"))
        self.payments = pd.read_csv(os.path.join(DATA_DIR, "olist_order_payments_dataset.csv"))
        self.customers = pd.read_csv(os.path.join(DATA_DIR, "olist_customers_dataset.csv"))
        self.products = pd.read_csv(os.path.join(DATA_DIR, "olist_products_dataset.csv"))
        self.sellers = pd.read_csv(os.path.join(DATA_DIR, "olist_sellers_dataset.csv"))
        self.reviews = pd.read_csv(os.path.join(DATA_DIR, "olist_order_reviews_dataset.csv"))
        self.geolocation = pd.read_csv(os.path.join(DATA_DIR, "olist_geolocation_dataset.csv"))
        self.category_translation = pd.read_csv(
            os.path.join(DATA_DIR, "product_category_name_translation.csv")
        )
        print(f"[DataAccessLayer] Loaded {len(self.orders)} orders, "
              f"{len(self.order_items)} items, {len(self.payments)} payments.")

    # ── Order lookups ──

    def get_order(self, order_id: str) -> dict | None:
        """Get single order row as dict. Returns None if not found."""
        rows = self.orders[self.orders["order_id"] == order_id]
        if rows.empty:
            return None
        row = rows.iloc[0].to_dict()
        # Convert NaN to None for JSON compatibility
        return {k: (None if pd.isna(v) else v) for k, v in row.items()}

    def get_order_items(self, order_id: str) -> list[dict]:
        """Get all item rows for an order, sorted by order_item_id (stable order per spec)."""
        rows = self.order_items[self.order_items["order_id"] == order_id]
        rows = rows.sort_values("order_item_id")
        return self._to_clean_list(rows)

    def get_payments(self, order_id: str) -> list[dict]:
        """Get all payment rows for an order, sorted by payment_sequential (stable order per spec)."""
        rows = self.payments[self.payments["order_id"] == order_id]
        rows = rows.sort_values("payment_sequential")
        return self._to_clean_list(rows)

    # ── Customer lookups ──

    def get_customer_by_id(self, customer_id: str) -> dict | None:
        """Get customer row by customer_id."""
        rows = self.customers[self.customers["customer_id"] == customer_id]
        if rows.empty:
            return None
        row = rows.iloc[0].to_dict()
        return {k: (None if pd.isna(v) else v) for k, v in row.items()}

    def get_customer_orders(self, customer_unique_id: str) -> list[dict]:
        """Get all orders for a customer_unique_id (for repeat customer detection)."""
        cust_ids = self.customers[
            self.customers["customer_unique_id"] == customer_unique_id
        ]["customer_id"].tolist()
        rows = self.orders[self.orders["customer_id"].isin(cust_ids)]
        return self._to_clean_list(rows)

    # ── Product lookups ──

    def get_product(self, product_id: str) -> dict | None:
        """Get product row by product_id."""
        rows = self.products[self.products["product_id"] == product_id]
        if rows.empty:
            return None
        row = rows.iloc[0].to_dict()
        return {k: (None if pd.isna(v) else v) for k, v in row.items()}

    def get_category_english(self, category_name_pt: str) -> str | None:
        """Translate Portuguese category name to English."""
        if pd.isna(category_name_pt) or category_name_pt is None:
            return None
        rows = self.category_translation[
            self.category_translation["product_category_name"] == category_name_pt
        ]
        if rows.empty:
            return category_name_pt  # fallback to original
        return rows.iloc[0]["product_category_name_english"]

    # ── Seller lookups ──

    def get_seller(self, seller_id: str) -> dict | None:
        """Get seller row by seller_id."""
        rows = self.sellers[self.sellers["seller_id"] == seller_id]
        if rows.empty:
            return None
        row = rows.iloc[0].to_dict()
        return {k: (None if pd.isna(v) else v) for k, v in row.items()}

    # ── Utilities ──

    def _to_clean_list(self, df: pd.DataFrame) -> list[dict]:
        """Convert DataFrame to list of dicts with NaN -> None."""
        records = df.to_dict("records")
        return [
            {k: (None if pd.isna(v) else v) for k, v in row.items()}
            for row in records
        ]
