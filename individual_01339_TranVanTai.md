# Member Role Report - Day 9: Multi Agent A2A

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
| --- | --- |
| Họ và tên | Trần Văn Tài |
| MSSV | 01339 |
| Khóa/Lớp | K3 |
| Vai trò chính | Xây dựng pipeline multi-agent, policy và kiểm chứng output |
| Ngày hoàn thành | 2026-08-05 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| --- | --- | --- | --- | --- |
| Điều phối multi-agent | `dispute_resolution/coordinator.py` | Case JSON và các typed finding | Candidate output và trace handoff | Hoàn thành |
| Phân tích dữ liệu và áp dụng policy | `dispute_resolution/agents.py` | Order, item, seller, payment và delivery facts | Issue, cause, responsible party, refund và action | Hoàn thành |
| Truy xuất dữ liệu Olist | `dispute_resolution/repository.py` | 50 order ID và các file CSV | Chỉ mục order, item, payment, seller và product | Hoàn thành |
| Kiểm thử và xuất kết quả | `tests/test_system.py`, `output/`, `logging/` | Candidate của 50 case | 50 JSON hợp lệ và 500 trace event | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --- | --- | --- |
| Debug Git và tích hợp thay đổi | Repository nhóm | Giải quyết trạng thái non-fast-forward, giữ lịch sử remote và local |
| Audit chất lượng output | Verifier và policy pipeline | Phát hiện evidence quá rộng, chuyển sang evidence theo từng issue |
| Tài liệu kiến trúc | `architecture.md` | Mô tả agent, quyền truy cập dữ liệu, handoff và verification gate |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --- | --- | --- | --- |
| Cài đặt sáu nhánh `EC_POLICY_V1` theo đúng thứ tự ưu tiên | `PolicyAgent.handle` | Đủ sáu primary issue, cause, party, refund và action | `test_all_six_policy_branches` |
| Tính tổng tiền và đối soát split payment | `PaymentAgent.handle`, `money` | Làm tròn hai chữ số, tolerance 0.10 BRL | `test_payment_tolerance_is_inclusive` |
| Xác định giao trễ và seller bàn giao trễ | `OrderSellerAgent`, `DeliveryAgent` | So sánh timestamp và giữ trạng thái unknown khi thiếu ngày | Các domain-agent test |
| Xây evidence có thể truy ngược về dữ liệu | `_build_evidence` | ID theo order, item, payment, seller và policy | `test_evidence_is_specific_to_policy_issue` |
| Kiểm tra output trước khi publish | `VerifierAgent` | Chặn sai schema, enum, ID, giới hạn và số tiền | Hai verifier tampering test |
| Chạy toàn bộ dữ liệu chính thức | `output/`, `logging/trace.jsonl` | 50 output, sáu nhóm issue và 500 trace event | `python -m dispute_resolution --validate-only` |

Artifact cụ thể là bộ 50 file `output/EC_001.json` đến `output/EC_050.json`. Mỗi file có assessment, affected entities, root cause, evidence, financial resolution và resolution actions. Lần đánh giá gần nhất đạt tổng điểm 95.1646; riêng Evidence tăng từ 86.1305 lên 92.8729 sau khi chuyển từ evidence tổng quát sang evidence theo policy issue.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Mỗi yêu cầu hỗ trợ chỉ cung cấp một `claimed_order_id`, trong khi kết luận cần đối chiếu nhiều nguồn Olist. Pipeline phải xác định đúng trạng thái đơn, thời hạn seller bàn giao, thời điểm giao cho khách, các dòng item, các dòng payment và thứ tự ưu tiên của policy. Output còn phải dùng ID có thể dựng lại từ CSV, không được tạo bằng chứng hoặc transaction không tồn tại.

### Cách triển khai

Repository đọc trước 50 order ID rồi chỉ giữ các record liên quan trong CSV. Coordinator giao typed task cho OrderSeller, Payment và Delivery Agent. Policy Agent nhận các finding bất biến và xét lần lượt sáu quy tắc: canceled, unavailable, seller delay, logistics delay, valid split payment và unsupported late claim.

Tiền được xử lý bằng `Decimal`, làm tròn `ROUND_HALF_UP` ở hai chữ số. Split payment hợp lệ khi có ít nhất hai payment row và chênh lệch với item cộng freight không vượt quá 0.10 BRL. Coordinator chỉ ghi output sau khi Verifier dựng lại entity, evidence và financial values rồi xác nhận candidate hợp lệ.

### Input, output và contract

