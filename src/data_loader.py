import pandas as pd
import os
from typing import Dict, Any, List

class DataLoader:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.orders = pd.read_csv(os.path.join(data_dir, "olist_orders_dataset.csv"))
        self.customers = pd.read_csv(os.path.join(data_dir, "olist_customers_dataset.csv"))
        self.order_items = pd.read_csv(os.path.join(data_dir, "olist_order_items_dataset.csv"))
        self.order_payments = pd.read_csv(os.path.join(data_dir, "olist_order_payments_dataset.csv"))
        self.products = pd.read_csv(os.path.join(data_dir, "olist_products_dataset.csv"))

    def _clean_val(self, val):
        if pd.isna(val) or val is None:
            return None
        return val

    def get_customer_info(self, order_id: str) -> Dict[str, Any]:
        order = self.orders[self.orders['order_id'] == order_id]
        if order.empty:
            return {"customer_unique_id": None, "related_order_ids": []}
            
        customer_id = order.iloc[0]['customer_id']
        customer = self.customers[self.customers['customer_id'] == customer_id]
        if customer.empty:
            return {"customer_unique_id": None, "related_order_ids": []}
            
        customer_unique_id = customer.iloc[0]['customer_unique_id']
        
        related_customers = self.customers[self.customers['customer_unique_id'] == customer_unique_id]
        related_customer_ids = related_customers['customer_id'].tolist()
        
        related_orders = self.orders[self.orders['customer_id'].isin(related_customer_ids)]
        related_order_ids = related_orders['order_id'].tolist()
        
        if order_id in related_order_ids:
            related_order_ids.remove(order_id)
            
        return {
            "customer_unique_id": self._clean_val(customer_unique_id),
            "related_order_ids": related_order_ids
        }

    def get_order_items(self, order_id: str) -> List[Dict[str, Any]]:
        items = self.order_items[self.order_items['order_id'] == order_id]
        if items.empty:
            return []
        
        items_with_products = items.merge(self.products, on='product_id', how='left')
        
        result = []
        for _, row in items_with_products.iterrows():
            result.append({
                "order_item_id": self._clean_val(row['order_item_id']),
                "product_id": self._clean_val(row['product_id']),
                "seller_id": self._clean_val(row['seller_id']),
                "price": float(self._clean_val(row['price'])) if self._clean_val(row['price']) is not None else None,
                "freight_value": float(self._clean_val(row['freight_value'])) if self._clean_val(row['freight_value']) is not None else None,
                "shipping_limit_date": self._clean_val(row['shipping_limit_date']),
                "product_category_name": self._clean_val(row.get('product_category_name', None))
            })
        return result

    def get_payments(self, order_id: str) -> List[Dict[str, Any]]:
        payments = self.order_payments[self.order_payments['order_id'] == order_id]
        if payments.empty:
            return []
        
        result = []
        for _, row in payments.iterrows():
            result.append({
                "payment_sequential": self._clean_val(row['payment_sequential']),
                "payment_type": self._clean_val(row['payment_type']),
                "payment_value": float(self._clean_val(row['payment_value'])) if self._clean_val(row['payment_value']) is not None else None
            })
        return result

    def get_delivery_info(self, order_id: str) -> Dict[str, Any]:
        order = self.orders[self.orders['order_id'] == order_id]
        if order.empty:
            return {}
        
        row = order.iloc[0]
        return {
            "order_status": self._clean_val(row['order_status']),
            "order_delivered_customer_date": self._clean_val(row['order_delivered_customer_date']),
            "order_estimated_delivery_date": self._clean_val(row['order_estimated_delivery_date']),
            "order_delivered_carrier_date": self._clean_val(row['order_delivered_carrier_date'])
        }
