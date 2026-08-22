# VeChecker / DKTLE

Bot Telegram tra cứu thông tin kiểm định phương tiện từ `app.vr.org.vn`. Bot dùng
một tài khoản nguồn chung do admin đăng nhập, một WebForms session chung và một
worker FIFO. Telegram user không cần biết tài khoản nguồn.

## Chức năng chính

- Phân quyền Telegram: `ADMIN`, `USER`; trạng thái `PENDING`, `ACTIVE`, `BLOCKED`.
- Admin phê duyệt, thu hồi hoặc khóa user ngay trên Telegram.
- Chỉ admin nhập username/password nguồn bằng `/login`.
- Credential được xóa khỏi chat ngay, chỉ giữ trong RAM và không ghi SQLite/log.
- CAPTCHA được giải bằng model ONNX; nếu model lỗi, admin có thể nhập tay.
- Session hết hạn tự nhiên được đăng nhập lại rồi retry đúng candidate một lần.
- Một worker truy cập website tuần tự; queue mặc định tối đa 20 job.
- SQLite lưu lịch sử kết quả và hỗ trợ backup, restore, recovery sau restart.

## Luồng hoạt động

```text
Admin /login -> nhập credential -> giải CAPTCHA -> session nguồn READY
                                               |
User ACTIVE -> gửi biển số -> queue 20 slot -> 1 worker FIFO -> website nguồn
                                               |
                              session hết hạn -> tự login lại -> retry candidate
```

Khi admin gửi `/logout`, bot chặn yêu cầu mới, chờ job đang chạy hoàn tất, không
cho các job còn chờ gọi website, đóng session và xóa credential khỏi RAM. Sau
restart hoặc logout, admin phải `/login` lại.

## Lệnh Telegram

### User ACTIVE

| Lệnh | Mục đích |
|---|---|
| `/start` | Xem trạng thái phê duyệt |
| `/help` | Xem hướng dẫn theo quyền hiện tại |
| `/status` | Xem session chung và mức sử dụng queue |
| `/tracuu <biển_số>` | Gửi yêu cầu tra cứu |
| `/traacuu <biển_số>` | Bí danh của `/tracuu` |
| `<biển_số>` | Gửi trực tiếp, không cần lệnh |

User `PENDING` hoặc `BLOCKED` không được tra cứu. User không sử dụng được
`/login`, `/logout`, `/captcha` hoặc lệnh quản trị.

### Admin

Admin có toàn bộ lệnh của user và các lệnh sau:

| Lệnh | Mục đích |
|---|---|
| `/login` | Nhập username/password và mở session nguồn chung |
| `/cancel` | Hủy bước nhập credential |
| `/logout` | Đóng session chung sau khi job hiện tại hoàn tất |
| `/captcha <mã>` | Nhập CAPTCHA tay khi model fallback |
| `/refresh_captcha` | Lấy ảnh CAPTCHA khác |
| `/users` | Liệt kê Telegram ID, role và trạng thái |
| `/approve <telegram_id>` | Chuyển user sang `ACTIVE` |
| `/revoke <telegram_id>` | Chuyển user về `PENDING` |
| `/block <telegram_id>` | Chuyển user sang `BLOCKED` |

Không thể revoke hoặc block admin `ACTIVE` cuối cùng. User phải gửi `/start` ít
nhất một lần để xuất hiện trong `/users`.

## Định dạng biển số

Input có dạng `2 số + 1–2 chữ + 4–5 số`. Biển 5 số có thể kèm mã màu
`T`, `X` hoặc `V`:

```text
30A12345
30A12345T
30A12345V
30A12345X
37RM00562
37RM00562T
37S3456
```

Bot không phân biệt chữ hoa/thường và tự loại khoảng trắng, dấu gạch ngang, dấu
chấm cùng ký tự định dạng ẩn. Vì vậy `37rm00562`, `37-RM 005.62` và
`37RM00562` được chuẩn hóa thành cùng một giá trị.

Biển 4 số như `37s3456` và series `RM` được thử theo thứ tự: payload lowercase
nguyên bản, nối `t`, rồi nối `v`. Ví dụ: `37s3456`, `37s3456t`, `37s3456v` và
`37rm00628`, `37rm00628t`, `37rm00628v`. Toàn bộ payload đặc biệt này được gửi
ở dạng chữ thường. Các hidden field WebForms
(`__VIEWSTATE`, `__VIEWSTATEGENERATOR`, `__EVENTVALIDATION`) luôn được lấy mới từ
form ngay trước khi POST; không sử dụng lại giá trị mẫu hoặc request cũ.

