# Phase 2 — Telegram, worker đa luồng và CAPTCHA ONNX

## 1. Mục tiêu

Kết nối lõi tra cứu Phase 1 với Telegram, kiểm soát quyền bằng admin, xử lý hàng đợi bằng worker giới hạn và bổ sung CAPTCHA tự động bằng model ONNX có fallback nhập tay.

Không làm trong Phase 2: web admin, webhook public, Redis, nhiều tài khoản nguồn hoặc tự huấn luyện model liên tục.

## 2. Điều kiện bắt đầu

- Phase 1 đã được chủ dự án ký `PASS`.
- Có `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_IDS` trong `.env`.
- Có ít nhất một Telegram user thử nghiệm ngoài admin.
- Việc dùng CAPTCHA tự động đã được chủ dự án xác nhận phù hợp với quyền sử dụng tài khoản và điều khoản của website.

## 3. Thành phần MVC bổ sung

```text
src/app/
  models/
    user.py
    lookup.py

  views/
    telegram_view.py

  controllers/
    telegram_controller.py
    auth_controller.py
    lookup_controller.py

  services/
    worker_service.py
    captcha_service.py
    captcha_onnx.py

models/captcha/
  model.onnx
  MODEL_INFO.md
```

Trách nhiệm:

- `telegram_view`: định dạng message, CAPTCHA image và kết quả; không quyết định quyền.
- `telegram_controller`: nhận update, gọi authorization/lookup controller và chọn view trả lời.
- `worker_service`: hàng đợi giới hạn, tối đa số worker cấu hình được.
- `captcha_onnx`: tiền xử lý ảnh, inference ONNX, trả chuỗi và confidence.
- `captcha_service`: chọn manual/auto, quản lý fallback và lock đăng nhập.

## 4. Luồng Telegram và phân quyền

```text
/start
  -> chưa có user: tạo PENDING
  -> PENDING/BLOCKED: không được tra cứu
  -> ACTIVE: nhận lệnh tra cứu

Admin
  -> /approve <id>
  -> /revoke <id>
  -> /block <id>
  -> /users
  -> /status
  -> /login
  -> /captcha <mã>
  -> /refresh_captcha
```

User `ACTIVE` được dùng:

- `/tracuu <biển_số>`.
- Gửi trực tiếp một biển số trong private chat.

Mỗi request Telegram tạo một job theo input. Controller áp dụng quy tắc candidate `T/V` của Phase 1 rồi trả mọi kết quả tìm thấy cho đúng chat/user đã yêu cầu.

## 5. Luồng worker đa luồng

```text
Telegram controller
  -> kiểm tra quyền + input
  -> enqueue job
  -> worker nhận job
  -> mỗi candidate: GET form mới + POST
  -> parser
  -> lưu DB
  -> telegram_view trả kết quả
```

Quy tắc bắt buộc:

- Bắt đầu với `MAX_WORKERS=2`.
- Mỗi worker có HTTP client và WebForms state riêng.
- Không chạy song song hai candidate `T/V` trong cùng một job; tra tuần tự để dễ đối chiếu.
- Login/refresh CAPTCHA dùng một lock chung.
- Nếu test live cho thấy tài khoản nguồn không an toàn khi song song, đặt lock cho phần gọi website nhưng vẫn giữ hàng đợi Telegram.
- Job trùng cùng `telegram_update_id` chỉ xử lý một lần.

## 6. CAPTCHA ONNX

### 6.1. Đánh giá model

1. Tìm model miễn phí có source và giấy phép sử dụng rõ ràng.
2. Không đưa model không rõ giấy phép vào dự án.
3. Chuẩn bị tối thiểu 50 CAPTCHA mới, do admin nhập nhãn đúng để tạo tập test độc lập.
4. Đánh giá theo `exact-match accuracy`: cả chuỗi phải đúng mới tính là đúng.
5. Chỉ chọn model đạt tối thiểu 90% exact-match trên tập test độc lập.
6. Nếu không model nào đạt, Phase 2 chưa đạt phần CAPTCHA tự động; tiếp tục manual mode và báo chủ dự án quyết định.

### 6.2. Chuyển `.pt` sang ONNX

