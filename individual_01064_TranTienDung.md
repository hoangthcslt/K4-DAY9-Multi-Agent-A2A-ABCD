# Member Role Report — Day 9: Multi Agent A2A

## 1. Thông tin cá nhân

| Thông tin       | Nội dung                                                                     |
| --------------- | ----------------------------------------------------------------------------- |
| Họ và tên       | Trần Tiến Dũng                                                                 |
| MSSV            | 2A202601064                                                                    |
| Khóa/Lớp        | K4                                                                             |
| Vai trò chính   | Kiến trúc sư hệ thống multi-agent & tích hợp LLM (toàn bộ pipeline + audit tooling) |
| Ngày hoàn thành | 2026-08-05                                                                     |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| --- | --- | --- | --- | --- |
| Deterministic policy engine (port từ pipeline if/else gốc, không đổi công thức) | `src/policy_rules.py` | `order_id`, `raw_items`, `raw_payments`, `delivery_info`, `related_order_ids` | `apply_policy()` trả `{order, payment, delivery, resolution, evidence_ids}` theo đúng `EC_POLICY_V2` | Hoàn thành |
| LLM-augmented domain agents (mỗi agent 1 lệnh gọi LLM thật + fallback deterministic) | `src/agents/{customer,order_product,payment,delivery,policy}_agent.py` | fact sheet tính sẵn từ `policy_rules`/`data_loader` | `finding` dict (judgement/narrative + `llm_available`); riêng Policy Agent trả thêm `confidence` | Hoàn thành — đã chạy full-batch 50 case với `GROQ_API_KEY` thật, `llm_available: true` cho toàn bộ agent_step, 0 lỗi |
| Agent base scaffolding + Groq LLM client (retry/backoff/JSON-mode) | `src/agents/base.py`, `src/llm_client.py` | `system_prompt`, `user_prompt` | JSON response + usage, hoặc `LLMError` để agent rơi vào `fallback()` | Hoàn thành |
| Trace logger (A2A message + agent step) | `src/trace_logger.py` | `AgentMessage`, dữ liệu từng bước agent | `logging/trace.jsonl` (1 JSON/dòng, ghi đè mỗi lần chạy) | Hoàn thành |
| Coordinator orchestration + entrypoint (cô lập lỗi từng case) | `src/coordinator.py`, `main.py` | `input/EC_xxx.json`, dữ liệu từ `DataLoader` | `output/EC_xxx.json` + `logging/trace.jsonl`; 1 case lỗi không làm crash cả batch | Hoàn thành, đã verify (xem mục 4) |
| Verifier gate: schema Pydantic + business-rule cross-check + array cap | `src/agents/verifier_agent.py` | output dict đã assemble, dữ liệu gốc của order | `(errors, warnings)`; output đã `enforce_limits()` theo giới hạn README mục 6 | Hoàn thành |
| Script audit độc lập trước khi nộp | `audit_outputs.py` | `input/`, `output/`, `data/*.csv` | Báo cáo console: số problem, phân bố `primary_issue`/`case_status` | Hoàn thành — đã chạy, kết quả `Problems: 0`, 50/50 output hợp lệ |
| Sửa mismatch dependency/metadata | `requirements.txt`, `metadata.json`, `.gitignore`, `.env.example` | — | Repo cài đặt/chạy đúng trên môi trường sạch; tên model khớp giữa code và `metadata.json` | Hoàn thành |
| Cập nhật tài liệu kiến trúc cho khớp code thực tế | `architecture.md` | — | Mô tả đúng luồng multi-agent + rules-win pattern đang chạy thật | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --- | --- | --- |
| Đối chiếu kiến trúc với 3 nhánh khác trong nhóm (`2A202601436_NguyenDinhHoang`, `2A202601724_DuongVanKien`, `2A202601909_HoangThiHaHuyen`) để rút ra mẫu thiết kế "LLM cross-check + rules-win" trước khi tự triển khai | Toàn nhóm (tham khảo, không copy nguyên code) | Xác định được pattern an toàn nhất để thêm LLM thật mà không làm sai 50 case đã đúng |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --- | --- | --- | --- |
| Refactor toàn bộ `src/agents.py` (1 file 503 dòng, if/else thuần) thành package `src/agents/` với LLM thật + rules-win | `src/agents/*.py`, `src/coordinator.py` | Multi-agent pipeline có LLM reasoning quan sát được qua trace, không đổi giá trị đã chấm điểm | `python main.py` (fallback mode) chạy hết 50 case, `git diff --stat -- output/` không có thay đổi |
| Fix xung đột đặt tên module/package khiến `main.py` không import được giữa chừng refactor | `src/agents.py` ↔ `src/agents/` | Repo luôn ở trạng thái import được trước khi push | `python -c "import importlib.util; importlib.util.find_spec('src.agents')"` |
| Viết script audit độc lập, tách biệt hoàn toàn với `verifier_agent.py` | `audit_outputs.py` | Công cụ tự kiểm tra `output/` so với CSV gốc trước khi nộp | `python audit_outputs.py` (kết quả kỳ vọng: `Problems: 0`) |

