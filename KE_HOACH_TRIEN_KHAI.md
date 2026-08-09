# Kế hoạch triển khai tra cứu phương tiện qua Telegram

## 1. Mục tiêu và nguyên tắc nghiệm thu

Xây dựng ứng dụng dùng một tài khoản `app.vr.org.vn` để tra cứu nhiều biển số và trả đúng ba thông tin qua Telegram:

- Loại phương tiện.
- Thương hiệu/Nhãn hiệu.
- Thời hạn kiểm định mới nhất.

Quy tắc thực hiện:

- Phase 1 dùng CAPTCHA nhập tay. Phase 2 đánh giá model miễn phí, chuyển model `.pt` sang ONNX để nhận dạng tự động; nếu model không đạt ngưỡng hoặc độ tin cậy thấp thì bắt buộc quay về nhập tay bởi admin.
- Chỉ Telegram user đã được admin cấp quyền mới được tra cứu.
- Admin Telegram được khai báo trong `.env` và tự động tạo/cập nhật thành `ADMIN + ACTIVE` trong DB khi ứng dụng khởi động.
- Mỗi phase phải hoàn thành test tự động và được chủ dự án trực tiếp nghiệm thu `PASS` trước khi làm phase kế tiếp.
- Chỉ triển khai đúng nhu cầu hiện tại: một tài khoản nguồn, một bot, SQLite, không web admin, không Redis, không microservice.

## 2. Luồng đã xác nhận từ HAR

HAR hiện có 9 request và cho thấy website dùng ASP.NET WebForms.

### 2.1. Đăng nhập

Tài khoản test thực tế phải được cấu hình bằng `VR_USERNAME` và `VR_PASSWORD` trong `.env`; không ghi username/password trực tiếp trong Markdown, source, test hoặc log.
1. `GET /ptpublicweb/Login.aspx` để lấy form ban đầu.
2. Parse đúng ba hidden field mới nhất:
   - `__VIEWSTATE`
   - `__VIEWSTATEGENERATOR`
   - `__EVENTVALIDATION`
3. Parse đường dẫn ảnh từ `#captchaImage`, tải ảnh và yêu cầu admin nhập tay.
4. Nếu admin yêu cầu ảnh khác, POST form với `ImaRefresh.x` và `ImaRefresh.y`, sau đó lấy lại hidden field và ảnh mới.
5. POST đăng nhập bằng username, password, CAPTCHA và hidden field hiện tại.
6. Kết quả:
   - Thành công: HTTP `302`, chuyển tới `/ptpublicweb/ThongTinPT.aspx`.
   - CAPTCHA sai: HTTP `200`, lỗi nằm tại `#lblErrMsg`; lấy lại state/CAPTCHA mới.
   - Sai tài khoản, hết phiên hoặc website đổi cấu trúc: phân loại thành lỗi riêng, không retry vô hạn.

### 2.2. Tra cứu một biển số

Quy tắc tạo candidate:

- Input chưa có đuôi `T/V`: tra cứu độc lập `<biển_số>T` và `<biển_số>V`, trả mọi candidate có dữ liệu.
- Input đã có đuôi `T` hoặc `V`: chỉ tra cứu đúng input một lần.
- Không candidate nào có dữ liệu: trả `NOT_FOUND`.
- Nếu cả hai candidate đều có dữ liệu: trả cả hai kết quả, không tự loại bỏ một kết quả.

1. Luôn `GET /ptpublicweb/ThongTinPT.aspx` trước mỗi biển số để lấy WebForms state riêng.
2. POST form với `txtBienDK`, `Button1` và hidden field vừa lấy.
3. Kết quả:
   - Sai định dạng/không có dữ liệu: đọc `#lblErrMsg` và trả thông báo phù hợp.
   - Thành công: parse HTML kết quả.
   - Nếu response quay về trang login: đánh dấu phiên hết hạn và chuyển sang luồng nhập CAPTCHA bởi admin.
4. Mapping kết quả:
   - `#txtLoaiPT` → loại phương tiện.
   - `#txtNhanHieu` → thương hiệu/nhãn hiệu.
   - `#DGKiemDinh` → tìm cột có tiêu đề “Thời hạn KĐ”, parse toàn bộ dòng và chọn ngày hợp lệ lớn nhất.
5. Sau kết quả thành công, GET lại trang tra cứu cho biển số tiếp theo; không tái sử dụng state của response trước.

### 2.3. Luồng tổng thể