- Export với input shape cố định theo ảnh CAPTCHA thực tế.
- So sánh output `.pt` và ONNX trên cùng tập test.
- Sai khác exact-match giữa hai bản không vượt 1 mẫu trên toàn tập test.
- Lưu nguồn model, giấy phép, kích thước input, charset và checksum trong `MODEL_INFO.md`.

### 6.3. Chạy thực tế

```text
CAPTCHA_MODE=manual
  -> luôn gửi ảnh cho admin

CAPTCHA_MODE=auto
  -> ONNX inference
  -> confidence đạt ngưỡng: thử đăng nhập một lần
  -> confidence thấp hoặc website báo sai: gửi ảnh cho admin
```

Không để model retry tự động vô hạn. Tối đa một lần thử tự động trên mỗi ảnh CAPTCHA trước khi fallback.

## 7. Test tự động

### Authorization/controller

- `PENDING/BLOCKED` không gọi được lookup controller.
- Chỉ admin dùng được lệnh quản trị.
- Approve/revoke/block có hiệu lực ngay.
- Không thể revoke/block admin cuối cùng.
- Input không hợp lệ không được enqueue.

### Worker

- Hai worker không dùng chung session/state.
- Không trả chéo chat ID hoặc user ID.
- Update trùng không tạo job trùng.
- Queue đầy trả `BUSY` và không tăng vô hạn.
- Worker lỗi không làm bot dừng.
- Hết phiên chuyển sang trạng thái chờ login, không retry vòng lặp.

### CAPTCHA

- Tiền xử lý ảnh cho tensor đúng shape/type.
- ONNX output chỉ chứa charset/độ dài hợp lệ.
- Confidence dưới ngưỡng luôn fallback.
- Website báo CAPTCHA sai sau auto inference luôn fallback.
- Manual mode không load model.
- Token, ảnh CAPTCHA và dự đoán không xuất hiện trong log.

### Telegram view

- Kết quả một candidate và hai candidate hiển thị rõ ràng.
- Chỉ trả loại phương tiện, nhãn hiệu và hạn kiểm định.
- Thông báo lỗi không chứa stack trace, credential hoặc HTML.

## 8. Nghiệm thu của chủ dự án

| ID | Thao tác | Kết quả bắt buộc |
|---|---|---|
| P2-UAT-01 | User mới gửi `/start` và biển số | User là `PENDING`, bị từ chối tra cứu |
| P2-UAT-02 | Admin approve user | User dùng được ngay, không cần restart bot |
| P2-UAT-03 | User tra bằng lệnh và tin nhắn trực tiếp | Hai cách trả đúng kết quả Phase 1 |
| P2-UAT-04 | Admin revoke/block user | User bị từ chối ngay ở yêu cầu kế tiếp |
| P2-UAT-05 | Hai user gửi tổng cộng 5–10 input gần đồng thời | Không mất/trộn job và không trả sai chat |
| P2-UAT-06 | Chạy tập test CAPTCHA độc lập | Model ONNX đạt ngưỡng exact-match đã quy định |
| P2-UAT-07 | Dùng CAPTCHA confidence thấp hoặc cố ý làm model sai | Bot gửi ảnh riêng cho admin và đăng nhập được bằng tay |
| P2-UAT-08 | Làm hết hạn phiên trong lúc có job | Job không chạy vòng lặp; hệ thống hoạt động lại sau login |
| P2-UAT-09 | Restart bot | Quyền user còn nguyên, admin vẫn `ACTIVE` |
| P2-UAT-10 | Kiểm tra log và chạy `pytest -q` | Không lộ bí mật; toàn bộ test pass |

## 9. Sản phẩm bàn giao và cổng phase

- Telegram bot chạy private chat.
- Admin/user authorization đầy đủ.
- Worker pool giới hạn và có fallback tuần tự.
- Model ONNX cùng `MODEL_INFO.md` hoặc báo cáo không có model đạt ngưỡng.
- Test report CAPTCHA và concurrency.
- README cập nhật lệnh bot và cấu hình Phase 2.

Chỉ bắt đầu Phase 3 khi chủ dự án ký `PASS` toàn bộ Phase 2. Nếu model không đạt ngưỡng, P2-UAT-06 là `FAIL` cho tới khi chủ dự án thay đổi tiêu chí hoặc chọn phương án khác.

```text
PHASE 2: PASS / FAIL
Người nghiệm thu:
Ngày:
Lỗi cần sửa:
```