Một output cụ thể mà phần việc của tôi tạo ra:

`logging/trace.jsonl` sau khi chạy `python main.py` — mỗi case có các dòng `event: a2a_message` (handoff Coordinator → từng agent) và `event: agent_step` (agent, model, input, output, duration_ms, usage/error), là bằng chứng runtime cho thấy 6 agent thực sự được gọi tuần tự và trao đổi dữ liệu với nhau, thay vì chỉ được mô tả trong `architecture.md`.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Pipeline gốc (trước khi tôi refactor) tính đúng 50/50 case theo `EC_POLICY_V2`, nhưng toàn bộ quyết định là if/else Python thuần; LLM chỉ được gọi 1 lần cho một con số `confidence` không ảnh hưởng gì đến kết quả (và luôn fallback về hằng số vì chưa cấu hình API key). Điều này không thể hiện đúng tinh thần "multi-agent với LLM reasoning + handoff" mà đề bài yêu cầu, và `architecture.md` cũ mô tả sai so với code thật (tuyên bố "rely entirely on LLM" trong khi code không hề gọi LLM cho reasoning).

### Cách triển khai

Tách logic quyết định (đã đúng) ra `src/policy_rules.py` làm nguồn chân lý duy nhất, giữ **nguyên xi công thức/điều kiện** để không đổi bất kỳ giá trị nào của 50 case đã có. Sau đó bọc mỗi domain agent (Customer/Order-Product/Payment/Delivery/Policy) bằng một lớp `Agent` (`src/agents/base.py`) gọi đúng 1 lần Groq `llama-3.1-8b-instant` trên fact sheet đã tính sẵn. Hàm `validate()` của từng agent luôn ưu tiên giá trị deterministic cho mọi field được chấm điểm — LLM chỉ đóng góp phần narrative và, ở Policy Agent, một classification độc lập dùng làm cross-check để đặt `confidence` (0.95 nếu khớp rule, 0.75 nếu lệch, 0.80 nếu không gọi được LLM). Mọi lệnh gọi và handoff được `TraceLogger` ghi vào `logging/trace.jsonl`. `Coordinator` (`src/coordinator.py`) điều phối toàn bộ luồng và gọi `verifier_agent` (schema + business-rule + array cap, không LLM) trước khi ghi file.

### Input, output và contract

| Thành phần | Mô tả |
| --- | --- |
| Input | `input/EC_xxx.json` (`case_id`, `claimed_order_id`) + `data/*.csv` (9 file Olist) |
| Output | `output/EC_xxx.json` đúng schema README mục 6 + `logging/trace.jsonl` |
| Module phụ thuộc | `src/data_loader.py`, `src/policy_rules.py`, `src/agents/*`, `src/llm_client.py`, `src/trace_logger.py` |
| Module sử dụng output | `audit_outputs.py` (đọc lại `output/` để tự kiểm tra); file zip nộp bài |
| Điều kiện lỗi cần xử lý | `claimed_order_id` không có trong CSV; LLM timeout/lỗi mạng/JSON không hợp lệ → rơi vào `fallback()`; 1 case lỗi bất kỳ không được làm dừng cả 50 case (try/except quanh từng case trong `main.py`) |

### Cách xác minh

