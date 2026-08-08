# Phase 1 — Base MVC, DB, parser và CAPTCHA nhập tay

## 1. Mục tiêu

Hoàn thành lõi tra cứu chạy bằng SCRIPT TEST PYTHON ( KHÔNG DÙNG ClI), dùng một tài khoản nguồn và CAPTCHA nhập tay. Phase này phải chứng minh một tài khoản có thể tra cứu nhiều biển số tuần tự, parser trả đúng ba trường và DB ghi đúng lịch sử.

Không làm trong Phase 1: Telegram, đa luồng và CAPTCHA tự động.

## 2. Điều kiện đầu vào

- `VR_USERNAME` và `VR_PASSWORD` do chủ dự án đặt trong `.env`.
- Danh sách 10–20 biển số được phép dùng để nghiệm thu, gồm:
  - Biển số gốc chưa có đuôi.
  - Biển số đã có đuôi `t`.
  - Biển số đã có đuôi `v`.
  - Biển số sai định dạng.
  - Biển số không có dữ liệu.
- `TELEGRAM_ADMIN_IDS` để kiểm tra seed admin trong DB; chưa khởi chạy bot.

## 3. Thành phần MVC phải tạo

```text
src/app/
  config.py
  database.py
  main.py

  models/
    user.py
    lookup.py

  views/
    cli_view.py

  controllers/
    auth_controller.py
    lookup_controller.py

  services/
    webforms_client.py
    vr_parser.py
    captcha_service.py
```

Trách nhiệm:

- `models`: model SQLite `User`, `Lookup` và các trạng thái nghiệp vụ.
- `cli_view`: hiển thị CAPTCHA, nhận mã và in kết quả; không gọi HTTP/DB trực tiếp.
- `auth_controller`: điều phối đăng nhập/refresh CAPTCHA giữa view và service.
- `lookup_controller`: nhận biển số, tạo candidate, gọi tra cứu và lưu kết quả.
- `webforms_client`: GET/POST, session, hidden field, timeout và phát hiện redirect/login.
- `vr_parser`: sửa encoding, parse lỗi và ba trường kết quả.
- `captcha_service`: lưu ảnh CAPTCHA tạm và xóa ngay sau khi dùng.

## 4. Luồng thực hiện

### 4.1. Khởi động

```text
main
  -> load .env
  -> tạo/migrate SQLite
  -> upsert TELEGRAM_ADMIN_IDS thành ADMIN + ACTIVE
  -> auth_controller.login()
```

### 4.2. Đăng nhập tay

```text
GET Login.aspx
  -> parse hidden fields + captchaImage
  -> tải CAPTCHA
  -> cli_view yêu cầu nhập
  -> POST Login.aspx
     -> 302: READY
     -> CAPTCHA sai: lấy state/ảnh mới và cho nhập lại
     -> lỗi khác: dừng với error code rõ ràng
```

Giới hạn tối đa ba lần nhập CAPTCHA trong một lượt login. Sau đó dừng để người vận hành chủ động chạy lại; không lặp vô hạn.

### 4.3. Tạo candidate biển số

```text
normalize = trim + uppercase

Nếu kết thúc bằng T hoặc V:
  candidates = [normalize]
Ngược lại:
  candidates = [normalize + "T", normalize + "V"]
```

Mỗi candidate được tra cứu độc lập bằng một lần GET form mới và một lần POST. Trả mọi candidate có dữ liệu; nếu không candidate nào có dữ liệu thì trả `NOT_FOUND`.

### 4.4. Parse kết quả

- `#txtLoaiPT` → `vehicle_type`.
- `#txtNhanHieu` → `brand`.
- `#DGKiemDinh` → xác định cột “Thời hạn KĐ”, parse mọi dòng và chọn ngày lớn nhất.
- Thiếu một trong ba trường bắt buộc → `PARSE_ERROR`, không ghi `SUCCESS`.

## 5. Thứ tự triển khai