Với biển 5 số chưa có mã màu, bot thường thử lần lượt `T` (trắng), `X` (xanh),
`V` (vàng). Riêng series `RM`, endpoint `ptpublicweb` dùng payload lowercase,
ví dụ `txtBienDK=37rm00628`; bot thử nguyên bản rồi thêm `t/v`. Series `KT` và
`LD` được gửi nguyên bản. Input sai định dạng bị từ chối tại ứng dụng và
không gửi lên website nguồn. Kết quả gồm biển đã tra, loại phương tiện, thương
hiệu/nhãn hiệu và thời hạn kiểm định.

## Yêu cầu

- Ubuntu 24.04 hoặc Linux tương đương.
- Python 3.11 trở lên; production hiện dùng Python 3.12.
- Git và `python3-venv`.
- Telegram bot token từ BotFather.
- Telegram numeric ID của ít nhất một admin.
- Account nguồn hợp lệ; chỉ nhập sau khi admin dùng `/login`.

## Cài đặt

```bash
cd /opt
git clone --branch main https://github.com/NguyenDucHuy257/VeChecker.git
cd VeChecker
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install -e . --no-deps
```

Tạo user và thư mục runtime:

```bash
id dktle >/dev/null 2>&1 || useradd --system --shell /usr/sbin/nologin dktle
mkdir -p /var/lib/dktle/captcha /var/lib/dktle/backups
chown -R dktle:dktle /var/lib/dktle
chmod -R 750 /var/lib/dktle
```

## Cấu hình

Tạo `/etc/dktle.env`:

```env
TELEGRAM_ADMIN_IDS=123456789
TELEGRAM_BOT_TOKEN=TOKEN_MOI_TU_BOTFATHER

VR_BASE_URL=https://app.vr.org.vn/ptpublicweb/
DATABASE_PATH=/var/lib/dktle/dktle.sqlite3
CAPTCHA_DIR=/var/lib/dktle/captcha

REQUEST_TIMEOUT_SECONDS=15
SOURCE_REQUEST_ATTEMPTS=3
SOURCE_RETRY_DELAY_SECONDS=1
MAX_CAPTCHA_ATTEMPTS=3
CANDIDATE_DELAY_SECONDS=2
VERIFY_SSL=true
LOG_LEVEL=INFO

JOB_QUEUE_SIZE=20
TELEGRAM_POLL_TIMEOUT_SECONDS=25
USER_RATE_LIMIT_SECONDS=2
SOURCE_SERIALIZE_REQUESTS=true

CAPTCHA_MODE=auto
CAPTCHA_MODEL_PATH=/opt/VeChecker/models/captcha/model.onnx
CAPTCHA_CONFIDENCE_THRESHOLD=0.60
```

`VR_USERNAME` và `VR_PASSWORD` không bắt buộc với Telegram bot. Bot vẫn khởi
động khi chưa có session; user tra cứu lúc đó được hướng dẫn báo admin `/login`.

```bash
chown root:root /etc/dktle.env
chmod 600 /etc/dktle.env
```

Không commit file cấu hình thật, token, credential, database, cookie, CAPTCHA,
HAR hoặc danh sách biển số thật vào Git.

## Chạy thử trực tiếp

```bash
cd /opt/VeChecker
set -a
. /etc/dktle.env
set +a
.venv/bin/python scripts/telegram_bot.py
```

Dừng bằng `Ctrl+C`.

## Chạy bằng systemd

Tạo `/etc/systemd/system/dktle.service`:

```ini
[Unit]
Description=DKTLE Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=dktle
Group=dktle
WorkingDirectory=/opt/VeChecker
EnvironmentFile=/etc/dktle.env
ExecStart=/opt/VeChecker/.venv/bin/python /opt/VeChecker/scripts/telegram_bot.py
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/dktle

[Install]
WantedBy=multi-user.target
```

Nạp và khởi động:

```bash
systemctl daemon-reload
systemctl enable --now dktle
sleep 5
systemctl status dktle --no-pager
journalctl -u dktle --since "1 minute ago" --no-pager
```

Sau khi bot chạy, admin gửi `/login`, nhập username/password nguồn và kiểm tra:

```text
/status
source_ready=True | shared_sessions=1 | queue=0/20
```

## Cập nhật production

```bash
cd /opt/VeChecker
systemctl stop dktle
git pull --ff-only origin main
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install -e . --no-deps
systemctl start dktle
sleep 5
systemctl status dktle --no-pager
journalctl -u dktle --since "1 minute ago" --no-pager
```