```bash
# 1. Chạy toàn bộ 50 case ở chế độ chưa có GROQ_API_KEY (đúng trạng thái ban đầu)
/home/dungtt/miniconda3/envs/lab7/bin/python main.py

# 2. So sánh output mới sinh ra với bản đã có trước khi refactor
git diff --stat -- output/

# 3. Smoke test lệnh gọi LLM thật (sau khi thêm GROQ_API_KEY vào .env)
python -c "
from dotenv import load_dotenv; load_dotenv()
from src.llm_client import call_llm
print(call_llm('You are a test agent. Reply with JSON only.',
                'Reply with JSON: {\"ok\": true, \"message\": \"pong\"}'))
"
```

- **Kết quả mong đợi:** (1) toàn bộ 50 case chạy xong không lỗi; (2) `output/` không đổi field nào ngoại trừ `case_assessment.confidence`; (3) lệnh gọi Groq thật trả JSON hợp lệ.
- **Kết quả thực tế:** Đã xác nhận đầy đủ cả 3, gồm cả lượt chạy full-batch 50 case với `GROQ_API_KEY` thật:
  - `python main.py` (có key thật): 50/50 case chạy xong, `llm_available: true` cho toàn bộ agent_step trong `logging/trace.jsonl` (700 dòng = đúng 14 sự kiện/case), 0 lỗi LLM/agent, 0 case verifier fail.
  - So sánh field-by-field (bỏ qua `confidence`) giữa `output/` mới và bản trước khi thêm LLM thật: **0 case lệch** — chỉ `case_assessment.confidence` đổi (43 case `0.95` vì LLM đồng ý với rule, 7 case `0.75` vì LLM lệch, 0 case `0.80`/no-LLM).
  - `python audit_outputs.py`: `Problems: 0`, đủ 50/50 output, phân bố `primary_issue`/`case_status` hợp lý theo policy.
- **Artifact/log:** `logging/trace.jsonl` (không chứa secret — chỉ chứa facts đã trích xuất và output của LLM).

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Cần thêm LLM reasoning thật cho từng agent (đúng tinh thần multi-agent của đề bài) mà không được làm sai bất kỳ field nào trong 50 case đã tính đúng theo `EC_POLICY_V2`, trong bối cảnh chưa chắc có API key để test đầy đủ trước khi nộp.
- **Các phương án đã cân nhắc:**
  1. Giữ nguyên pure-Python (không có LLM thật) — an toàn tuyệt đối về số liệu nhưng không thể hiện được "multi-agent LLM reasoning".
  2. Để LLM tự quyết định toàn bộ `primary_issue`/refund/actions — thể hiện đúng tinh thần multi-agent nhưng có rủi ro model nhỏ (8B) suy luận sai, phải chạy lại và so khớp toàn bộ 50 case, nguy hiểm nếu gần deadline chấm điểm.
  3. Hybrid "rules-win": mỗi agent gọi LLM thật để narrate/cross-check, nhưng `validate()` luôn lấy giá trị deterministic cho mọi field chấm điểm; LLM chỉ ảnh hưởng `confidence`.
- **Phương án đã chọn:** (3) Hybrid rules-win.
- **Lý do:** Vừa có LLM reasoning thật và quan sát được qua `trace.jsonl` (đúng yêu cầu multi-agent), vừa đảm bảo 0% rủi ro thay đổi các field đã đúng của 50 case — vì `policy_rules.py` là nguồn chân lý duy nhất, độc lập với việc LLM có sẵn sàng hay trả lời đúng hay không.
- **Bằng chứng quyết định phù hợp:** Chạy `main.py` ở chế độ fallback (chưa có key) cho ra `output/` byte-identical với bản trước refactor; gọi Groq thật qua `llm_client.call_llm()` thành công (trả `{"ok": true, "message": "pong"}`).

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** Sau khi tạo package `src/agents/` (chứa `base.py`, `__init__.py`) trong khi file cũ `src/agents.py` vẫn còn tồn tại, `main.py` (`from src.agents import CustomerAgent, ...`) bị `ImportError` vì các class không tồn tại trong `__init__.py` rỗng của package mới.
- **Lệnh hoặc bước tái hiện:**
  ```bash
  python -c "import importlib.util; print(importlib.util.find_spec('src.agents').origin)"
  # -> .../src/agents/__init__.py  (thay vì src/agents.py)
  ```
