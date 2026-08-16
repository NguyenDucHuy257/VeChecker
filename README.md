# DKTLE — Phase 3

Ứng dụng MVC dùng một tài khoản `app.vr.org.vn` để tra cứu qua Telegram, kiểm soát quyền bằng admin, xử lý qua hàng đợi worker giới hạn và lưu lịch sử vào SQLite.

## Cấu trúc MVC

- `src/app/models`: `User`, `Lookup` và repository SQLite.
- `src/app/views`: nhập CAPTCHA/biển số và hiển thị ba trường kết quả cho script.
- `src/app/controllers`: điều phối đăng nhập, candidate `T/V`, tra cứu và ghi DB.
- `src/app/services`: HTTP WebForms, parser HTML, CAPTCHA file và error codes.

Phase 2 bổ sung `telegram_controller`, `telegram_view`, Telegram long polling, worker pool có session nguồn riêng và CAPTCHA ONNX có fallback nhập tay.

## Cài đặt trên Windows

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
Copy-Item .env.example .env
```

Điền các giá trị thật vào `.env`:

- `VR_USERNAME`
- `VR_PASSWORD`
- `TELEGRAM_ADMIN_IDS`: một hoặc nhiều numeric ID, cách nhau bằng dấu phẩy.
- `TELEGRAM_BOT_TOKEN`: token lấy từ BotFather; không ghi vào log hoặc Git.
- `CANDIDATE_DELAY_SECONDS=2`: khoảng nghỉ tối thiểu giữa hai candidate `T/V`.
- `STABILITY_INPUT_FILE` và `STABILITY_DELAY_SECONDS`: file đầu vào và khoảng nghỉ của stability test.

Không đưa `.env`, DB, ảnh CAPTCHA, file biển số thật hoặc HAR vào Git.

## Chạy Telegram bot

Model chính thức hiện chạy `CAPTCHA_MODE=auto` với threshold `0.60`. Khi confidence
thấp hoặc website báo sai CAPTCHA, bot lấy challenge mới và giải tiếp; lỗi model
mới fallback nhập tay. Chi tiết accuracy và giới hạn đánh giá nằm trong
[MODEL_INFO.md](models/captcha/MODEL_INFO.md). Chạy bot bằng:

```powershell
.\.venv\Scripts\python.exe scripts\telegram_bot.py
```

Admin đăng nhập nguồn tuần tự cho từng worker bằng `/login`, xem ảnh riêng bot gửi và trả lời `/captcha <mã>`. User mới phải gửi `/start`; admin dùng `/approve <telegram_id>` trước khi user gửi `/tracuu <biển_số>` hoặc gửi trực tiếp biển số.

Lệnh admin: `/approve`, `/revoke`, `/block`, `/users`, `/status`, `/login`, `/captcha`, `/refresh_captcha`.

Mặc định `MAX_WORKERS=2` nhưng `SOURCE_SERIALIZE_REQUESTS=true`, phù hợp với nguồn chưa chứng minh an toàn khi gọi song song. Worker vẫn tách session/state và hàng đợi Telegram vẫn hoạt động độc lập.

Đánh giá model trên manifest TSV riêng tư (`đường_dẫn_ảnh<TAB>nhãn`), tối thiểu 50 mẫu:

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_captcha_model.py D:\duong-dan-rieng\labels.tsv
```

Script chỉ in số tổng hợp exact-match, không in ảnh, nhãn hoặc dự đoán.

Quy trình tạo model MobileNetV3-Small, fine-tune dataset và export ONNX được mô tả tại [CAPTCHA_FINETUNE.md](docs/CAPTCHA_FINETUNE.md).

## Script test Phase 1

Trước khi dùng `Tee-Object` trên Windows PowerShell, đặt encoding UTF-8 cho
terminal hiện tại:

```powershell
chcp 65001 > $null
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
```

Kiểm tra riêng đăng nhập CAPTCHA tay:

```powershell
.\.venv\Scripts\python.exe scripts\manual_login.py
```

Đăng nhập rồi tra cứu một input:

```powershell
.\.venv\Scripts\python.exe scripts\lookup_once.py
```

Chạy tuần tự 10–20 input:

```powershell
Copy-Item tests\live_plates.example.txt tests\live_plates.txt
# Thay nội dung live_plates.txt bằng dữ liệu được phép sử dụng.
.\.venv\Scripts\python.exe scripts\stability_test.py
```

Input chưa có đuôi sẽ được thử lần lượt với `T` và `V`. Input đã có đuôi `T/V` chỉ được tra cứu một lần.

Định dạng đã được HAR và UAT xác nhận là `2 số + 1 chữ + 5 số`, có thể kèm đuôi `T/V`. Input khác dạng được ghi `INVALID` ngay tại ứng dụng và không gửi lên website nguồn.

Làm sạch response HTML từ HAR để kiểm tra chẩn đoán:

```powershell
.\.venv\Scripts\python.exe scripts\sanitize_har.py
```

Output nằm trong `runtime/sanitized_har` và đã được Git ignore. Script không xuất request body và thay dữ liệu động bằng giá trị tổng hợp.

## Test tự động

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Baseline kỹ thuật Phase 3 ngày 16/08/2026: `182 passed`. `compileall` và
`pip check` đều pass.

Phase 3 bổ sung retry timeout/network/HTTP 5xx theo cấu hình, recovery job sau
restart, constraint trạng thái tại SQLite, giới hạn input và backup/restore có
integrity check. Runbook vận hành nằm tại [OPERATIONS.md](docs/OPERATIONS.md).

Backup DB:

```powershell
.\.venv\Scripts\python.exe scripts\database_backup.py backup
```

Restore DB (phải dừng bot trước):

```powershell
.\.venv\Scripts\python.exe scripts\database_backup.py restore D:\backup\dktle.sqlite3
```

Fixture trong `tests/fixtures/sanitized` là dữ liệu tổng hợp, không chứa credential hoặc dữ liệu phương tiện từ HAR.

## Dữ liệu và lỗi

SQLite mặc định: `runtime/dktle.sqlite3`.

Các trạng thái lookup:

- `SUCCESS`
- `INVALID`
- `NOT_FOUND`
- `ERROR`

`SUCCESS` chỉ được ghi khi đủ loại phương tiện, nhãn hiệu và hạn kiểm định. Response thiếu selector hoặc ngày hợp lệ được ghi nhận là lỗi parser, không trả dữ liệu một phần.

Lookup gặp HTTP `500`, `502`, `503` hoặc `504` sẽ thử lại tối đa ba lượt. Mỗi lượt luôn GET form WebForms mới trước khi POST lại candidate; không tái sử dụng hidden state cũ.

Nếu URL ảnh CAPTCHA trả `404`, client thử tải lại và controller yêu cầu website sinh ảnh mới tối đa ba lần. Lỗi ảnh không làm mất lượt nhập CAPTCHA của người vận hành.

## Nghiệm thu

Phase 1 và Phase 2 đã hoàn tất triển khai. Thực hiện P3-UAT-01 đến P3-UAT-10
trong [docs/PHASE_3.md](docs/PHASE_3.md) trước khi ký nghiệm thu Phase 3.

HAR gốc đã được bỏ khỏi Git index và vẫn được giữ trên máy để đối chiếu. Tuy nhiên, file từng nằm trong lịch sử commit cũ; phải đổi mật khẩu tài khoản nguồn và làm sạch lịch sử Git trước khi phát hành hoặc chia sẻ repository đó.
