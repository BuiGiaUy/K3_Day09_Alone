# Báo cáo vai trò thành viên — Day 9: Multi-Agent A2A

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
| --- | --- |
| Họ và tên | Bùi Gia Uy |
| MSSV | 01867 |
| Khóa/Lớp | K3 |
| Vai trò chính | AI Engineer — thiết kế và triển khai hệ thống Multi-Agent |
| Ngày hoàn thành | 2026-08-05 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| --- | --- | --- | --- | --- |
| Điều phối luồng multi-agent | `dispute_resolution/coordinator.py`, `CoordinatorAgent.process()` | `CaseRequest`, repository đã index | Candidate output, trace handoff, kết quả đã xác minh | Hoàn thành |
| Agent nghiệp vụ | `dispute_resolution/agents.py` | Order, item, payment và các typed finding | Kết quả điều tra, quyết định chính sách, kết quả verifier | Hoàn thành |
| Data contract và truy xuất dữ liệu | `models.py`, `repository.py` | 50 JSON đầu vào và các CSV Olist | Dataclass bất biến và index dữ liệu chỉ đọc | Hoàn thành |
| Áp dụng EC_POLICY_V1 | `PolicyAgent.handle()` | Kết quả OrderSeller, Payment và Delivery | Issue, root cause, responsible party, refund và action | Hoàn thành |
| Kiểm thử và artifact | `tests/test_system.py`, `output/`, `logging/` | Source code và 50 case chính thức | 50 output JSON, 500 trace event, metadata và test report | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --- | --- | --- |
| Tích hợp và tài liệu hóa | Toàn bộ pipeline | Hoàn thiện `architecture.md`, hướng dẫn chạy và sơ đồ Mermaid |
| Audit output và evidence | Verifier/Policy | Evidence được tạo theo từng loại issue, chỉ dùng ID có thể dựng lại từ CSV |
| Chuẩn bị artifact nộp bài | Output và logging | Sinh đủ 50 JSON, `trace.jsonl`, `metadata.json` và `output.zip` |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --- | --- | --- | --- |
| Xây dựng 6 agent tách biệt | `dispute_resolution/agents.py`, `coordinator.py` | Coordinator, OrderSeller, Payment, Delivery, Policy và Verifier Agent | Kiểm tra typed handoff trong source và `logging/trace.jsonl` |
| Xử lý toàn bộ case | `input/`, `output/` | 50/50 case hợp lệ | `python -B -m dispute_resolution --validate-only` |
| Áp dụng đúng thứ tự policy | `PolicyAgent.handle()` | Đủ 6 nhánh EC_POLICY_V1, không có case unmatched | `PolicyTests.test_all_six_policy_branches` |
| Kiểm tra schema và tài chính | `VerifierAgent.handle()` | Phát hiện enum, ID, evidence, refund hoặc array limit sai | Các test `test_verifier_rejects_*` |
| Đảm bảo tính tái lập | `coordinator.py`, `trace.jsonl` | Kết quả và trace có thứ tự ổn định, không dùng random/LLM | Chạy pipeline lặp lại và đối chiếu artifact |

Artifact cụ thể được bàn giao là 50 file `EC_001.json` đến `EC_050.json`. Phân bố kết quả thực tế gồm 8 `canceled_order_paid`, 8 `unavailable_order_paid`, 8 `late_delivery_seller`, 8 `late_delivery_logistics`, 9 `valid_split_payment` và 9 `unsupported_late_claim`. Lần chạy chính thức tạo 500 sự kiện handoff hợp lệ trong `logging/trace.jsonl`.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Nội dung khiếu nại của khách hàng không đủ để kết luận hoàn tiền. Hệ thống phải dùng duy nhất `claimed_order_id` để truy xuất dữ liệu có thể kiểm chứng, kết hợp trạng thái đơn hàng, item, seller, thời điểm giao vận và payment. Kết quả chỉ được ghi khi đúng schema, đúng EC_POLICY_V1 và mọi evidence ID đều tồn tại trong dữ liệu.

### Cách triển khai

Pipeline đọc trước 50 input để lấy tập order ID cần xử lý, sau đó quét các CSV liên quan và tạo index chỉ đọc. Cách này tránh việc mỗi agent phải đọc lại toàn bộ dataset cho từng case.

Các agent trao đổi bằng frozen dataclass thay vì đoạn văn tự do:

1. `CoordinatorAgent` gửi `OrderSellerTask` và `PaymentTask`.
2. `OrderSellerAgent` tính item total, freight total và trạng thái seller handoff theo từng item.
3. `PaymentAgent` dùng `Decimal` để tính payment total, phát hiện split payment và đối soát với sai số tối đa 0.10 BRL.
4. `DeliveryAgent` so sánh ngày giao thực tế với ngày dự kiến; timestamp thiếu được giữ là `None`, không bị hiểu nhầm là giao đúng hạn.
5. `PolicyAgent` áp dụng sáu quy tắc theo đúng thứ tự ưu tiên của EC_POLICY_V1.
6. `VerifierAgent` dựng lại kết quả mong đợi từ dữ liệu nguồn, kiểm tra schema, enum, giới hạn mảng, evidence, responsible party và số tiền trước khi cho phép ghi file.

Mọi phép tính tiền dùng `Decimal` và chỉ chuyển sang JSON number sau khi làm tròn hai chữ số. Evidence được tạo riêng theo loại issue để tránh đưa record có thật nhưng không liên quan trực tiếp đến kết luận.

### Input, output và contract

