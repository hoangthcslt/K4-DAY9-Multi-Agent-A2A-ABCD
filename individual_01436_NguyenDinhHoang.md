# Member Role Report — Day 9: Multi Agent A2A

## 1. Thông tin cá nhân

| Thông tin       | Nội dung                  |
| --------------- | ------------------------- |
| Họ và tên       | Nguyễn Đình Hoàng         |
| MSSV            | 01436                     |
| Khóa/Lớp        | K4                        |
| Vai trò chính   | Agent Developer & Architect|
| Ngày hoàn thành | 2026-08-05                |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao   | Trạng thái                            |
| ------------------ | ------------------ | -------------- | ----------------- | ------------------------------------- |
| Coordinator Agent  | `agents/coordinator_agent.py` | Input JSON từ `input/` | Kết quả tổng hợp & Trace dict | Hoàn thành |
| Policy Agent       | `agents/policy_agent.py` | Kết quả từ các sub-agent | Đánh giá chính sách & Refund value | Hoàn thành |
| Verifier Agent     | `agents/verifier_agent.py` | JSON draft từ Policy Agent | JSON chuẩn hóa & danh sách lỗi | Hoàn thành |
| Main Run & Logging | `main.py` | Thư mục `input/` | File output JSON, trace.jsonl, metadata.json | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động                 | Thành viên/module được hỗ trợ | Kết quả                 |
| ------------------------- | ----------------------------- | ----------------------- |
| Xây dựng LLM Client       | LLM API Integration           | Tích hợp Groq SDK cho mô hình llama-3.1-8b-instant hoạt động ổn định |
| Phân tích dữ liệu Olist   | Data Access Layer             | Load dữ liệu từ 9 CSV sang Pandas phục vụ các agent truy xuất song song |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao          | Cách xác minh   |
| --------------------- | --------------------------- | ------------------------- | --------------- |
| Xây dựng luồng điều phối chính | `agents/coordinator_agent.py` | Chạy thành công 50 cases đầu vào | Chạy script `python main.py` không gặp lỗi |
| Áp dụng luật EC_POLICY_V2 | `agents/policy_agent.py` | Tự động tính toán refund và action phù hợp | Kết quả JSON khớp với quy định trong file README.md |
| Xác thực dữ liệu đầu ra | `agents/verifier_agent.py` | Loại bỏ các lỗi schema và giới hạn số phần tử mảng | log của VerifierAgent in ra `valid=True` cho toàn bộ 50 cases |

Nêu một output cụ thể mà phần việc của bạn tạo ra hoặc giúp xác minh:

- File kết quả đầu ra `output/EC_001.json` đến `output/EC_050.json` khớp hoàn toàn với định dạng schema mô tả trong README.md.
- File logs `logging/trace.jsonl` ghi nhận chi tiết thời gian chạy và kết quả của từng agent trong toàn bộ pipeline.
- File `logging/metadata.json` chứa thông tin về cấu hình mô hình `llama-3.1-8b-instant` (8B parameters) và tổng thời gian chạy thực tế (731.2s).

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Trong bài toán xử lý tranh chấp thương mại điện tử Olist, hệ thống cần đối chiếu một lượng lớn dữ liệu phân tán (thông tin đơn hàng, sản phẩm, thanh toán, vận chuyển). Việc dùng duy nhất một prompt LLM để xử lý tất cả sẽ dễ gây ra hiện tượng mất thông tin, hallucination (ảo tưởng), hoặc tính toán sai lệch các khoảng thời gian và tiền tệ. Do đó cần chia nhỏ bài toán thành các Agent chuyên biệt, kết hợp tính toán chính xác từ Pandas (Deterministic) và khả năng tổng hợp lý giải từ LLM (Reasoning).

### Cách triển khai

Hệ thống được thiết kế theo mô hình **Enhanced Hybrid Multi-Agent** gồm 4 Phases chính:
1. **Phase 1 (Dispatch):** Coordinator Agent nhận case và kích hoạt 3 sub-agents hoạt động song song.
2. **Phase 2 (Investigation):** 
   - `InvestigationAgent` kiểm tra thông tin khách hàng, sản phẩm, và categories.
   - `DeliveryAgent` tính toán khoảng lệch thời gian thực tế so với dự kiến.
   - `PaymentAgent` đối soát tổng tiền thanh toán với tổng giá trị đơn hàng + phí vận chuyển.
3. **Phase 3 (Policy Reasoning):** `PolicyAgent` áp dụng bảng luật ưu tiên của `EC_POLICY_V2` để quyết định vấn đề chính, bên chịu trách nhiệm, số tiền hoàn trả, và gọi LLM để đánh giá mức độ tự tin (confidence score).
4. **Phase 4 (Validation):** `VerifierAgent` thực hiện kiểm tra cấu trúc mảng, giới hạn phần tử và tự động sửa các lỗi format trước khi xuất file.

### Input, output và contract

| Thành phần              | Mô tả                                  |
| ----------------------- | -------------------------------------- |
| Input                   | Case ID, claimed_order_id, policy_version |
| Output                  | JSON chứa kết quả đánh giá, đối soát tài chính, bằng chứng (evidence_ids) và hành động tiếp theo |
| Module phụ thuộc        | `data_access.py`, `llm_client.py`      |
| Module sử dụng output   | Coordinator Agent ghi file và chấm điểm hệ thống |
| Điều kiện lỗi cần xử lý | Lỗi format JSON từ LLM, lỗi thiếu trường dữ liệu khi đơn hàng bị canceled hoặc unavailable |

### Cách xác minh

```bash
python main.py
```

