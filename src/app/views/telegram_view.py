"""Plain-text Telegram messages; no authorization decisions live here."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any

from app.models import User


class TelegramView:
    @staticmethod
    def pending() -> str:
        return "Tài khoản đang chờ admin phê duyệt."

    @staticmethod
    def blocked() -> str:
        return "Tài khoản đã bị khóa."

    @staticmethod
    def approved() -> str:
        return "Tài khoản đã được phê duyệt. Có thể gửi biển số hoặc /tracuu <biển số>."

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
        return "Nguồn tra cứu chưa đăng nhập. Vui lòng chờ admin xử lý."

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
