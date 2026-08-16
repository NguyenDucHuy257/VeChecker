# Báo cáo kiểm tra Phase 3 — 16/08/2026

## Kết quả kỹ thuật

| Hạng mục | Kết quả |
|---|---:|
| Pytest | 185 passed |
| Compile `src` và `scripts` | PASS |
| `pip check` | PASS — không có dependency lỗi |
| SQLite schema | v3 |
| SQLite integrity | ok |
| Lookup dở dang khi migrate | 0 |
| Telegram update dở dang khi migrate | 0 |

## Failure matrix đã kiểm tra tự động

- Connect timeout, read timeout và network error được retry có giới hạn/backoff.
- HTTP 500–504 retry bằng GET form mới; HTTP 400 không retry.
- Session hết hạn trước GET và sau POST đều hạ trạng thái worker.
- Response rỗng, thiếu selector và bảng đổi cấu trúc fail-closed.
- CAPTCHA confidence thấp/sai được giải challenge mới đến khi login.
- Model thiếu/hỏng fallback hoặc fail-closed theo điểm gọi.
- Transaction lỗi rollback; trigger v3 chặn lookup/update không nhất quán.
- Startup kết thúc lookup `QUEUED/RUNNING` và update `ACCEPTED` cũ.
- Queue đầy, rate limit, update trùng và input quá dài không tạo job sai.
- Formatter che secret cả message và exception traceback.
- Backup/restore SQLite round-trip và integrity check pass.
- Hai user dùng hai account/client/session độc lập; logout hoặc session expiry của
  một user không ảnh hưởng user khác.
- Username/password messages được gọi xóa ngay và không xuất hiện trong bot response.

## Artifact vận hành

- Backup trước migration:
  `runtime/backups/dktle-20260816-081557.sqlite3`
- Runbook: `docs/OPERATIONS.md`
- Migration: `003_phase3_integrity.sql`

## UAT còn cần chủ dự án thực hiện

Các ca P3-UAT-01..10 có website/Telegram thật chưa được tự động chạy vì cần input
được phép, admin thật và đối chiếu thủ công với website. Đặc biệt còn cần stability
test live, ngắt mạng có kiểm soát, restart khi đang có job và đối chiếu ngẫu nhiên
ít nhất năm kết quả. Vì vậy trạng thái hiện tại là **TECHNICAL PASS / LIVE UAT PENDING**.
