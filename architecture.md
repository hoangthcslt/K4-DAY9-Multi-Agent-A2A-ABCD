# Architecture — Multi-Agent E-commerce Dispute Resolution

## 1. Tổng quan

Hệ thống Enhanced Hybrid Multi-Agent xử lý 50 khiếu nại khách hàng trên dữ liệu Olist.
- **5 agents** + 1 DataAccessLayer chia sẻ
- **Deterministic** cho data lookup & tính toán (pandas) → đảm bảo chính xác
- **LLM** (Llama 3.1 8B via Groq) cho reasoning & confidence → thể hiện multi-agent

## 2. Sơ đồ kiến trúc

```
                    ┌─────────────────┐
                    │   Input JSON    │
                    │  (EC_001..050)  │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  Coordinator    │
                    │    Agent        │
                    └──┬─────┬─────┬──┘
                       │     │     │
         ┌─────────────┼─────┼─────┼──────────────┐
         │             │     │     │              │
    ┌────▼────┐  ┌─────▼───┐ │  ┌──▼──────┐      │
    │Investig.│  │Delivery │ │  │Payment  │      │
    │ Agent   │  │ Agent   │ │  │ Agent   │      │
    │(pandas+ │  │(pandas+ │ │  │(pandas+ │      │
    │  LLM)   │  │  LLM)   │ │  │  LLM)   │      │
    └────┬────┘  └────┬────┘ │  └────┬────┘      │
         │            │      │       │            │
         └────────────┼──────┼───────┘            │
                      │      │                    │
                 ┌────▼──────▼────┐               │
                 │  Policy Agent  │               │
                 │  (rules+LLM)  │               │
                 └───────┬────────┘               │
                         │                        │
                 ┌───────▼────────┐               │
                 │Verifier Agent  │               │
                 │  (rules only)  │               │
                 └───────┬────────┘               │
                         │                        │
                    ┌────▼────────────────────────▼┐
                    │      Output JSON + Trace     │
                    └──────────────────────────────┘
```

## 3. Chi tiết từng Agent

### DataAccessLayer (Shared)
- **File:** `agents/data_access.py`
- **Loại:** Python module (không phải agent)
- **Quyền truy cập:** 9 CSV files (orders, items, payments, customers, products, sellers, reviews, geolocation, category_translation)
- **Chức năng:** Load CSV vào pandas DataFrames 1 lần, cung cấp lookup functions

### Coordinator Agent
- **File:** `agents/coordinator_agent.py`
- **Loại:** Deterministic (Python)
- **Vai trò:** Nhận input case, dispatch tới 3 investigation agents, merge kết quả, gửi Policy → Verifier, ghi output
- **Quyền truy cập:** Input/Output files, điều phối tất cả agents khác

### Investigation Agent
- **File:** `agents/investigation_agent.py`
- **Loại:** Hybrid (pandas + LLM)
- **Vai trò:** Tra cứu order, items, sellers, products, categories, customer history
- **Quyền truy cập:** orders, order_items, customers, products, sellers, category_translation
- **Handoff:** Gửi structured data (order info, items, sellers, customer context, flags) → Policy Agent

### Delivery Agent
- **File:** `agents/delivery_agent.py`
- **Loại:** Hybrid (datetime math + LLM)
- **Vai trò:** Tính delivery_variance_hours, handoff_variance_hours, xác định late sellers
- **Quyền truy cập:** orders, order_items
- **Handoff:** Gửi delivery analysis (variance, late sellers) → Policy Agent

### Payment Agent
- **File:** `agents/payment_agent.py`
- **Loại:** Hybrid (arithmetic + LLM)
- **Vai trò:** Đối soát payment vs items+freight, tính difference, reconciled
- **Quyền truy cập:** order_items, order_payments
- **Handoff:** Gửi payment reconciliation → Policy Agent

### Policy Agent
- **File:** `agents/policy_agent.py`
- **Loại:** Hybrid (rule engine + LLM confidence)
- **Vai trò:** Áp dụng EC_POLICY_V2, xác định primary/secondary issues, root cause, refund, actions
- **Input nhận:** Investigation + Delivery + Payment results
- **Handoff:** Gửi final assessment → Verifier Agent

### Verifier Agent
- **File:** `agents/verifier_agent.py`
- **Loại:** Deterministic (rules only)
- **Vai trò:** Validate schema, evidence IDs, array limits, null handling
- **Handoff:** Xác nhận valid → Coordinator ghi output

## 4. Luồng Handoff

```
1. Coordinator đọc input JSON → extract case_id, order_id
2. Coordinator → Investigation Agent (order_id)
3. Coordinator → Delivery Agent (order_id)
4. Coordinator → Payment Agent (order_id)
5. Investigation → Policy Agent (order info, items, customer, flags)
6. Delivery → Policy Agent (delivery variance, late sellers)
7. Payment → Policy Agent (reconciliation results)
8. Policy → Verifier Agent (draft output)
9. Verifier → Coordinator (validated output)
10. Coordinator → ghi output/EC_XXX.json + trace
```

## 5. Technology Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.13 |
| Data Processing | pandas |
| LLM Provider | Groq API |
| LLM Model | llama-3.1-8b-instant (8B params) |
| SDK | groq-python-sdk |
| Config | python-dotenv |
