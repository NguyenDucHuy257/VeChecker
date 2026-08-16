# Phase 3 — Rà soát lỗi và hoàn thiện vận hành

## 1. Mục tiêu

Rà soát toàn bộ hệ thống đã Pass Phase 1 và Phase 2, sửa lỗi còn lại, hoàn thiện khả năng phục hồi và tài liệu vận hành. Phase 3 không thêm tính năng nghiệp vụ mới.

## 2. Điều kiện bắt đầu

- Phase 1 và Phase 2 đã được chủ dự án ký `PASS`.
- Có DB test đã chứa admin, user và lịch sử tra cứu.
- Có tập biển số nghiệm thu cuối được phép sử dụng.
- Đã chốt `CAPTCHA_MODE` dùng khi vận hành.

## 3. Phạm vi rà soát theo MVC

### Models

- Constraint và trạng thái `User`, `Lookup` đúng với DB.
- Không có lookup kẹt `RUNNING` sau restart.
- Migration chạy được trên DB mới và DB từ Phase 2.

### Views

- CLI/Telegram chỉ hiển thị thông tin cần thiết.
- Message lỗi ngắn gọn, thống nhất và không lộ chi tiết kỹ thuật.
- Hai candidate cùng có dữ liệu được hiển thị thành hai kết quả tách biệt.

### Controllers

- Mọi đường vào đều kiểm tra quyền trước khi gọi service.
- Update trùng, input lỗi và queue đầy được xử lý một lần.
- Không controller nào gọi DB/HTTP bỏ qua interface đã thiết kế.

### Services

- WebForms state không dùng lại sai request hoặc sai worker.
- Session hết hạn chuyển đúng về login flow.
- CAPTCHA auto giải từng challenge mới cho đến khi login; lỗi model fallback manual.
- Parser fail-closed khi website đổi cấu trúc.

## 4. Ma trận lỗi bắt buộc

| Trường hợp | Xử lý bắt buộc |
|---|---|
| Connect/read timeout | Retry tối đa theo cấu hình, sau đó trả `SOURCE_TIMEOUT` |
| HTTP 5xx | Retry có delay giới hạn; không retry vô hạn |
| HTTP 200 nhưng quay về login | Đánh dấu hết phiên, tạm dừng job và yêu cầu login |
| CAPTCHA auto sai | Lấy challenge mới và tiếp tục giải đến khi login |
| CAPTCHA user sai ba lần | Dừng login flow và yêu cầu user chủ động `/login` lại |
| Biển số sai định dạng | Trả `INVALID`, không retry |
| Không candidate có dữ liệu | Trả `NOT_FOUND` |
| Thiếu selector/bảng đổi cấu trúc | Trả `PARSE_ERROR`, không trả dữ liệu một phần |
| Queue đầy/rate limit | Trả `BUSY` hoặc `RATE_LIMITED` |
| DB đang khóa/ghi lỗi | Rollback transaction, job `ERROR`, bot không crash |
| Telegram gửi update trùng | Bỏ qua update đã xử lý |

## 5. Công việc triển khai

1. Rà lại toàn bộ test và lỗi đã ghi trong nghiệm thu Phase 1/2.
2. Bổ sung timeout cho mọi HTTP request.
3. Bổ sung retry giới hạn cho timeout/HTTP 5xx; không retry lỗi nghiệp vụ.
4. Khôi phục job `RUNNING` thành `ERROR` hoặc `QUEUED` theo trạng thái an toàn khi startup.
5. Giới hạn queue, rate limit và kích thước input.
6. Xóa ảnh CAPTCHA tạm sau thành công, lỗi hoặc shutdown.
7. Kiểm tra redaction của log và nội dung DB.
8. Tạo backup/restore SQLite đơn giản.
9. Hoàn thiện README cài đặt, `.env`, chạy, restart và xử lý lỗi.
10. Chạy test hồi quy và stability test cuối.

## 6. Test tự động