| Thành phần | Mô tả |
| --- | --- |
| Input | `input/EC_001.json` đến `EC_050.json`, 9 CSV Olist và `EC_POLICY_V1` |
| Output | 50 JSON theo schema đề bài, `logging/trace.jsonl` và `logging/metadata.json` |
| Module phụ thuộc | `repository.py`, `models.py`, `constants.py`, dữ liệu trong `data/` |
| Module sử dụng output | `CoordinatorAgent`, `VerifierAgent`, bộ chấm và file ZIP nộp bài |
| Điều kiện lỗi cần xử lý | Case/order thiếu, CSV sai định dạng, timestamp hoặc amount không hợp lệ, policy không hỗ trợ, evidence giả, vượt giới hạn mảng hoặc refund sai |

### Cách xác minh

```bash
python -m unittest discover -s tests -v
python -m dispute_resolution --validate-only
```

- **Kết quả mong đợi:** Toàn bộ test pass; đủ 50 case, sáu nhóm issue và 500 trace event.
- **Kết quả thực tế:** 11/11 test pass; 50 case hợp lệ; phân bố issue là 8 canceled, 8 unavailable, 8 seller delay, 8 logistics delay, 9 split payment và 9 unsupported claim; 500 trace event.
- **Artifact/log:** `output/`, `logging/trace.jsonl`, `logging/metadata.json`; không chứa secret.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Bài yêu cầu mô hình không quá 10B nhưng quy tắc nghiệp vụ và dữ liệu đều có cấu trúc, cần kết quả tái lập chính xác cho 50 case.
- **Các phương án đã cân nhắc:** Dùng LLM tạo kết luận tự do; dùng LLM kết hợp validator; hoặc dùng các agent Python deterministic trao đổi typed dataclass.
- **Phương án đã chọn:** Pipeline deterministic với sáu agent Python; khai báo `qwen-qwen3-8b` là compatible reference model nhưng không gọi model trong quyết định.
- **Lý do:** Quy tắc hữu hạn phù hợp với code có kiểu, `Decimal` và verifier độc lập theo domain. Cách này giảm hallucination, không cần API key, chi phí chạy thấp và cho kết quả lặp lại.
- **Bằng chứng quyết định phù hợp:** 50/50 case qua validation, 11 test pass và mỗi lần chạy tạo đúng 500 trace event với phân bố issue ổn định.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** Điểm Evidence chỉ đạt 86.1305 dù các evidence ID đều tồn tại trong dữ liệu.
- **Lệnh hoặc bước tái hiện:** Chạy pipeline, nén 50 output và nộp lên bảng chấm; đối chiếu evidence của từng nhóm issue.
- **Nguyên nhân gốc:** Builder cũ đưa nhiều ID liên quan đến order nhưng không trực tiếp hỗ trợ quy tắc đang được áp dụng. Các ID hợp lệ về định dạng vẫn trở thành false positive đối với grader.
- **Cách xử lý:** Xây evidence theo `primary_issue`: canceled/unavailable ưu tiên order, payment và policy; seller delay thêm item và seller vi phạm; logistics, split payment và unsupported claim chỉ giữ các nguồn cần cho điều kiện tương ứng.
- **Cách xác minh sau khi sửa:** Chạy test evidence, toàn bộ test suite và validation 50 case; nộp lại output để so sánh từng tiêu chí.
- **Điều học được:** Evidence cần vừa truy xuất được vừa có tính liên quan. Thêm mọi record tồn tại không đồng nghĩa với bằng chứng tốt và có thể làm giảm precision.

## 7. Hiểu biết về luồng end-to-end

1. Mỗi case JSON cung cấp `claimed_order_id`. Repository dùng ID này để nối order với item, seller, product và payment trong các CSV Olist.
2. Coordinator gửi task cho OrderSeller Agent để lấy trạng thái, item, seller và tổng tiền; gửi task cho Payment Agent để tính payment total và kiểm tra split payment.
3. Delivery Agent so sánh ngày giao thực tế với estimated date và carrier date với shipping limit của từng item.
4. Policy Agent áp dụng sáu quy tắc theo thứ tự ưu tiên để tạo primary issue, cause, responsible party, refund và action.
5. Coordinator ghép candidate output. Verifier kiểm tra schema, enum, giới hạn, ID nguồn, evidence, số tiền và tính nhất quán với policy.
6. Chỉ khi cả 50 case hợp lệ, pipeline mới thay thế các file trong `output/`, tạo metadata và ghi mới 500 event vào trace.
7. Baseline và các phiên bản cải thiện phải chạy trên cùng 50 case. Repair chỉ được coi là tốt khi test/validation vẫn pass và tiêu chí mục tiêu trên grader tăng mà các tiêu chí khác không giảm.

## 8. Cam kết của thành viên

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi "đã chạy thành công" cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Trần Văn Tài 
**Ngày xác nhận:** 2026-08-05