```text
Khởi động
  -> đọc .env, migrate DB, seed admin
  -> đăng nhập nguồn bằng CAPTCHA tay
  -> trạng thái READY

Telegram user gửi biển số
  -> kiểm tra ACTIVE
  -> chuẩn hóa đầu vào
  -> đưa vào hàng đợi giới hạn
  -> worker GET form mới + POST biển số
  -> parse 3 trường
  -> ghi lịch sử
  -> trả đúng người yêu cầu

Nếu phiên hết hạn
  -> tạm dừng job nguồn
  -> gửi CAPTCHA riêng cho admin
  -> admin nhập CAPTCHA
  -> đăng nhập lại
  -> tiếp tục job còn hợp lệ
```

## 3. Cấu trúc source MVC tối thiểu

```text
src/app/
  config.py
  database.py
  main.py

  models/
    user.py
    lookup.py

  views/
    script_view.py
    telegram_view.py

  controllers/
    auth_controller.py
    lookup_controller.py
    telegram_controller.py

  services/
    webforms_client.py
    vr_parser.py
    captcha_service.py
    worker_service.py

tests/
  fixtures/sanitized/
  models/
  views/
  controllers/
  services/

scripts/
  sanitize_har.py
  manual_login.py
  lookup_once.py
  stability_test.py

.env.example
.gitignore
pyproject.toml
README.md
```

Quy ước MVC:

- `models`: dữ liệu và trạng thái DB; không gọi Telegram hoặc website.
- `views`: hiển thị/định dạng cho script test Python và Telegram; không chứa nghiệp vụ tra cứu.
- `controllers`: nhận input, kiểm tra quyền và điều phối model/service/view.
- `services`: tích hợp website, parser, CAPTCHA và worker; không định dạng message Telegram.

Tài liệu chi tiết:

- [Phase 1](docs/PHASE_1.md)
- [Phase 2](docs/PHASE_2.md)
- [Phase 3](docs/PHASE_3.md)

Stack tối thiểu: Python, HTTP client có session, HTML parser, SQLite, Telegram Bot API library, ONNX Runtime ở Phase 2 và pytest. Dependency sẽ được pin phiên bản khi bắt đầu từng phase.

## 4. Database tối thiểu

Chỉ dùng hai bảng nghiệp vụ:

### `users`

- `id`
- `telegram_user_id` — unique
- `telegram_username`
- `role` — `ADMIN` hoặc `USER`
- `status` — `PENDING`, `ACTIVE`, `BLOCKED`
- `created_by`
- `created_at`, `updated_at`

### `lookups`

- `id`
- `user_id`
- `input_plate`
- `queried_plate`
- `status` — `QUEUED`, `RUNNING`, `SUCCESS`, `INVALID`, `NOT_FOUND`, `ERROR`
- `vehicle_type`
- `brand`
- `inspection_expiry`
- `error_code`
- `duration_ms`
- `created_at`, `finished_at`

Không lưu password nguồn, bot token, CAPTCHA hoặc cookie trong DB. Credential chỉ đọc từ `.env`; session chỉ giữ trong bộ nhớ.

## 5. Phase 1 — Base, DB, parser và CAPTCHA tay

**Trạng thái 09/08/2026:** source và 94 test tự động đã hoàn thành; UAT live chưa ký `PASS`, vì vậy chưa chuyển Phase 2. Checklist ký chính thức nằm tại [docs/PHASE_1.md](docs/PHASE_1.md).

### Phạm vi thực hiện

- Tạo cấu trúc source, cấu hình `.env`, logging có che bí mật và SQLite migration.
- Seed admin từ `TELEGRAM_ADMIN_IDS`; Phase 1 chỉ kiểm tra DB, chưa kết nối bot.
- Tạo script làm sạch HAR; tuyệt đối không dùng HAR gốc làm test fixture.
- Viết `webforms_client` cho login, refresh CAPTCHA và tra cứu tuần tự.
- Viết parser cho ba trường yêu cầu và sửa lỗi encoding tiếng Việt.
- Viết các script Python để nhập CAPTCHA tay, tra cứu một biển số và chạy danh sách biển số tuần tự; không xây CLI command framework.
- Phân loại tối thiểu: CAPTCHA sai, đăng nhập sai, biển số sai định dạng, không có dữ liệu, timeout, hết phiên, HTML thay đổi.

### Test tự động bắt buộc

- Hidden field của request sau luôn lấy từ response ngay trước đó và chỉ URL-encode một lần.
- Parser đọc đúng ba trường từ fixture đã làm sạch.
- Bảng kiểm định có một dòng, nhiều dòng, ngày lỗi hoặc không có dòng.
- HTML lỗi trả đúng mã lỗi, không bị hiểu nhầm thành kết quả thành công.
- Parser xử lý đúng tiếng Việt dù meta/header encoding không nhất quán.
- Input không có đuôi tạo đúng hai candidate `T/V`; input đã có đuôi chỉ tạo một candidate.
- Admin được seed idempotent: chạy khởi động nhiều lần không tạo trùng.
- Log không chứa password, CAPTCHA, bot token hoặc HTML gốc.

