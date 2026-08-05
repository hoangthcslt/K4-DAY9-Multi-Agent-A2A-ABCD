# Member Role Report — Day 9: Multi Agent A2A

## 1. Thông tin cá nhân

| Thông tin       | Nội dung                                          |
| --------------- | ------------------------------------------------- |
| Họ và tên       | Dương Văn Kiên                                    |
| MSSV            | 2A202601724                                       |
| Khóa/Lớp        | K4                                                |
| Vai trò chính   | System Architect & Policy/Verification Engineer   |
| Ngày hoàn thành | 2026-08-05                                        |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| ------------------ | ------------------ | -------------- | --------------- | ---------- |
| Data layer | `src/data_layer.py` — `OlistData`, `get_case_bundle()` | 9 file CSV trong `data/` | Case bundle đã join (order, item, payment, customer, seller, product, related orders) | Hoàn thành |
| Policy engine | `src/policy_rules.py` — `apply_policy()`, `analyze_delivery()`, `analyze_payment()`, `determine_*()` | Case bundle | Assessment deterministic: primary/secondary issue, refund, actions, evidence, root cause | Hoàn thành |
| Agent orchestration | `src/agents/coordinator.py` — `Coordinator.process()`, `IntakeAgent` | Case input + bundle | Output JSON hoàn chỉnh, các handoff ghi vào trace | Hoàn thành |
| Verifier gate | `src/agents/verifier_agent.py` — `verify_output()`, `enforce_limits()`, `build_valid_evidence_set()` | Output đã lắp ráp + bundle gốc | Danh sách lỗi; output đã cắt theo array limit | Hoàn thành |
| Independent audit | `src/audit_outputs.py` — `audit_case()` | 50 output + CSV gốc | Báo cáo audit: 0 vấn đề / 50 case | Hoàn thành |
| Trace & A2A protocol | `src/trace_logger.py` — `AgentMessage`, `TraceLogger` | Sự kiện từ mọi agent | `trace.jsonl` — 800 dòng, 350 a2a_message + 350 agent_step | Hoàn thành |
| Tài liệu kiến trúc | `architecture.md`, `metadata.json` | Thiết kế hệ thống | Sơ đồ agent, bảng quyền truy cập, khai báo model | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --------- | ----------------------------- | ------- |
| Debug sự cố mất kết nối Groq giữa batch | Toàn bộ pipeline (EC_043–EC_049) | Thêm cờ `--no-truncate-trace` và `TraceLogger.drop_cases()`; chạy lại 7 case mà không phá trace của 43 case còn lại |
| Thiết kế prompt cho các domain agent | `customer_agent`, `order_product_agent`, `payment_agent`, `delivery_agent` | Prompt ép JSON schema con; model 8B trả JSON hợp lệ 300/300 lượt gọi ở lượt chạy cuối |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --------------------- | --------------------------- | ---------------- | ------------- |
| Join 9 CSV thành một nguồn fact duy nhất | `src/data_layer.py` | 99.441 order được index; bundle trả về trong O(1) | `python src/run.py --case EC_002` in ra đúng entity của order |
| Cài đặt EC_POLICY_V2 deterministic | `src/policy_rules.py` | 6 primary issue, 5 secondary, 6 root cause, công thức variance/reconciliation | `python src/audit_outputs.py` recompute toàn bộ từ CSV, khớp 50/50 |
| Cổng kiểm chứng trước khi ghi file | `src/agents/verifier_agent.py` | 9 nhóm kiểm tra: evidence, array limit, null, enum, status↔refund | Log console `Verifier: all cases passed.` |
| Audit độc lập | `src/audit_outputs.py` | 0 vấn đề trên 50 case | `python src/audit_outputs.py` → `All outputs conform to the spec.` |
| Sinh 50 output | `output/EC_001.json` … `EC_050.json` | 50 file đúng schema | `ls output/*.json \| wc -l` → 50 |

Nêu một output cụ thể mà phần việc của bạn tạo ra hoặc giúp xác minh:

`src/audit_outputs.py` là artifact tôi coi trọng nhất. Nó **không tái sử dụng code
của verifier**: với mỗi case, nó tự nạp lại CSV, tự gọi `apply_policy()` để suy ra
kỳ vọng, rồi so sánh từng field với file output đã ghi. Nhờ vậy nếu verifier có bug
thì audit vẫn phát hiện được — một checker dùng chung code với thứ nó kiểm tra sẽ
mù trước chính lỗi của mình. Kết quả chạy: `Problems: 0` trên cả 50 case, kèm phân
bố `late_delivery_seller 10 / late_delivery_logistics 10 / unsupported_late_claim 8
/ canceled_order_paid 8 / valid_split_payment 8 / unavailable_order_paid 6`.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Bài toán buộc mỗi agent dùng model ≤10B. Model ở kích thước đó sai số học và sai
thứ tự ưu tiên rule đủ thường xuyên để không thể giao cho nó tính `delivery_variance_hours`
hay `expected_total_brl` — mà đây lại chính là các con số được chấm điểm. Nhưng nếu
LLM chỉ lặp lại kết quả code đã tính thì multi-agent trở thành trang trí, và đề bài
nói rõ "không có điểm cho việc chỉ đặt tên nhiều agent".

Phần việc của tôi là giải quyết mâu thuẫn đó: giữ độ chính xác tuyệt đối cho số liệu
mà vẫn để LLM đóng vai trò thực chất.

### Cách triển khai

Tôi tách hệ thống theo ranh giới **cái gì kiểm chứng được** thay vì theo tên agent:

- **Code quyết định** (`policy_rules.py`): mọi con số và ID được chấm — variance,
  reconciliation, primary/secondary issue, responsible party, refund, actions, evidence ID.
- **LLM đảm nhiệm**: điều phối, đọc khiếu nại tiếng Việt để phân loại ý định, diễn giải
  fact thành nhận định, và ở Policy Agent là **phân loại độc lập**.

Điểm mấu chốt là Policy Agent: tôi cho nó prompt mô tả đầy đủ 6 rule của EC_POLICY_V2
và các fact đã trích xuất, rồi để nó **tự phân loại mà không thấy kết quả của rules
engine**. Sau đó hệ thống so sánh hai đường:

- Đồng ý → `confidence = 0.95`
- Bất đồng → `confidence = 0.75`, và `model_primary_issue` được ghi vào trace

Rules engine luôn thắng khi ghi output, nên bất đồng không làm hỏng số liệu — nó trở
thành **tín hiệu quan sát được**. Nhờ vậy `confidence` phản ánh mức hội tụ của hai
đường phân loại độc lập, chứ không phải một con số tôi tự đặt.

Về `data_layer.py`: tôi cho mọi agent đọc từ đúng một bundle thay vì mỗi agent tự query
CSV. Lý do là nếu hai agent join dữ liệu riêng lẻ, chúng có thể thấy hai phiên bản sự
thật khác nhau về cùng một order, và loại bug đó rất khó phát hiện qua output.

### Input, output và contract

| Thành phần | Mô tả |
| ---------- | ----- |
| Input | `input/EC_XXX.json` (`claimed_order_id`, `investigation_scope`) + 9 CSV Olist |
| Output | `output/EC_XXX.json` đúng schema mục 6 README; `trace.jsonl` |
| Module phụ thuộc | `data_layer.py` → `policy_rules.py` → các agent → `verifier_agent.py` |
| Module sử dụng output | `audit_outputs.py` đọc lại toàn bộ `output/` để đối chiếu |
| Điều kiện lỗi cần xử lý | Order không có item row (money field = `null`, mảng rỗng); order không tồn tại trong CSV; LLM mất kết nối; model trả JSON hỏng; rate limit 429 |

### Cách xác minh

```bash
python src/run.py --limit 3        # smoke test 3 case
python src/run.py                  # chạy đủ 50 case
python src/audit_outputs.py        # audit độc lập
```