- Toàn bộ test Phase 1 và Phase 2 phải tiếp tục pass.
- Timeout connect/read, HTTP 5xx và response rỗng.
- Session hết hạn trước và giữa lookup.
- HTML thiếu từng selector bắt buộc.
- Bảng kiểm định thay đổi thứ tự cột.
- ONNX inference lỗi hoặc model file thiếu.
- DB rollback khi insert/update lỗi.
- Khởi động lại khi DB có job `RUNNING`.
- Queue đầy và rate limit theo user.
- Telegram update trùng.
- Log redaction trên mọi nhánh exception.

Lệnh kiểm tra dự kiến:

```powershell
pytest -q
python scripts/stability_test.py --input <FILE_TEST> --delay 2
```

## 7. Nghiệm thu của chủ dự án

| ID | Thao tác | Kết quả bắt buộc |
|---|---|---|
| P3-UAT-01 | Chạy end-to-end với input hợp lệ, sai định dạng và không có dữ liệu | Phân loại đúng, bot không crash |
| P3-UAT-02 | Đối chiếu ngẫu nhiên ít nhất 5 kết quả với website | Khớp hoàn toàn ba trường yêu cầu |
| P3-UAT-03 | Ngắt mạng tạm thời rồi bật lại | Bot báo lỗi đúng và phục hồi ở yêu cầu sau |
| P3-UAT-04 | Restart ứng dụng khi đang có job | Không còn job kẹt `RUNNING`, quyền user còn nguyên |
| P3-UAT-05 | Gửi yêu cầu vượt queue/rate limit | Bot báo bận/giới hạn, worker không treo |
| P3-UAT-06 | Làm phiên hết hạn và kiểm tra CAPTCHA mode đã chọn | Login lại đúng luồng auto; mỗi challenge chỉ inference một lần |
| P3-UAT-07 | Kiểm tra input có/không có đuôi `T/V` | Số lần gọi và kết quả đúng quy tắc candidate |
| P3-UAT-08 | Kiểm tra `.env`, DB, log, fixture và Git | Không có credential, token, CAPTCHA, cookie hoặc HAR gốc bị commit |
| P3-UAT-09 | Cài và chạy theo README trên môi trường sạch | Khởi động, migrate, seed admin và tra cứu thành công |
| P3-UAT-10 | Chạy toàn bộ test và stability test cuối | Tất cả test pass, không trộn dữ liệu hoặc kẹt job |

## 8. Sản phẩm bàn giao

- Source MVC hoàn chỉnh.
- DB migration và hướng dẫn backup/restore.
- `.env.example`, `.gitignore`, README vận hành.
- Bộ test và báo cáo test cuối.
- Danh sách error code/message.
- Biên bản nghiệm thu ba phase.

Không bàn giao nếu còn lỗi làm sai kết quả, lộ bí mật, sai quyền user hoặc trộn dữ liệu giữa các request.

## 9. Trạng thái triển khai kỹ thuật 16/08/2026

- Retry timeout/network/HTTP 5xx đã cấu hình hóa và dùng form WebForms mới mỗi lượt.
- Startup recovery đã kết thúc an toàn lookup/update dở dang.
- Migration v3 thêm constraint trạng thái ở tầng SQLite.
- Input Telegram giới hạn 128 ký tự; queue và per-user rate limit giữ nguyên.
- CAPTCHA tạm Phase 1 được dọn cả startup, sau nhập và shutdown; Telegram dùng bytes.
- Mỗi Telegram user có source account/client/cookie/lock riêng trong RAM; `/logout`
  đóng session, credential messages được xóa ngay qua Telegram API.
- Backup/restore SQLite cùng integrity check nằm ở `scripts/database_backup.py`.
- Runbook/error code nằm trong `docs/OPERATIONS.md`.
- Xác minh cuối: **185 passed**, `compileall` pass, `pip check` không có dependency lỗi.
- DB vận hành đã backup, migrate schema v3 và đạt `PRAGMA integrity_check=ok`;
  không có lookup/update dở dang cần recovery tại thời điểm migrate.

Các UAT có website/Telegram thật vẫn cần chủ dự án thực hiện; test tự động không
thay thế đối chiếu live P3-UAT-01..10.

```text
PHASE 3: PASS / FAIL
Người nghiệm thu:
Ngày:
Lỗi cần sửa:
```
