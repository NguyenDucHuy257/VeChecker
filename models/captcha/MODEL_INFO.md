# CAPTCHA ONNX model gate

Kiến trúc đã chọn: **MobileNetV3-Small pretrained, 4 character crops, 4 position heads**.

Quy trình train và export nằm trong [CAPTCHA_FINETUNE.md](../../docs/CAPTCHA_FINETUNE.md).

## Lần train được chọn 16/08/2026 — dataset 6.063 ảnh

- Dataset: 6.063 ảnh; split theo nhãn thành 4.851 train, 606 validation, 606 test.
- Charset: 62 ký tự, phân biệt chữ hoa, chữ thường và số.
- Seed: `20260815`.
- Test character accuracy: **87,33%**.
- Test exact-match: **62,21%** (`377/606`), tăng 4,42 điểm so với model 3.081 ảnh.
- Accuracy theo vị trí: **97,85% / 95,05% / 85,31% / 71,12%**.
- Với confidence tối thiểu `0.60`: coverage **60,23%**, exact-match nội bộ **90,68%** (`331/365`).
- SHA-256 `model.pt`: `593c2812618bd3b54a863f033daafc5ae214423fe5d7145374e4f750e28af84d`.
- SHA-256 `model.onnx`: `eae23cefe64e93b065b27a0d40778175d955fb2b4bef3f0d9a27f3bc13b9c189`.

Trạng thái: **được chủ dự án yêu cầu bật auto-login với threshold 0,60**. Raw
exact-match chưa đạt 90% và kết quả threshold vẫn là test split nội bộ, không phải
tập độc lập do admin gán nhãn. Vòng login tự refresh/giải challenge mới khi
confidence thấp hoặc website báo CAPTCHA sai cho đến khi đăng nhập thành công.

Không đặt `model.onnx` vào đây cho tới khi có đủ:

- URL source và giấy phép cho phép sử dụng.
- SHA-256 của file `.pt` gốc và `model.onnx`.
- Input width/height, grayscale/RGB, normalize và charset.
- Kiểu output và cách decode tương thích contract `[1, length, charset]`.
- Báo cáo exact-match trên ít nhất 50 CAPTCHA mới do admin gán nhãn.
- Exact-match tối thiểu 90% và sai khác `.pt`/ONNX không quá một mẫu.

Khi đạt cổng trên:

1. Đặt file tại `models/captcha/model.onnx`.
2. Sao chép `model.example.json` thành `model.json` và điền metadata thật.
3. Ghi nguồn, license, checksum và kết quả đánh giá vào file này.
4. Đặt `CAPTCHA_MODE=auto`; nếu chưa đạt, giữ `CAPTCHA_MODE=manual`.
