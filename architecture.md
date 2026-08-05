# Architecture — Multi-Agent E-commerce Dispute Resolution

Hệ thống điều tra 50 khiếu nại thương mại điện tử trên dữ liệu Olist bằng một
đội agent. Mỗi agent phụ trách một domain dữ liệu, handoff phát hiện của mình
cho Coordinator, và Verifier chặn output trước khi ghi file.

## 1. Sơ đồ agent và luồng handoff

```
                        input/EC_XXX.json
                               │
                               ▼
                      ┌─────────────────┐
                      │   COORDINATOR   │  (LLM: intake, phân loại claim)
                      └────────┬────────┘
                               │  AgentMessage (handoff)
        ┌──────────────┬───────┴───────┬──────────────┐
        ▼              ▼               ▼              ▼
┌──────────────┐ ┌───────────┐ ┌─────────────┐ ┌────────────┐
│  CUSTOMER    │ │  ORDER &  │ │   PAYMENT   │ │  DELIVERY  │
│    AGENT     │ │  PRODUCT  │ │    AGENT    │ │   AGENT    │
│              │ │   AGENT   │ │             │ │            │
│ identity,    │ │ item,     │ │ reconcile   │ │ variance,  │
│ history      │ │ seller,   │ │ payment vs  │ │ seller     │
│              │ │ category  │ │ item+freight│ │ handoff    │
└──────┬───────┘ └─────┬─────┘ └──────┬──────┘ └─────┬──────┘
       │               │              │              │
       └───────────────┴──────┬───────┴──────────────┘
                              │  findings handoff
                              ▼
                     ┌─────────────────┐
                     │  POLICY AGENT   │  (LLM phân loại + rules engine đối chiếu)
                     │   EC_POLICY_V2  │
                     └────────┬────────┘
                              │  classified case
                              ▼
                     ┌─────────────────┐
                     │ VERIFIER AGENT  │  (rule-based, không LLM)
                     │ schema · evidence│
                     │ limits · nulls  │
                     └────────┬────────┘
                              │  pass / fail
                              ▼
                      output/EC_XXX.json
```

Mọi mũi tên trong sơ đồ là một `AgentMessage` được ghi vào `trace.jsonl`, nên
cấu trúc handoff quan sát được trong artifact chạy thật chứ không chỉ mô tả
trong tài liệu.

## 2. Vai trò và quyền truy cập dữ liệu

| Agent | Vai trò | Quyền đọc | Dùng LLM |
| ----- | ------- | --------- | -------- |
| `coordinator` | Nhận case, phân loại claim, điều phối, tổng hợp output | case input + toàn bộ finding | Có |
| `customer_agent` | Xác định khách hàng và lịch sử mua | `bundle.customer`, `bundle.related_order_ids` | Có |
| `order_product_agent` | Thành phần đơn: item, seller, product, category | `bundle.order`, `bundle.items`, `seller_ids`, `product_ids` | Có |
| `payment_agent` | Đối soát payment với item + freight | `bundle.payments` + reconciliation đã tính | Có |
| `delivery_agent` | Quy trách nhiệm trễ: seller hay logistics | delivery analysis đã tính | Có |
| `policy_agent` | Áp `EC_POLICY_V2`, phân loại primary issue | toàn bộ finding upstream | Có |
| `verifier_agent` | Gác cổng schema, evidence, array limit, null | output + bundle gốc | Không (thuần code) |

Không agent nào đọc CSV trực tiếp. Toàn bộ đọc từ `get_case_bundle()` của
`data_layer.py`, nên mọi agent trong cùng một case nhìn thấy đúng một tập fact.

## 3. Phân tách trách nhiệm: cái gì do code, cái gì do LLM

Đây là quyết định thiết kế trung tâm.

**Code quyết định (`policy_rules.py`)** — mọi con số và ID được chấm điểm:
`delivery_variance_hours`, `handoff_variance_hours`, `expected_total_brl`,
`difference_brl`, `reconciled`, primary/secondary issue, responsible party,
refund, actions, evidence ID.

**LLM đảm nhiệm** — điều phối, phân loại ý định khiếu nại tiếng Việt, diễn giải
fact thành nhận định, và ở Policy Agent là **phân loại độc lập để đối chiếu**
với rules engine.

Lý do: model ≤10B sai số học và sai thứ tự ưu tiên rule đủ thường xuyên để không
thể giao phần tính tiền/giờ. Nhưng nếu LLM chỉ lặp lại output của code thì
multi-agent thành trang trí. Cách giải quyết: Policy Agent nhận fact và **tự phân
loại theo prompt mô tả đầy đủ 6 rule**, sau đó hệ thống so sánh với kết quả rules
engine:

- Đồng ý → `confidence = 0.95`
- Bất đồng → `confidence = 0.75`, và `model_primary_issue` được ghi vào trace