- **Kết quả mong đợi:** 50 file output đúng schema, verifier pass toàn bộ, audit báo 0 vấn đề.
- **Kết quả thực tế:** `[50/50] EC_050 -> unsupported_late_claim / no_action (ok)`,
  `Verifier: all cases passed.`, `Problems: 0`, `All outputs conform to the spec.`
  Trace lượt cuối: 50 case, 350 agent_step, 350 a2a_message, 300 lượt gọi LLM, **0 lỗi**,
  ~123.000 token. Policy Agent đồng ý với rules engine **50/50 case**.
- **Artifact/log:** `output/EC_001.json`–`EC_050.json`, `trace.jsonl` (800 dòng). Không chứa secret.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Ai tính các con số được chấm điểm — LLM hay code?

- **Các phương án đã cân nhắc:**
  1. **LLM tính toàn bộ:** đưa dữ liệu thô cho model 8B, yêu cầu tự tính variance,
     đối soát tiền và áp rule. Đúng tinh thần "agent tự chủ" nhất.
  2. **Code tính toàn bộ, LLM chỉ tóm tắt:** an toàn tuyệt đối về số liệu, nhưng LLM
     thành lớp trang trí — vi phạm yêu cầu multi-agent thực chất của đề.
  3. **Code tính, LLM phân loại độc lập rồi đối chiếu:** code giữ số liệu; LLM vẫn phải
     ra quyết định thật (chọn 1 trong 6 rule) và quyết định đó được đo lường.

- **Phương án đã chọn:** Phương án 3.

- **Lý do:** Phương án 1 đặt 15% điểm delivery + 15% payment + 15% root cause vào tay
  một model hay sai số học — rủi ro không tương xứng. Phương án 2 an toàn nhưng không
  còn là hệ multi-agent theo nghĩa đề yêu cầu. Phương án 3 giữ được cả hai: sai sót của
  LLM không thể làm hỏng output, nhưng đóng góp của nó vẫn đo được qua tỷ lệ đồng thuận,
  và tỷ lệ đó trở thành `confidence` có căn cứ thay vì một hằng số tùy chọn.

- **Bằng chứng quyết định phù hợp:** Policy Agent đồng ý với rules engine **50/50 case**
  ở lượt chạy cuối — nghĩa là model 8B *có* đủ năng lực phân loại khi được cung cấp fact
  sạch, nhưng tôi không phải đặt cược điểm số vào việc nó luôn đúng. Quan trọng hơn: khi
  mạng đứt ở 7 case, output vẫn chính xác 100% (đã verify bằng recompute) — điều bất khả
  nếu chọn phương án 1.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:**
  ```
  LLM call failed after 4 attempts: HTTPSConnectionPool(host='api.groq.com', port=443):
  Max retries exceeded with url: /openai/v1/chat/completions
  (Caused by NewConnectionError(...))
  ```

- **Lệnh hoặc bước tái hiện:** `python src/run.py` — lỗi xuất hiện ở EC_043 đến EC_049,
  phát hiện khi thấy tốc độ batch tụt từ ~2,5 case/phút xuống ~0,4 case/phút.

- **Nguyên nhân gốc:** Kết nối mạng tới `api.groq.com` bị gián đoạn tạm thời. Không phải
  lỗi code, nhưng phơi bày **một lỗi thiết kế thật trong `run.py`**: hàm khởi tạo trace
  luôn truncate `trace.jsonl`. Nghĩa là nếu tôi chạy lại riêng vài case bị hỏng, trace
  của các case còn lại sẽ bị xóa sạch — mà README yêu cầu trace đủ 50 case của lượt chạy
  mới nhất.

- **Cách xử lý:** Hai thay đổi:
  1. Thêm cờ `--no-truncate-trace` vào `run.py` để chạy lại subset mà không xóa trace.
  2. Thêm `TraceLogger.drop_cases()` — xóa bản ghi cũ của đúng những case sắp chạy lại,
     tránh trace có hai bộ record trùng cho cùng một case.

- **Cách xác minh sau khi sửa:** Chạy lại 7 case bị ảnh hưởng, rồi đếm:
  ```
  trace lines before: 800  →  trace lines after: 800
  cases in trace: 50 | LLM calls: 300 | failures: 0
  confidence distribution: {0.95: 50}
  ```
  Trace giữ nguyên 800 dòng và vẫn đủ 50 case — xác nhận `drop_cases()` xóa đúng bản ghi
  cũ rồi ghi bản mới, không nhân đôi.

