# Fine-tune CAPTCHA MobileNetV3-Small

## Mục tiêu và contract

Dataset `runtime/dataset` gồm ảnh CAPTCHA `120×35`, mỗi nhãn dài đúng 4 ký tự và phân biệt hoa/thường. Charset theo đúng thứ tự:

```text
0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz
```

Pipeline hỗ trợ ba kiến trúc MobileNetV3-Small pretrained. `spatial` giữ feature map toàn ảnh; `character-crops` chia đúng bốn cell ký tự, phóng lên `64×64` và dùng bốn head riêng; `character-crops-shared` dùng chung classifier cho cả bốn crop để tận dụng toàn bộ mẫu ký tự. Tất cả đều xuất ONNX `[batch, 4, 62]`, tương thích `OnnxCaptchaRecognizer`.

## Cài dependency huấn luyện

Dependency runtime vẫn nhẹ; PyTorch chỉ nằm trong extra `train`:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[train]"
```

## Kiểm tra dataset

`labels.tsv` phải có header và đường dẫn tương đối:

```tsv
filename	label
images/00IF.jpg	00IF
```

Pipeline tự kiểm tra file tồn tại, nhãn dài bốn ký tự và chỉ thuộc charset. Các mẫu có cùng nhãn luôn ở cùng partition để tránh leakage. Split mặc định là 80% train, 10% validation và 10% test với seed cố định.

## Chạy fine-tune

GPU CUDA được chọn tự động; nếu không có, script chạy CPU:

```powershell
.\.venv\Scripts\python.exe scripts\train_captcha_model.py `
  --dataset runtime\dataset `
  --output models\captcha\model.onnx `
  --architecture character-crops `
  --epochs 40 `
  --batch-size 64
```

Lần đầu, Torchvision tải weight ImageNet chính thức. Bốn epoch đầu chỉ học head; sau đó toàn bộ backbone được fine-tune bằng AdamW và cosine learning-rate. Early stopping dùng exact-match validation. Có thể dùng `--no-pretrained` khi chạy hoàn toàn offline, nhưng đó là train from scratch và thường kém hơn với dataset nhỏ.

Artifact đầu ra:

- `model.onnx`: model deploy.
- `model.json`: metadata input/output và charset.
- `model.pt`: checkpoint PyTorch tốt nhất.
- `model.metrics.json`: split, lịch sử và kết quả test.

Khi thử kiến trúc khác, luôn dùng một tên output khác; không ghi đè model tốt nhất trước khi so sánh test exact-match.

## Xác minh trước khi bật production

Chạy test contract và đánh giá tập độc lập ít nhất 50 ảnh chưa xuất hiện trong dataset train:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\evaluate_captcha_model.py D:\private-captcha\labels.tsv
```

Chỉ đặt `CAPTCHA_MODE=auto` khi exact-match độc lập đạt ít nhất 90%. Character accuracy chỉ dùng để chẩn đoán; tiêu chí quyết định là toàn bộ bốn ký tự đúng, kể cả hoa/thường.

Kết quả của mỗi lần train được lưu trong `model.metrics.json`. Artifact phải được kiểm tra bằng ONNX Runtime và ghi checksum vào `models/captcha/MODEL_INFO.md` trước khi bật tự động.

Lần train được chọn ngày 16/08/2026 dùng `character-crops`, đạt 85,31% character accuracy và 57,79% raw exact-match trên test split. Khi chỉ nhận dự đoán có confidence tối thiểu 0,50, exact-match nội bộ đạt 90,68% với coverage 52,27%; vẫn cần tập CAPTCHA độc lập trước khi bật production.

## Lưu ý augmentation

Pipeline chỉ xoay/dịch và đổi sáng-tương phản nhẹ. Không flip, crop hoặc chuyển lowercase vì các phép đó làm sai nhãn. Nếu `l`, `I`, `1`, `0`, `O`, `o` còn nhầm nhiều, ưu tiên thu thập thêm ảnh thật cân bằng thay vì tăng augmentation quá mạnh.