Rules engine luôn thắng khi ghi output, nhưng bất đồng trở thành tín hiệu quan
sát được. `confidence` vì vậy phản ánh mức độ hai đường phân loại độc lập hội tụ,
chứ không phải một con số tùy chọn.

## 4. Data layer

`data_layer.py` nạp 9 CSV một lần cho cả process, index theo khóa join:

| Index | Khóa | Dùng cho |
| ----- | ---- | -------- |
| `orders_by_id` | `order_id` | tra đơn khiếu nại |
| `customers_by_id` | `customer_id` | lấy `customer_unique_id` |
| `items_by_order` | `order_id` | item, seller, product, freight |
| `payments_by_order` | `order_id` | payment row |
| `products_by_id` | `product_id` | category |
| `sellers_by_id` | `seller_id` | seller tồn tại |
| `orders_by_customer_unique` | `customer_unique_id` | lịch sử mua |

`get_case_bundle(order_id)` join tất cả thành một cấu trúc duy nhất. Item được
sort theo `order_item_id`, payment theo `payment_sequential`, để thứ tự mảng
trong output ổn định theo dữ liệu nguồn.

Xử lý null: chuỗi rỗng trong CSV chuyển thành `null` để khớp schema.

## 5. Verifier — các kiểm tra bắt buộc

Thuần code, vì model nhỏ không thể là tuyến phòng thủ cuối cho tính đúng schema.

1. **Evidence ID**: regex đúng 5 pattern, *và* phải dựng được từ chính bundle đã
   nạp (so khớp tập hợp), chặn false positive.
2. **Array limit**: 5/5/3/5/5/5/5/3/3/20/5 theo README mục 6, cắt trước khi kiểm tra.
3. **`case_status` ↔ refund**: `action_required` khi và chỉ khi refund > 0.
4. **`confidence`** trong `[0,1]`.
5. **Timestamp**: đúng `YYYY-MM-DD HH:MM:SS` hoặc `null`.
6. **Order không có item row**: `expected_total_brl`, `difference_brl`,
   `reconciled` phải `null`; mảng item/seller/product/category/handoff rỗng.
7. **`affected_entities.order_ids`** đúng bằng order khiếu nại; order lịch sử chỉ
   được xuất hiện trong `customer_context.related_order_ids`.
8. **Enum hợp lệ**: primary issue, secondary issue, cause code, action, party type.
9. **Không trùng lặp** trong evidence, action, secondary issue.

Case fail gate vẫn được ghi ra file nhưng bị hạ `confidence`, và lỗi được in ra
console cùng ghi vào trace — không im lặng ship một case trông sạch nhưng chưa
được kiểm chứng.

## 6. trace.jsonl

Truncate ở đầu mỗi lần chạy (README yêu cầu lượt chạy mới nhất, không append).
Ba loại record:

```json
{"case_id":"EC_002","event":"a2a_message","from_agent":"coordinator","to_agent":"payment_agent","message_type":"handoff","payload":{},"timestamp":"..."}
{"case_id":"EC_002","event":"agent_step","step":"payment_agent","model":"llama-3.1-8b-instant","input":{},"output":{},"duration_ms":1388,"usage":{"total_tokens":396},"timestamp":"..."}
{"case_id":"EC_002","event":"case_complete","detail":{"primary_issue":"late_delivery_seller","case_status":"action_required","refund_brl":18.27,"verifier_passed":true},"timestamp":"..."}
```

`usage.total_tokens` trên từng `agent_step` là bằng chứng mỗi agent thực sự gọi
model, không phải echo lại kết quả code đã tính sẵn.

## 7. Xử lý lỗi

- **LLM không gọi được**: mỗi agent có `fallback()` deterministic. Case vẫn hoàn
  thành với đúng số liệu (vì số liệu vốn do code tính), `llm_available: false`
  được ghi vào trace, `confidence` hạ xuống 0.80.
- **Rate limit / lỗi 5xx**: `llm_client.py` retry 4 lần với backoff, tôn trọng
  header `retry-after`.
- **Model trả JSON hỏng**: retry; hết lượt thì dùng fallback.
- **Order không tồn tại trong CSV**: ghi `order_not_found` vào trace, không sinh
  output bịa cho case đó.

## 8. Model

| Thuộc tính | Giá trị |
| ---------- | ------- |
| Model | `llama-3.1-8b-instant` |
| Parameter size | 8B (dưới giới hạn 10B) |
| Provider | Groq |
| Temperature | 0.0 (để chạy lại cho kết quả ổn định) |
| Response format | `json_object` |
| Khai báo trong source | `src/llm_client.py` → `MODEL_NAME` |

API key đọc từ `.env` (`GROQ_API_KEY`), không commit. Tên model đặt trong source
code theo yêu cầu README mục 9, và lặp lại trong `metadata.json`.

## 9. Chạy

```bash
python src/run.py                 # toàn bộ 50 case
python src/run.py --limit 3       # smoke test
python src/run.py --case EC_007   # một case cụ thể
```
