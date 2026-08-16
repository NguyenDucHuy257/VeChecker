# Vận hành DKTLE — Phase 3

## Khởi động và dừng

Chạy từ thư mục dự án:

```bash
.venv/bin/python scripts/telegram_bot.py
```

Dừng bằng `Ctrl+C`. Ứng dụng chờ worker hiện tại hoàn tất, đóng HTTP session và
không nhận job mới. Khi khởi động lại, migration chạy tự động; lookup còn
`QUEUED/RUNNING` và Telegram update còn `ACCEPTED` từ process cũ được kết thúc
thành lỗi `SOURCE_ERROR`, không bị kẹt hoặc chạy lại ngoài ý muốn.

Sau restart, source session dùng chung trong RAM bị mất. Admin dùng `/login` để
đăng nhập account đã cấu hình trong `/etc/dktle.env`, sau đó kiểm tra `/status`
có `source_ready=True`. User không nhập hoặc biết credential nguồn.

## Retry nguồn

- Mọi request có timeout `REQUEST_TIMEOUT_SECONDS`.
- Lookup retry timeout, lỗi mạng và HTTP `500/502/503/504` tối đa
  `SOURCE_REQUEST_ATTEMPTS` lần.
- Delay tăng tuyến tính theo `SOURCE_RETRY_DELAY_SECONDS`.
- Mỗi lần retry lookup bắt đầu bằng GET form mới; không dùng lại WebForms state.
- HTTP 4xx, lỗi parse, input nghiệp vụ và credential không retry.
- CAPTCHA auto chỉ inference một lần trên mỗi challenge; ảnh confidence thấp
  hoặc bị website từ chối được thay bằng challenge mới cho đến khi login.
- Với Telegram ở chế độ CAPTCHA `auto`, khi lookup phát hiện session chung hết
  hạn, bot dùng credential còn trong RAM để đăng nhập lại rồi retry đúng candidate
  đó một lần. Nếu session tiếp tục hết hạn, job dừng để tránh vòng lặp vô hạn.
- `/logout` hoặc restart đóng session; admin dùng `/login` để khởi tạo lại.
- Telegram chỉ chạy một worker nguồn. `JOB_QUEUE_SIZE=20` cho phép tối đa 20 job
  đã nhận (gồm job đang chạy); job được xử lý lần lượt, không truy cập đồng thời.

## Backup SQLite

Có thể backup khi bot đang chạy; SQLite online backup tạo snapshot nhất quán:

```bash
.venv/bin/python scripts/database_backup.py backup
```

Mặc định file nằm trong `runtime/backups/dktle-YYYYMMDD-HHMMSS.sqlite3`. Chỉ định
đường dẫn khác bằng `--output`:

```bash
.venv/bin/python scripts/database_backup.py backup --output /safe/dktle.sqlite3
```

Restore là thao tác ghi đè DB vận hành. Dừng bot trước, kiểm tra đúng file rồi chạy:

```bash
.venv/bin/python scripts/database_backup.py restore /safe/dktle.sqlite3
```

Cả backup và restore đều chạy `PRAGMA integrity_check`. Sau restore, migration và
startup recovery được chạy lại.

## Error code

| Code | Ý nghĩa | Hành động |
|---|---|---|
| `INVALID_PLATE` | Input hoặc nguồn từ chối định dạng | Sửa input, không retry |
| `NOT_FOUND` | Không candidate nào có dữ liệu | Không retry |
| `PARSE_ERROR` | Website đổi cấu trúc/thiếu dữ liệu | Kiểm tra fixture/parser |
| `SOURCE_TIMEOUT` | Nguồn quá thời gian sau retry | Thử job mới sau |
| `SOURCE_NETWORK_ERROR` | Mất kết nối sau retry | Kiểm tra mạng |
| `SOURCE_HTTP_ERROR` | HTTP nguồn không hợp lệ | Kiểm tra status/log code |
| `SESSION_EXPIRED` | Session vẫn hết hạn sau một lần tự đăng nhập lại | Kiểm tra nguồn; admin chạy `/login` nếu lỗi lặp lại |
| `AUTH_FAILED` | Credential riêng bị từ chối | User kiểm tra account nguồn |
| `SOURCE_NOT_READY` | Session chung chưa được admin khởi tạo | Admin chạy `/login` |
| `SOURCE_ERROR` | Lỗi bất ngờ hoặc job bị ngắt do restart | Kiểm tra log, gửi job mới |
| `TELEGRAM_API_ERROR` | Telegram tạm lỗi | Polling tự chờ và thử lại |

## Kiểm tra trước phát hành

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q src scripts
.venv/bin/python -m pip check
```

Stability test cần file biển số thật được phép sử dụng và có thao tác website:

```bash
.venv/bin/python scripts/stability_test.py
```

Không commit `.env`, DB, backup, ảnh CAPTCHA, file input live, cookie hoặc HAR gốc.
