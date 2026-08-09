# DKTLE — Phase 1

Ứng dụng MVC dùng một tài khoản `app.vr.org.vn` để đăng nhập bằng CAPTCHA nhập tay, tra cứu tuần tự và lưu lịch sử vào SQLite.

Phase 1 chỉ cung cấp các script Python phục vụ test/nghiệm thu. Chưa có Telegram, đa luồng hoặc CAPTCHA tự động.

## Cấu trúc MVC

- `src/app/models`: `User`, `Lookup` và repository SQLite.
- `src/app/views`: nhập CAPTCHA/biển số và hiển thị ba trường kết quả cho script.
- `src/app/controllers`: điều phối đăng nhập, candidate `T/V`, tra cứu và ghi DB.
- `src/app/services`: HTTP WebForms, parser HTML, CAPTCHA file và error codes.

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
- `CANDIDATE_DELAY_SECONDS=2`: khoảng nghỉ tối thiểu giữa hai candidate `T/V`.
- `STABILITY_INPUT_FILE` và `STABILITY_DELAY_SECONDS`: file đầu vào và khoảng nghỉ của stability test.

Không đưa `.env`, DB, ảnh CAPTCHA, file biển số thật hoặc HAR vào Git.

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

Làm sạch response HTML từ HAR để kiểm tra chẩn đoán:

```powershell
.\.venv\Scripts\python.exe scripts\sanitize_har.py
```

Output nằm trong `runtime/sanitized_har` và đã được Git ignore. Script không xuất request body và thay dữ liệu động bằng giá trị tổng hợp.

## Test tự động

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Baseline ngày 09/08/2026: `94 passed`. `compileall` và `pip check` cũng đã pass.

Fixture trong `tests/fixtures/sanitized` là dữ liệu tổng hợp, không chứa credential hoặc dữ liệu phương tiện từ HAR.

## Dữ liệu và lỗi

SQLite mặc định: `runtime/dktle.sqlite3`.

Các trạng thái lookup:

- `SUCCESS`
- `INVALID`
- `NOT_FOUND`
- `ERROR`

`SUCCESS` chỉ được ghi khi đủ loại phương tiện, nhãn hiệu và hạn kiểm định. Response thiếu selector hoặc ngày hợp lệ được ghi nhận là lỗi parser, không trả dữ liệu một phần.

## Nghiệm thu

Thực hiện P1-UAT-01 đến P1-UAT-10 trong [docs/PHASE_1.md](docs/PHASE_1.md). Không bắt đầu Phase 2 trước khi chủ dự án ký `PASS` toàn bộ Phase 1.

HAR gốc đã được bỏ khỏi Git index và vẫn được giữ trên máy để đối chiếu. Tuy nhiên, file từng nằm trong lịch sử commit cũ; phải đổi mật khẩu tài khoản nguồn và làm sạch lịch sử Git trước khi phát hành hoặc chia sẻ repository đó.