| Thành phần | Mô tả |
| --- | --- |
| Input | `EC_001.json` đến `EC_050.json`, gồm `case_id`, `opened_at`, `customer_request.claimed_order_id` và `policy_version` |
| Dữ liệu nguồn | Orders, order items, payments, customers, sellers và products trong bộ CSV Olist |
| Handoff | Frozen dataclass như `OrderSellerFinding`, `PaymentFinding`, `DeliveryFinding`, `PolicyDecision` và `VerificationResult` |
| Output | JSON đúng schema chính thức, kèm issue, entity, root cause, evidence, financial resolution và action |
| Module phụ thuộc | `constants.py`, `models.py`, `repository.py`, `agents.py` |
| Module sử dụng output | `CoordinatorAgent`, `VerifierAgent`, CLI và bộ test tích hợp |
| Điều kiện lỗi cần xử lý | Input sai schema, policy không hỗ trợ, order không tồn tại, timestamp/số tiền sai định dạng, không rule nào match hoặc verifier từ chối |

### Cách xác minh

```bash
python -B -m unittest discover -s tests -v
python -B -m dispute_resolution --validate-only
```

- **Kết quả mong đợi:** Toàn bộ unit/integration test pass; 50 case được xác minh; không có output sai schema hoặc evidence giả.
- **Kết quả thực tế:** 11 test pass; 50 case hợp lệ; phân bố issue là `8/8/8/8/9/9`; tạo 500 trace event.
- **Artifact/log:** `output/`, `logging/trace.jsonl`, `logging/metadata.json`, `architecture.md`; không chứa API key hoặc secret.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Đề bài cho phép model tối đa 10B nhưng toàn bộ điều kiện ra quyết định đã được mô tả bằng dữ liệu cấu trúc và business rule xác định.
- **Các phương án đã cân nhắc:** (1) Gọi LLM cho từng agent; (2) dùng Python component deterministic và chỉ khai báo model tham chiếu tương thích.
- **Phương án đã chọn:** Dùng sáu Python agent deterministic; khai báo `qwen-qwen3-8b` 8B là compatible reference model và đặt `MODEL_INVOCATION_ENABLED = False`.
- **Lý do:** Không gọi LLM giúp loại bỏ hallucination, giảm chi phí và độ trễ, không cần API key, đồng thời cho kết quả có thể tái lập hoàn toàn. Agent vẫn có trách nhiệm, computation và typed handoff tách biệt nên đáp ứng kiến trúc multi-agent thực tế.
- **Bằng chứng quyết định phù hợp:** Pipeline xác minh đủ 50 case, 11 test pass, 500 handoff event được ghi và không có case unmatched.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi:** Evidence ban đầu được gom theo một công thức chung nên có thể chứa seller hoặc item tồn tại trong CSV nhưng không trực tiếp hỗ trợ rule đã chọn. Điều này làm tăng nguy cơ false positive khi chấm evidence.
- **Bước tái hiện:** So sánh evidence cần thiết của `canceled_order_paid` với `late_delivery_seller`; hai issue cần tập bằng chứng khác nhau.
- **Nguyên nhân gốc:** Hàm dựng evidence chỉ giới hạn số lượng và giữ order/policy ID, chưa xét `primary_issue` và responsible party của `PolicyDecision`.
- **Cách xử lý:** Chuyển `_build_evidence()` sang nhận toàn bộ `PolicyDecision`, tạo evidence theo từng nhóm issue, loại trùng và giới hạn tối đa 10 ID. Đồng thời dùng confidence `1.0` cho kết luận đã được kiểm chứng hoàn toàn thay vì tự đặt tier không có trong policy.
- **Cách xác minh sau khi sửa:** Chạy `python -B -m unittest tests.test_system.DomainAgentTests.test_evidence_is_specific_to_policy_issue -v` và toàn bộ 11 test; tất cả đều pass. Sau đó tái sinh và xác minh đủ 50 output.
- **Điều học được:** Evidence “có tồn tại” chưa đủ; evidence phải vừa reconstructable vừa liên quan trực tiếp đến điều kiện tạo ra quyết định.

## 7. Hiểu biết về luồng end-to-end

1. **Dữ liệu đi từ input đến index như thế nào?** CLI đọc toàn bộ input, kiểm tra tên file, case ID và policy version, sau đó lấy đúng `claimed_order_id`. Repository quét CSV một lần và chỉ giữ các order cùng entity liên quan trong index bất biến.
2. **Các agent phối hợp ra sao?** Coordinator giao task theo domain, nhận typed finding, chuyển kết quả OrderSeller cho Delivery và tổng hợp ba finding để gọi Policy. Mỗi request/response đều tạo một trace event.
3. **Policy được áp dụng thế nào?** Policy Agent kiểm tra lần lượt canceled paid, unavailable paid, late seller, late logistics, split payment và unsupported claim. Nhánh đầu tiên thỏa điều kiện là kết quả duy nhất.
4. **Quality gate nằm ở đâu?** Sau khi Coordinator dựng candidate, Verifier kiểm tra lại toàn bộ contract và dữ liệu nguồn. Candidate không hợp lệ làm cả run thất bại với exit code khác 0 và không được công bố như kết quả đúng.
5. **Khi nào pipeline được xem là thành công?** Khi đủ 50 input tạo đúng 50 output, tất cả output qua verifier, financial/evidence hợp lệ, trace có 500 JSON line và các test policy, boundary, failure mode đều pass.

## 8. Cam kết của thành viên

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi “đã chạy thành công” cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Bùi Gia Uy  
**Ngày xác nhận:** 2026-08-05