### Nghiệm thu Phase 1 do chủ dự án thực hiện

Thực hiện và ký P1-UAT-01 đến P1-UAT-10 theo [docs/PHASE_1.md](docs/PHASE_1.md). Danh sách này bao gồm DB/admin, CAPTCHA sai và đúng, candidate `T/V`, input sai, `NOT_FOUND`, đối chiếu năm kết quả, stability 10–20 input và toàn bộ test tự động.

**Cổng Phase 1:** Chỉ chuyển Phase 2 khi chủ dự án ghi `PASS` cho toàn bộ P1-UAT-01 đến P1-UAT-10.

```text
Nghiệm thu Phase 1: PASS / FAIL
Người nghiệm thu:
Ngày:
Ghi chú lỗi cần sửa:
```

## 6. Phase 2 — Worker đa luồng và Telegram bot

### Phạm vi thực hiện

- Kết nối bot bằng `TELEGRAM_BOT_TOKEN` trong `.env`, chạy private chat.
- Đánh giá model CAPTCHA miễn phí; chỉ tích hợp model có giấy phép sử dụng rõ ràng.
- Chuyển model `.pt` được chọn sang ONNX và chạy bằng ONNX Runtime.
- Hỗ trợ `CAPTCHA_MODE=manual|auto`; chế độ `auto` luôn có fallback nhập tay bởi admin.
- User mới gửi `/start` được tạo ở trạng thái `PENDING`.
- Lệnh admin tối thiểu:
  - `/approve <telegram_id>`
  - `/revoke <telegram_id>`
  - `/block <telegram_id>`
  - `/users`
  - `/status`
  - `/login`
  - `/captcha <mã>`
  - `/refresh_captcha`
- User `ACTIVE` tra cứu bằng `/tracuu <biển_số>` hoặc gửi trực tiếp biển số.
- Dùng hàng đợi và `ThreadPoolExecutor` giới hạn; mặc định bắt đầu với hai worker.
- Mỗi worker có HTTP client và WebForms state riêng. Login/refresh CAPTCHA dùng một lock chung.
- Có rate limit đơn giản theo user và toàn hệ thống; không Redis.
- Nếu test live cho thấy một tài khoản không chịu được request song song, vẫn nhận nhiều job Telegram nhưng tuần tự hóa phần gọi website.

### Test tự động bắt buộc

- User `PENDING/BLOCKED` không gọi được lookup service.
- Admin approve/revoke/block đúng user và không thể vô hiệu admin cuối cùng.
- Hai worker không dùng chung `__VIEWSTATE` và không trả chéo kết quả.
- Hai update Telegram trùng nhau không tạo hai job giống nhau.
- Bot chỉ gửi CAPTCHA cho admin.
- Model ONNX cho kết quả đúng toàn chuỗi trên tập CAPTCHA test độc lập; kết quả độ tin cậy thấp phải chuyển sang nhập tay.
- Khi phiên hết hạn, job dừng chờ đăng nhập lại; không retry vòng lặp.
- Restart bot vẫn giữ nguyên quyền user trong DB.

### Nghiệm thu Phase 2 do chủ dự án thực hiện

| ID | Thao tác nghiệm thu | Kết quả bắt buộc |
|---|---|---|
| P2-01 | User chưa duyệt nhắn bot và gửi biển số | Bot từ chối tra cứu, tạo user `PENDING` |
| P2-02 | Admin dùng `/approve` | User chuyển `ACTIVE` và dùng được ngay |
| P2-03 | User tra cứu bằng lệnh và bằng tin nhắn biển số trực tiếp | Hai cách đều trả đúng ba trường |
| P2-04 | Admin dùng `/revoke` hoặc `/block` | User bị từ chối ngay ở lần tiếp theo |
| P2-05 | Hai user gửi tổng cộng 5–10 biển số gần như đồng thời | Không mất job, không trả nhầm user/biển số, DB đúng trạng thái |
| P2-06 | Kiểm tra CAPTCHA tự động, CAPTCHA độ tin cậy thấp và làm hết hạn phiên | Model tự xử lý khi đủ tin cậy; trường hợp còn lại chỉ admin nhận CAPTCHA và hệ thống tiếp tục sau khi nhập đúng |
| P2-07 | Restart bot | Quyền user còn nguyên, admin vẫn `ACTIVE` |
| P2-08 | Kiểm tra log và chạy toàn bộ test | Không lộ bí mật; tất cả test pass |