Restart làm mất session và credential trong RAM; admin cần `/login` lại.

## Đổi admin

Sửa `TELEGRAM_ADMIN_IDS` trong `/etc/dktle.env`. Có thể đặt nhiều ID, phân tách
bằng dấu phẩy. Khi restart, ID trong cấu hình được thêm hoặc nâng thành admin;
admin cũ không tự bị hạ quyền trong SQLite.

Để thay hẳn admin, dừng bot, backup DB, thêm admin mới và hạ admin cũ bằng
`sqlite3`. Luôn thay hai placeholder bằng numeric ID thật:

```bash
systemctl stop dktle
cp -a /var/lib/dktle/dktle.sqlite3 /var/lib/dktle/backups/dktle-before-admin-change.sqlite3

sqlite3 /var/lib/dktle/dktle.sqlite3 "
BEGIN;
INSERT INTO users (telegram_user_id, role, status)
VALUES (ID_ADMIN_MOI, 'ADMIN', 'ACTIVE')
ON CONFLICT(telegram_user_id) DO UPDATE SET role='ADMIN', status='ACTIVE';
UPDATE users SET role='USER', status='ACTIVE'
WHERE telegram_user_id=ID_ADMIN_CU AND telegram_user_id<>ID_ADMIN_MOI;
COMMIT;
"

chown dktle:dktle /var/lib/dktle/dktle.sqlite3
systemctl start dktle
```

## Vận hành và xử lý lỗi

```bash
systemctl is-active dktle
systemctl show dktle -p NRestarts --value
journalctl -u dktle -n 100 --no-pager
```

- `source_ready=False`: admin chưa login, đã logout hoặc đăng nhập lại thất bại.
- `queue=20/20`: queue đầy; user cần gửi lại sau.
- `SESSION_EXPIRED`: tự login lại vẫn không giữ được session; admin thử `/login`.
- `AUTH_FAILED`: username/password nguồn không đúng.
- `PARSE_ERROR`: website nguồn đã đổi cấu trúc HTML.
- `SOURCE_TIMEOUT`, `SOURCE_NETWORK_ERROR`, `SOURCE_HTTP_ERROR`: nguồn hoặc mạng
  tạm thời không ổn định.

Runbook chi tiết: [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Backup và restore

Backup online:

```bash
cd /opt/VeChecker
set -a; . /etc/dktle.env; set +a
.venv/bin/python scripts/database_backup.py backup --output /var/lib/dktle/backups/dktle.sqlite3
```

Restore phải thực hiện khi bot đã dừng:

```bash
systemctl stop dktle
cd /opt/VeChecker
set -a; . /etc/dktle.env; set +a
.venv/bin/python scripts/database_backup.py restore /var/lib/dktle/backups/dktle.sqlite3
chown dktle:dktle /var/lib/dktle/dktle.sqlite3
systemctl start dktle
```

## Kiểm thử

```bash
cd /opt/VeChecker
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q src scripts tests
.venv/bin/python -m pip check
```

Baseline hiện tại: `206 passed`.

Đánh giá model CAPTCHA bằng manifest TSV riêng tư:

```bash
.venv/bin/python scripts/evaluate_captcha_model.py /duong/dan/labels.tsv
```

Quy trình fine-tune và export: [docs/CAPTCHA_FINETUNE.md](docs/CAPTCHA_FINETUNE.md).
Thông tin model production: [models/captcha/MODEL_INFO.md](models/captcha/MODEL_INFO.md).

## Cấu trúc dự án

```text
src/app/                 code ứng dụng MVC và service
scripts/telegram_bot.py  entrypoint production
scripts/                 công cụ backup, đánh giá và huấn luyện CAPTCHA
models/captcha/          model ONNX production và metadata
tests/                   test với fixture đã làm sạch
docs/OPERATIONS.md       runbook vận hành
docs/CAPTCHA_FINETUNE.md hướng dẫn model CAPTCHA
```

## Bảo mật

- Token và credential từng bị gửi qua kênh không an toàn phải được thu hồi/đổi.
- Chỉ chat private được bot xử lý.
- Bot cố xóa ngay tin nhắn username/password của admin; admin vẫn nên tự kiểm tra
  và xóa nếu Telegram API báo lỗi.
- Credential/session chỉ ở RAM và mất khi logout, shutdown hoặc restart.
- SQLite không lưu username/password nguồn, CAPTCHA hoặc cookie.
- Fixture trong `tests/fixtures/sanitized` là dữ liệu tổng hợp đã làm sạch.
