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

## 3. Kết quả theo vai trò

| Nhiệm vụ | Artifact liên quan | Kết quả | Cách xác minh |
|---|---|---|---|
| Join customer history đúng order ID | `data_loader.py` | Related history chỉ chứa ID có trong orders | Regression test và validator |
| Đối soát policy | `policy_engine.py` | 6 primary issue theo đúng thứ tự ưu tiên | 50 output và phân bố trace |
| Kiểm tra output | `verifier.py`, `logging/trace.jsonl` | 50/50 case, 350/350 handoff LLM thành công | `pytest`, validation command |
| Đóng gói bài nộp | `output.zip` | Đúng `output/EC_001.json` đến `output/EC_050.json` | Kiểm tra ZipArchive |

## 4. Giải thích phần kỹ thuật

### Vấn đề cần giải quyết

Mỗi khiếu nại phải join order, customer, item, seller, product, payment và timestamp delivery. Kết luận phải có evidence dựng được từ CSV, không được để LLM tự tạo ID hoặc tự tính tiền.

### Cách triển khai

Data Loader đọc CSV một lần và tạo index chỉ-đọc. Customer, Order & Product, Payment và Delivery tạo facts deterministic. Policy engine áp dụng `EC_POLICY_V2` theo thứ tự ưu tiên. Coordinator gọi 7 logical agent, trong đó mỗi agent gửi một JSON review tới Groq; model chỉ diễn giải handoff, còn phép tính và quyết định cuối do code kiểm soát. Verifier kiểm tra schema, ID, evidence, null handling và giới hạn mảng trước khi ghi output.

### Input, output và contract

| Thành phần | Mô tả |
|---|---|
| Input | `input/EC_001.json` đến `input/EC_050.json` và Olist CSV |
| Output | `output/EC_XXX.json` theo schema README |
| Module phụ thuộc | `data_loader`, các domain agents, `policy_engine` |
| Module sử dụng output | `output_writer`, `validation`, ZIP submission |
| Điều kiện lỗi | Unknown ID, JSON sai, refund/status không nhất quán, related order không tồn tại |

### Cách xác minh

```powershell
$env:PYTHONPATH='src'; pytest -q
$env:PYTHONPATH='src'; python -m olist_multi_agent.validation --output-dir output --input-dir input --data-dir data
```

- Kết quả mong đợi: test pass, đủ 50 output và không có verifier error.
- Kết quả thực tế: 5 tests pass; 50 output hợp lệ; trace có 350/350 LLM handoff thành công.
- Artifact: `logging/trace.jsonl`, `logging/metadata.json`, `output.zip`.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Groq chỉ cung cấp một model phù hợp trong runtime hiện tại.
- **Phương án:** gọi nhiều model logic khác nhau hoặc dùng một model chung cho 7 role.
- **Lựa chọn:** dùng `llama-3.1-8b-instant` cho 7 logical agent và khai báo model trong `config.py`.
- **Lý do:** model dưới 10B, hỗ trợ JSON mode; dùng chung giúp giảm chi phí và tránh phụ thuộc model ID không tồn tại trên Groq. Các phép tính chính vẫn deterministic.
- **Bằng chứng:** `metadata.json` ghi 7 model, mỗi model 8B; trace ghi 350 handoff thành công.

## 6. Một lỗi đã xử lý

- **Triệu chứng:** `related_order_ids` trong output không tồn tại trong orders dataset.
- **Nguyên nhân:** Data Loader trước đó đưa `customer_id` trực tiếp vào danh sách được đặt tên là order IDs.
- **Cách xử lý:** join `orders.customer_id` với `customers.customer_id`, sau đó lưu `orders.order_id`; Verifier kiểm tra mọi related order có trong index.
- **Cách xác minh:** regression test kiểm tra toàn bộ history IDs là order IDs; validator kiểm tra lại 50 output.
- **Bài học:** tên biến và schema phải được kiểm chứng bằng source-of-truth index, không chỉ kiểm tra array shape.

## 7. Luồng end-to-end

1. Data Loader đọc orders, customers, items, payments, products, sellers và category translation.
2. Coordinator nhận case, gọi LLM để lập route, rồi dispatch bốn fact agent song song.
3. Customer Agent join customer identity và lịch sử bằng `customer_unique_id` nhưng trả về `order_id`.
4. Order/Product, Payment và Delivery tạo facts có evidence; Decimal và datetime xử lý các phép tính chính.
5. Policy Agent áp dụng `EC_POLICY_V2`, tạo primary issue, root cause, responsibility, refund và actions.
6. Verifier Agent review candidate bằng LLM rồi dùng verifier deterministic để kiểm tra schema, ID, evidence và limits.
7. Output Writer chỉ ghi candidate đã pass; Trace Writer ghi start, handoff và end cho từng case.
8. Validator kiểm tra 50 file; ZIP chỉ chứa `output/EC_001.json` đến `output/EC_050.json`.

## 8. Cam kết của thành viên

- [x] Nội dung báo cáo phản ánh phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end.
- [x] Tôi không ghi “đã chạy thành công” cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo không sao chép báo cáo thành viên khác.

**Họ và tên:** Hoàng Thị Hà Huyền  
**Ngày xác nhận:** 2026-08-05