- **Nguyên nhân gốc:** Python ưu tiên resolve một package (thư mục có `__init__.py`) trước một module file cùng tên trong cùng thư mục cha; hai thứ không thể cùng "hoạt động" dưới tên `src.agents` cùng lúc.
- **Cách xử lý:** Đổi tên file cũ thành `src/agents_legacy.py.bak` (giữ tạm để không mất logic tham chiếu) trong lúc xây `src/agents/` package mới song song; sau khi đã port xong toàn bộ logic sang các file mới và verify output khớp, xoá hẳn file cũ bằng `git rm`.
- **Cách xác minh sau khi sửa:** `python -c "from src.coordinator import Coordinator"` không lỗi; `python main.py` chạy hết 50 case; `output/` không đổi so với bản trước khi refactor.
- **Điều học được:** Không thể có `module.py` và `package/` cùng tên trong cùng thư mục cha trong Python — cần dọn/di chuyển một trong hai *trước* khi bắt đầu migrate, không thể làm song song tại chỗ.

## 7. Hiểu biết về luồng end-to-end

> Lưu ý: 5 câu hỏi gốc trong template (Crossref, vector index, freshness monitoring, baseline/corrupted/repaired...) thuộc về một lab khác (RAG/data-quality), không khớp với lab Multi-Agent E-commerce Dispute Resolution này. Tôi thay bằng 5 câu hỏi tương đương đúng với pipeline thực tế của lab này.

**Câu hỏi tương đương và trả lời:**

1. **Dữ liệu đi từ input JSON đến output JSON như thế nào?** `input/EC_xxx.json` cho `claimed_order_id` → `DataLoader` join 9 CSV Olist (orders/customers/order_items/order_payments/products) theo `order_id`/`customer_id`/`product_id`/`seller_id` → `policy_rules.apply_policy()` tính toàn bộ số liệu/điều kiện deterministic → mỗi domain agent gọi 1 lần LLM cross-check trên facts đó → Policy Agent tổng hợp confidence → Verifier Agent enforce limit + kiểm tra business rule → ghi `output/EC_xxx.json` + `logging/trace.jsonl`.
2. **"Ground truth" ở lab này là gì và dùng để đo cái gì?** Không có tập nhãn riêng — "ground truth" chính là bảng rule `EC_POLICY_V2` trong README, được implement lại độc lập trong `audit_outputs.py` (không tái sử dụng code của `verifier_agent.py`) để tái tạo giá trị kỳ vọng thẳng từ CSV và so khớp với `output/`.
3. **Quality check ở lab này khác gì so với "freshness monitoring"?** Dữ liệu Olist tĩnh (không có khái niệm dữ liệu "cũ/mới"), nên không có freshness check. Quality check ở đây gồm: (a) Verifier Agent — schema/array-cap/evidence tại thời điểm chạy; (b) `audit_outputs.py` — tái tính độc lập từ CSV sau khi đã có `output/`; (c) LLM cross-check ở Policy Agent — tín hiệu agree/disagree phản ánh vào `confidence`, không phải kiểm tra độ mới của dữ liệu.
4. **Vì sao phải dùng cùng 50 input case khi so sánh trước/sau refactor?** Để phép so sánh "output trước khi thêm LLM thật" và "output sau khi thêm LLM thật" là hợp lệ — nếu đổi tập input giữa hai lần chạy thì không thể kết luận khác biệt là do refactor hay do input khác.
5. **Refactor được xem là thành công dựa trên artifact/metric nào?** (a) `git diff --stat -- output/` không cho thấy thay đổi khi chạy ở chế độ fallback (chứng minh logic chấm điểm không đổi); (b) `audit_outputs.py` báo `Problems: 0` khi so khớp `output/` với giá trị tái tính từ CSV; (c) `logging/trace.jsonl` có đủ `a2a_message`/`agent_step` cho cả 6 agent mỗi case, chứng minh handoff thực sự xảy ra.

## 8. Cam kết của thành viên

> Đã tự chạy `python main.py` (với `GROQ_API_KEY` thật) và `python audit_outputs.py`, kết quả khớp đúng như mục 4 mô tả (0 problems, 0 field lệch ngoài `confidence`).

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi "đã chạy thành công" cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Trần Tiến Dũng
**Ngày xác nhận:** 2026-08-05