1. Tạo `.gitignore`, `.env.example`, cấu hình và logging redaction.
2. Tạo SQLite schema và seed admin idempotent.
3. Tạo fixture HTML đã làm sạch từ HAR; không copy HAR gốc vào `tests`.
4. Viết parser và unit test trước.
5. Viết WebForms client và test bằng response giả lập.
6. Viết controller và CLI nhập CAPTCHA.
7. Chạy tra cứu live từng biển số.
8. Chạy stability test tuần tự sau khi các test đơn lẻ đã pass.

## 6. Test tự động

### Model/DB

- Tạo DB mới đúng hai bảng nghiệp vụ.
- Seed admin nhiều lần không trùng.
- `telegram_user_id` unique.
- Lookup lưu đúng `input_plate`, `queried_plate`, status và ba trường kết quả.

### WebForms client

- Luôn dùng hidden field từ response ngay trước request.
- Không double URL-encode `__VIEWSTATE`/`__EVENTVALIDATION`.
- Nhận đúng `302` đăng nhập thành công.
- Nhận đúng lỗi CAPTCHA từ HTTP `200`.
- Mỗi candidate GET form mới; không tái sử dụng state.
- Timeout hoặc response quay về login trả đúng error code.

### Parser

- Kết quả đủ ba trường.
- Bảng kiểm định một dòng và nhiều dòng.
- Ngày lỗi, bảng rỗng hoặc thiếu cột.
- HTML lỗi định dạng/không có dữ liệu.
- Encoding tiếng Việt không nhất quán.
- HTML thiếu selector không được coi là thành công.

### Controller

- Input gốc tạo đúng hai candidate `T/V` theo đúng thứ tự.
- Input có đuôi `T/V` chỉ tạo một candidate.
- Không candidate có dữ liệu → `NOT_FOUND`.
- Một candidate có dữ liệu → trả một kết quả.
- Hai candidate có dữ liệu → trả hai kết quả.

Lệnh test dự kiến:

```powershell
pytest -q
python -m app.main login
python -m app.main lookup <BIEN_SO_TEST>
python scripts/stability_test.py --input <FILE_TEST> --delay 2
```

## 7. Nghiệm thu của chủ dự án

| ID | Thao tác | Kết quả bắt buộc |
|---|---|---|
| P1-UAT-01 | Khởi động với DB mới | Có đúng admin mặc định `ACTIVE`, không tạo trùng khi chạy lại |
| P1-UAT-02 | Nhập CAPTCHA sai rồi refresh | Báo đúng lỗi, có ảnh mới, ứng dụng không treo |
| P1-UAT-03 | Nhập CAPTCHA đúng | Chuyển `READY`; credential/CAPTCHA không xuất hiện trong log |
| P1-UAT-04 | Tra biển số gốc chưa có đuôi | Hệ thống thử lần lượt bản `T` và `V`, trả candidate có dữ liệu |
| P1-UAT-05 | Tra biển số đã có đuôi `T` hoặc `V` | Chỉ gọi đúng biển số input một lần |
| P1-UAT-06 | Tra biển số sai định dạng | Trả `INVALID`, không ghi `SUCCESS` |
| P1-UAT-07 | Tra biển số không có dữ liệu | Trả `NOT_FOUND`, phiên vẫn dùng tiếp được |
| P1-UAT-08 | Đối chiếu ít nhất 5 kết quả với website | Khớp loại phương tiện, nhãn hiệu và hạn kiểm định |
| P1-UAT-09 | Chạy tuần tự 10–20 input, delay tối thiểu 2 giây | Không trộn kết quả, không mất state, không có job kẹt |
| P1-UAT-10 | Chạy `pytest -q` | Toàn bộ test pass |

## 8. Sản phẩm bàn giao và cổng phase

- Source MVC của Phase 1.
- SQLite migration.
- Test fixtures đã làm sạch.
- Scripts login, lookup một lần và stability test.
- README hướng dẫn chạy Phase 1.
- Báo cáo kết quả P1-UAT-01 đến P1-UAT-10.

Chỉ bắt đầu Phase 2 sau khi chủ dự án ký `PASS` toàn bộ Phase 1.

```text
PHASE 1: PASS / FAIL
Người nghiệm thu:
Ngày:
Lỗi cần sửa:
```