- **Điều học được:** Sự cố hạ tầng là phép thử cho thiết kế. Vì số liệu vốn do
  `policy_rules.py` tính, 7 case chạy trong lúc mất mạng vẫn cho output **chính xác 100%**
  — tôi đã kiểm chứng bằng cách recompute từ CSV và so khớp từng field. Chỉ mất phần
  diễn giải của LLM và `confidence` tụt 0,95 → 0,80. Nếu tôi đã chọn phương án "LLM tính
  toàn bộ", 7 case đó đã hỏng hoàn toàn. Bài học thứ hai: một lỗi vận hành thường lộ ra
  giả định sai trong code (ở đây là "mỗi lần chạy luôn là chạy đủ 50 case").

## 7. Hiểu biết về luồng end-to-end

> Ghi chú: 5 câu hỏi trong template gốc nói về Crossref, vector index và retrieval —
> thuộc một lab RAG khác, không áp dụng cho bài Multi-Agent A2A này. Tôi trả lời theo
> các câu tương ứng của bài lab thực tế.

**1. Dữ liệu đi từ CSV Olist đến output như thế nào?**

`input/EC_XXX.json` cung cấp `claimed_order_id`. `data_layer.py` đã nạp sẵn 9 CSV và
index theo `order_id`, `customer_id`, `product_id`, `seller_id`, `customer_unique_id`;
`get_case_bundle()` join tất cả thành một bundle. Coordinator gửi bundle (dạng fact
sheet rút gọn) cho từng domain agent qua `AgentMessage`. `policy_rules.apply_policy()`
tính toàn bộ số liệu. Policy Agent phân loại độc lập và được đối chiếu. Verifier kiểm
tra output. Chỉ khi đó file mới được ghi vào `output/`.

**2. Vì sao mọi agent phải đọc từ cùng một bundle?**

Nếu mỗi agent tự query CSV, hai agent có thể thấy hai phiên bản sự thật khác nhau về
cùng một order — ví dụ Payment Agent tính trên 2 item còn Order Agent thấy 3 item. Output
sẽ tự mâu thuẫn mà không có lỗi nào được ném ra. Một bundle duy nhất loại bỏ hẳn lớp bug này.

**3. Verifier khác Audit ở điểm nào?**

Verifier chạy **trong** pipeline, trước khi ghi file, và dùng chung code với hệ thống.
Audit chạy **sau**, độc lập, tự nạp lại CSV và tự suy ra kỳ vọng. Nếu verifier có bug thì
nó không tự phát hiện được — audit thì có. Hai lớp này cố tình không dùng chung code.

**4. Vì sao số liệu do code tính chứ không phải LLM?**

Vì 90% trọng số điểm nằm ở các con số và ID kiểm chứng được (delivery 15%, payment 15%,
entities 15%, context 15%, root cause/evidence 15%, financial 10%). Model ≤10B sai số học
đủ thường xuyên để không thể đặt cược. LLM vẫn ra quyết định thật ở Policy Agent, nhưng
quyết định đó được đối chiếu chứ không được tin mù quáng.

**5. Dựa vào artifact và metric nào để kết luận hệ thống chạy đúng?**

Bốn nguồn: (a) `Verifier: all cases passed.` — gate trong pipeline; (b)
`python src/audit_outputs.py` → `Problems: 0` — kiểm chứng độc lập bằng recompute từ CSV;
(c) `trace.jsonl` với `usage.total_tokens` trên từng `agent_step` — bằng chứng agent thật
sự gọi model chứ không echo kết quả code; (d) EC_002 trong output khớp gần như từng con số
với ví dụ mẫu ở README (`delivery_variance_hours: 87.39`, `handoff_variance_hours: 1.04`,
`expected_total_brl: 212.27`) — một điểm neo bên ngoài mà tôi không hề tối ưu hướng tới.

## 8. Cam kết của thành viên

Đánh dấu sau khi tự kiểm tra:

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi "đã chạy thành công" cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Dương Văn Kiên
**Ngày xác nhận:** 2026-08-05