**Cổng Phase 2:** Chỉ chuyển Phase 3 khi chủ dự án ghi `PASS` cho P2-01 đến P2-08.

```text
Nghiệm thu Phase 2: PASS / FAIL
Người nghiệm thu:
Ngày:
Ghi chú lỗi cần sửa:
```

## 7. Phase 3 — Rà soát lỗi và hoàn thiện vận hành

### Phạm vi thực hiện

- Rà toàn bộ state machine login, CAPTCHA, lookup và Telegram authorization.
- Thêm timeout; retry có giới hạn chỉ cho lỗi mạng/HTTP tạm thời.
- Khi website đổi HTML hoặc thiếu selector: dừng parse, ghi lỗi rõ ràng, không trả dữ liệu sai.
- Chống spam bằng giới hạn hàng đợi và thời gian tối thiểu giữa hai yêu cầu.
- Chuẩn hóa thông báo Telegram ngắn gọn, không lộ lỗi kỹ thuật hoặc credential.
- Bổ sung cleanup CAPTCHA tạm, backup DB, hướng dẫn cài đặt/chạy/restart trong README.
- Chạy test hồi quy và stability test cuối; không bổ sung tính năng ngoài phạm vi.

### Test tự động bắt buộc

- Timeout, mất mạng, HTTP 5xx và response rỗng.
- Response quay về trang login giữa lúc tra cứu.
- Website thiếu một hoặc cả ba trường bắt buộc.
- DB tạm khóa hoặc ghi lỗi không làm bot crash.
- Queue đầy trả thông báo bận, không nhận job vô hạn.
- Log redaction cho tất cả nhánh lỗi.
- Test hồi quy toàn bộ Phase 1 và Phase 2.

### Nghiệm thu Phase 3 do chủ dự án thực hiện

| ID | Thao tác nghiệm thu | Kết quả bắt buộc |
|---|---|---|
| P3-01 | Chạy end-to-end với danh sách hợp lệ, sai định dạng và không có dữ liệu | Mọi trường hợp trả đúng loại kết quả, không crash |
| P3-02 | Ngắt mạng tạm thời rồi bật lại | Bot báo lỗi ngắn gọn và phục hồi ở yêu cầu sau |
| P3-03 | Restart ứng dụng/Windows | Bot và DB hoạt động lại theo README; quyền user còn nguyên |
| P3-04 | Gửi nhiều yêu cầu vượt giới hạn | Bot báo bận/rate limit, không làm treo worker |
| P3-05 | Đối chiếu ngẫu nhiên ít nhất 5 kết quả với website | Cả ba trường khớp hoàn toàn |
| P3-06 | Kiểm tra `.env`, DB, log, fixture và Git status | Không có password, token, CAPTCHA, cookie hoặc HAR gốc bị commit |
| P3-07 | Chạy toàn bộ test và stability test cuối | Tất cả test pass, không có job kẹt ở `RUNNING` |
| P3-08 | Đọc và làm theo README trên môi trường sạch | Có thể cài đặt, cấu hình và vận hành đúng hướng dẫn |

**Cổng hoàn thành:** Chỉ bàn giao khi chủ dự án ghi `PASS` cho P3-01 đến P3-08.

```text
Nghiệm thu Phase 3: PASS / FAIL
Người nghiệm thu:
Ngày:
Ghi chú lỗi cần sửa:
```

## 8. Ghi chú bắt buộc khi triển khai

- HAR gốc chứa dữ liệu nhạy cảm; thêm `*.har`, `.env`, DB và ảnh CAPTCHA vào `.gitignore` ngay từ Phase 1.
- Nên đổi mật khẩu tài khoản nguồn vì mật khẩu xuất hiện trong HAR.
- Chuẩn hóa biển số bằng `trim + uppercase`, sau đó áp dụng đúng quy tắc candidate `T/V`; không tự thêm quy tắc định dạng khác khi chưa có test xác nhận.
- HAR không có cookie/`Set-Cookie`; phải kiểm chứng live trước khi kết luận phiên đăng nhập có thể chia sẻ giữa các worker.
- Không dùng chung HTTP session hoặc WebForms hidden field giữa các thread.
- Không log raw request body hoặc raw response HTML.
- Chỉ trả ba trường đã yêu cầu; không trả số máy, số khung hoặc số tem chứng nhận.
- Không bắt đầu phase kế tiếp khi checklist nghiệm thu hiện tại còn mục `FAIL`.
