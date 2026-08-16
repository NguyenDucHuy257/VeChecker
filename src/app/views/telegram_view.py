"""Plain-text Telegram messages; no authorization decisions live here."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any

from app.models import User


class TelegramView:
    @staticmethod
    def user_help() -> str:
        return """HƯỚNG DẪN USER

Quyền: tra cứu bằng session nguồn dùng chung do admin quản lý. Bạn không thể xem tài khoản nguồn hoặc quản lý user khác.

/start — xem trạng thái phê duyệt
/help — mở hướng dẫn này
/status — xem session dùng chung và hàng đợi
/tracuu <biển_số> — gửi yêu cầu tra cứu
/traacuu <biển_số> — bí danh của /tracuu
<biển_số> — có thể gửi trực tiếp, không cần lệnh

Cách dùng:
1. Chờ admin khởi tạo session nguồn.
2. Gửi /tracuu <biển_số> hoặc gửi trực tiếp biển số.
3. Yêu cầu được xếp hàng và xử lý lần lượt, không chạy đồng thời.
4. Khi session nguồn hết hạn, bot tự đăng nhập lại rồi tiếp tục job.

Biển số hợp lệ: 2 số + 1-2 chữ + 5 số, có thể kèm T/V. Ví dụ: 30A12345, 37RM00562. Biển một chữ không có đuôi sẽ thử T/V; biển hai chữ được tra nguyên bản."""

    @staticmethod
    def admin_help() -> str:
        return """HƯỚNG DẪN ADMIN

Admin có toàn bộ quyền user và đại diện quản lý một session nguồn dùng chung. Chỉ admin nhập credential; Telegram user không được xem hoặc nhập.

Lệnh quản trị:
/users — liệt kê Telegram ID, role và trạng thái
/approve <telegram_id> — chuyển user sang ACTIVE
/revoke <telegram_id> — chuyển về PENDING và đóng session nguồn ngay
/block <telegram_id> — khóa user và đóng session nguồn ngay

Không thể revoke/block admin ACTIVE cuối cùng. User phải gửi /start ít nhất một lần trước khi xuất hiện trong /users.

Lệnh sử dụng cá nhân:
/login — nhập username/password để mở session nguồn dùng chung
/cancel — hủy bước nhập credential
/status — trạng thái session dùng chung và queue
/tracuu <biển_số> — tra cứu; cũng có thể gửi biển số trực tiếp
/traacuu <biển_số> — bí danh của /tracuu
/logout — đóng session dùng chung
/captcha <mã> và /refresh_captcha — fallback CAPTCHA nhập tay
/help — mở hướng dẫn này

Tin nhắn username/password được bot xóa ngay và credential chỉ giữ trong RAM. Mọi yêu cầu dùng chung một hàng đợi và chỉ một job chạm website nguồn tại một thời điểm. Nếu session hết hạn, bot tự đăng nhập lại và tiếp tục tra cứu. `/logout` chờ job đang chạy xong rồi đóng nguồn và chặn các job còn lại."""

    @staticmethod
    def pending_help() -> str:
        return """TÀI KHOẢN PENDING

Bạn chưa được phép đăng nhập nguồn hoặc tra cứu.
/start — xem trạng thái hiện tại
/help — mở hướng dẫn này

Hãy chờ admin kiểm tra /users và dùng /approve <telegram_id>. Sau khi thành ACTIVE, bạn chỉ cần gửi biển số để tra cứu."""

    @staticmethod
    def blocked_help() -> str:
        return """TÀI KHOẢN BLOCKED

Tài khoản Telegram của bạn đã bị khóa; session nguồn đã bị đóng.
/start — xem trạng thái hiện tại
/help — mở hướng dẫn này

Bạn không thể /login hoặc tra cứu cho đến khi admin dùng /approve <telegram_id>."""

    @staticmethod
    def pending() -> str:
        return "Tài khoản đang chờ admin phê duyệt."

    @staticmethod
    def blocked() -> str:
        return "Tài khoản đã bị khóa."

    @staticmethod
    def approved() -> str:
        return (
            "Tài khoản đã được phê duyệt. Gửi biển số hoặc "
            "/tracuu <biển số> để tra cứu."
        )

    @staticmethod
    def busy() -> str:
        return "Hệ thống đang bận, vui lòng thử lại sau."

    @staticmethod
    def queued() -> str:
        return "Đã nhận yêu cầu tra cứu."

    @staticmethod
    def invalid_plate() -> str:
        return "Biển số không đúng định dạng."

    @staticmethod
    def source_not_ready() -> str:
        return "Session nguồn chưa sẵn sàng. Vui lòng báo admin dùng /login."

    @staticmethod
    def format_results(results: Iterable[Any]) -> str:
        blocks: list[str] = []
        for item in results:
            vehicle = getattr(item, "vehicle", item)
            expiry = getattr(vehicle, "inspection_expiry", "")
            expiry_text = expiry.strftime("%d/%m/%Y") if isinstance(expiry, date) else str(expiry)
            blocks.append(
                "\n".join(
                    (
                        f"Biển tra cứu: {getattr(item, 'queried_plate', '')}",
                        f"Loại phương tiện: {getattr(vehicle, 'vehicle_type', '')}",
                        f"Thương hiệu/Nhãn hiệu: {getattr(vehicle, 'brand', '')}",
                        f"Thời hạn kiểm định: {expiry_text}",
                    )
                )
            )
        return "\n\n".join(blocks) if blocks else "Không tìm thấy dữ liệu phương tiện."

    @staticmethod
    def format_users(users: Iterable[User]) -> str:
        rows = [
            f"{user.telegram_user_id} | {user.role.value} | {user.status.value}"
            for user in users
        ]
        return "\n".join(rows) if rows else "Chưa có user."