- **Kết quả mong đợi:** Hệ thống chạy qua toàn bộ 50 cases từ EC_001.json đến EC_050.json, tự động sinh 50 file JSON kết quả trong thư mục `output/` đạt chuẩn xác thực.
- **Kết quả thực tế:** 50/50 cases chạy thành công, được kiểm chứng hợp lệ bởi VerifierAgent (`valid=True`).
- **Artifact/log:** Thư mục `output/` chứa 50 JSON, và file logs tại `logging/trace.jsonl` và `logging/metadata.json`.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Lựa chọn cách thức tích hợp mô hình ngôn ngữ lớn (LLM) để xác định lỗi chính và tính toán hoàn tiền trong Policy Agent.
- **Các phương án đã cân nhắc:** 
  1. **Phương án 1 (Full LLM):** Cho LLM đọc toàn bộ dữ liệu thô và tự suy ra kết quả bao gồm cả các phép tính số học về giờ và tiền tệ.
  2. **Phương án 2 (Enhanced Hybrid):** Sử dụng Pandas để xử lý các phép toán số học (tổng tiền, tính giờ giao hàng muộn) và áp dụng cấu trúc Rule-Engine cứng cho việc chọn lỗi chính, sau đó dùng LLM để sinh reasoning và đánh giá độ tự tin (Confidence score).
- **Phương án đã chọn:** Phương án 2 (Enhanced Hybrid).
- **Lý do:** Các mô hình LLM cỡ nhỏ (≤10B) như `llama-3.1-8b-instant` rất dễ tính toán sai các con số tài chính hoặc so sánh ngày tháng không chuẩn xác, dẫn đến việc mất điểm đáng tiếc. Việc kết hợp tính toán cứng từ Pandas đảm bảo độ chính xác 100% về mặt dữ liệu, trong khi LLM vẫn phát huy tốt thế mạnh ở phần tổng hợp lập luận.
- **Bằng chứng quyết định phù hợp:** Toàn bộ 50 cases đều đạt kết quả đối soát tài chính và chênh lệch ngày giờ cực kỳ chuẩn xác, không có hiện tượng sai lệch số thập phân hoặc sai định dạng bằng chứng.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** `UnicodeEncodeError: 'charmap' codec can't encode character '\u2705' in position 2: character maps to <undefined>` khi chạy trên môi trường Windows Terminal.
- **Lệnh hoặc bước tái hiện:** Chạy lệnh `python main.py` trên Powershell/CMD mặc định của Windows.
- **Nguyên nhân gốc:** Ký tự emoji như ✅ hoặc ❌ không được hỗ trợ mặc định bởi bộ mã hóa `cp1252` của Windows console khi in ra output bằng hàm `print()`.
- **Cách xử lý:** Thay thế các ký tự emoji này bằng chuỗi ASCII đơn giản như `[OK]` và `[FAIL]`.
- **Cách xác minh sau khi sửa:** Chạy lại `python main.py`, log in ra mượt mà và không còn crash giữa chừng.
- **Điều học được:** Cần lưu ý sự khác biệt về bảng mã console mặc định giữa Windows và Linux/macOS khi viết code in log ra màn hình.

## 7. Hiểu biết về luồng end-to-end

1. **Dữ liệu đi từ Crossref đến vector index như thế nào?**
   Dữ liệu thô từ Crossref API (chứa metadata bài báo khoa học) được thu thập, trích xuất các trường thông tin quan trọng như title, abstract, authors. Sau đó dữ liệu được chuyển đổi thành định dạng văn bản chuẩn (Markdown), thực hiện chia nhỏ thành các đoạn (chunks) có kích thước cố định hoặc dựa trên cấu trúc, tiếp đến được chuyển thành vector đặc trưng (embeddings) qua mô hình Embedding, và cuối cùng lưu trữ vào Vector DB để phục vụ tra cứu.

2. **Evaluation set và ground-truth document IDs dùng để đo retrieval/answer quality ra sao?**
   - **Retrieval Quality:** Hệ thống dùng câu hỏi trong Evaluation set để query. Kết quả top-K tài liệu trả về được đối chiếu với Ground-truth Document IDs để tính toán các metrics như Hit Rate@K, MRR (Mean Reciprocal Rank).
   - **Answer Quality:** Câu trả lời sinh ra bởi LLM dựa trên ngữ cảnh tìm được sẽ được đối chiếu với câu trả lời chuẩn (nếu có) hoặc đánh giá độ liên quan và tính trung thực thông qua các framework đánh giá (ví dụ RAGAS).

3. **Quality checks khác freshness monitoring ở điểm nào trong bài lab?**
   - **Quality checks:** Kiểm tra tính đúng đắn và chuẩn mực của dữ liệu (schema validation, tính nhất quán tài chính, định dạng ID bằng chứng).
   - **Freshness monitoring:** Giám sát tính cập nhật của dữ liệu theo thời gian thực (ngày cập nhật cuối, dữ liệu có bị cũ so với nguồn phát hành hay không).

4. **Vì sao phải dùng cùng test set cho baseline, corrupted và repaired?**
   Để đảm bảo tính nhất quán (consistency) và công bằng trong so sánh. Việc giữ nguyên test set giúp cô lập biến số và đo lường chính xác tác động của việc phá hoại dữ liệu (corrupted) và hiệu quả của các giải pháp sửa chữa (repaired).

5. **Repair được xem là thành công dựa trên artifact và metric nào?**
   Sửa chữa thành công khi các chỉ số chất lượng retrieval (Hit Rate, MRR) và chất lượng trả lời (RAGAS scores) được khôi phục về gần hoặc vượt mức baseline ban đầu, được thể hiện rõ ràng qua bảng so sánh kết quả (artifact report).

## 8. Cam kết của thành viên

Đánh dấu sau khi tự kiểm tra:

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi “đã chạy thành công” cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Nguyễn Đình Hoàng
**Ngày xác nhận:** 2026-08-05

