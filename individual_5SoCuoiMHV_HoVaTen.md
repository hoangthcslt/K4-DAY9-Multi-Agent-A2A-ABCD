# Báo cáo cá nhân — K4 Day 09: Multi-Agent E-commerce Dispute Resolution

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
|---|---|
| Họ và tên | Hoàng Thị Hà Huyền |
| MSSV | 2A202601909 |
| Khóa/Lớp | K4 |
| Vai trò chính | Xây dựng pipeline multi-agent, policy engine, verifier và kiểm định output |
| Ngày hoàn thành | 2026-08-05 |

## 2. Vai trò và phạm vi công việc

| Module/deliverable | File/hàm phụ trách | Input | Output bàn giao | Trạng thái |
|---|---|---|---|---|
| Data join và customer history | `src/olist_multi_agent/data_loader.py`, `agents/customer.py` | Olist CSV, `claimed_order_id` | Customer identity và related order IDs | Hoàn thành |
| Policy và resolution | `policy_engine.py`, `agents/policy.py` | Facts từ các handoff | Primary issue, root cause, refund, actions | Hoàn thành |
| Output contract và verifier | `output_builder.py`, `verifier.py`, `validation.py` | Candidate JSON, indexes | Output hợp lệ theo README | Hoàn thành |
| LLM orchestration | `agents/coordinator.py`, `agents/base.py`, `llm_client.py` | Case và deterministic facts | 7 LLM handoff/case, retry và trace | Hoàn thành |

## 3. Kết quả và cách xác minh

Data Loader join `orders.customer_id` với `customers.customer_id`, sau đó lưu `orders.order_id` cho
`customer_context.related_order_ids`. Các phép tính tiền dùng `Decimal`, timestamp dùng `datetime`,
và policy `EC_POLICY_V2` được áp dụng deterministic theo đúng thứ tự ưu tiên. LLM chỉ review facts;
không được tự sinh ID, amount hoặc timestamp.

Mỗi case có bảy logical handoff tới Groq model `llama-3.1-8b-instant` (8B): Coordinator, Customer,
Order & Product, Payment, Delivery, Policy và Verifier. Verifier deterministic kiểm tra schema, ID,
evidence, null handling và array limits trước khi ghi output.

Kết quả kiểm chứng của lần chạy gần nhất:

- 50/50 output `output/EC_001.json` đến `output/EC_050.json`.
- 350/350 handoff LLM thành công; trace được reset cho run mới.
- Validator và regression tests pass.
- `output.zip` chỉ chứa đúng 50 entry `output/EC_001.json` đến `output/EC_050.json`.

## 4. Luồng end-to-end

1. Data Loader đọc orders, customers, items, payments, products, sellers và category translation.
2. Coordinator nhận input và gọi LLM để tạo route review, sau đó dispatch bốn fact agent.
3. Customer Agent join customer identity và lịch sử bằng `customer_unique_id`, trả về order IDs thật.
4. Order/Product, Payment và Delivery tạo facts deterministic có evidence.
5. Policy Agent áp dụng `EC_POLICY_V2`, tạo primary issue, root cause, responsibility, refund và actions.
6. Verifier Agent review candidate bằng LLM rồi chạy kiểm tra deterministic.
7. Output Writer chỉ ghi candidate đã pass; Trace Writer ghi run mới nhất.

## 5. Lỗi đã xử lý

Lỗi quan trọng là customer history trước đó dùng `customer_id` như thể là `order_id`, khiến
`related_order_ids` không tồn tại trong orders dataset. Lỗi đã được sửa bằng join hai bước nêu trên,
đồng thời bổ sung regression test để mọi related ID phải tồn tại trong `orders_by_id`.

Các script `scripts/run_cases.py` và `scripts/validate_outputs.py` cũng tự thêm `src/` vào import path,
vì vậy có thể chạy trực tiếp từ root repo mà không cần editable install.

## 6. Artifact bàn giao

- Kiến trúc: `architecture.md`.
- Trace và metadata: `logging/trace.jsonl`, `logging/metadata.json`.
- Output: `output/EC_001.json` đến `output/EC_050.json`.
- Archive nộp bài: `output.zip`.

**Họ và tên:** Hoàng Thị Hà Huyền  
**Ngày xác nhận:** 2026-08-05
