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

Quyền: dùng tài khoản nguồn riêng của bạn để đăng nhập và tra cứu. Bạn không thể quản lý user khác.

/start — xem trạng thái phê duyệt
/help — mở hướng dẫn này
/login — bắt đầu đăng nhập nguồn riêng
/cancel — hủy bước nhập username/password
/status — xem session của bạn và hàng đợi
/tracuu <biển_số> — gửi yêu cầu tra cứu
<biển_số> — có thể gửi trực tiếp, không cần lệnh
/logout — đóng session và xóa credential khỏi RAM
/captcha <mã> — nhập tay nếu model CAPTCHA lỗi
/refresh_captcha — đổi ảnh CAPTCHA nhập tay

Cách dùng:
1. Gửi /login.
2. Gửi username nguồn khi bot yêu cầu.
3. Gửi password khi bot yêu cầu.
4. Hai tin nhắn credential sẽ được bot xóa ngay và không lưu DB/log.
5. Khi đăng nhập thành công, tra cứu nhiều lần đến khi /logout, session hết hạn hoặc server restart.

Biển số hợp lệ: 2 số + 1 chữ + 5 số, có thể kèm T/V. Không có đuôi sẽ thử cả T và V."""

    @staticmethod
    def admin_help() -> str:
        return """HƯỚNG DẪN ADMIN

Admin có toàn bộ quyền user nhưng vẫn phải /login bằng tài khoản nguồn riêng. Admin không xem được credential, cookie hoặc session của user khác.

Lệnh quản trị:
/users — liệt kê Telegram ID, role và trạng thái
/approve <telegram_id> — chuyển user sang ACTIVE
/revoke <telegram_id> — chuyển về PENDING và đóng session nguồn ngay
/block <telegram_id> — khóa user và đóng session nguồn ngay

Không thể revoke/block admin ACTIVE cuối cùng. User phải gửi /start ít nhất một lần trước khi xuất hiện trong /users.

Lệnh sử dụng cá nhân:
/login — nhập username/password nguồn riêng
/cancel — hủy nhập credential
/status — session của bạn, tổng session active và queue
/tracuu <biển_số> — tra cứu; cũng có thể gửi biển số trực tiếp
/logout — đóng session riêng
/captcha <mã> và /refresh_captcha — fallback CAPTCHA nhập tay
/help — mở hướng dẫn này

Credential được xóa khỏi chat ngay, chỉ giữ trong RAM và mất khi logout/revoke/block/restart."""

    @staticmethod
    def pending_help() -> str:
        return """TÀI KHOẢN PENDING

Bạn chưa được phép đăng nhập nguồn hoặc tra cứu.
/start — xem trạng thái hiện tại
/help — mở hướng dẫn này

Hãy chờ admin kiểm tra /users và dùng /approve <telegram_id>. Sau khi thành ACTIVE, dùng /login với tài khoản nguồn riêng của bạn."""

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
            "Tài khoản đã được phê duyệt. Dùng /login để đăng nhập nguồn riêng, "
            "sau đó gửi biển số hoặc /tracuu <biển số>."
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
        return "Bạn chưa đăng nhập nguồn hoặc phiên đã hết hạn. Dùng /login."

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
