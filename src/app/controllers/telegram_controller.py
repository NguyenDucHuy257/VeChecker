"""Telegram update routing, authorization and admin commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from time import monotonic
from typing import Any, Protocol

from app.controllers.lookup_controller import LookupController
from app.models import UserRepository, UserRole, UserStatus
from app.services.errors import SourceNotReadyError, VrServiceError
from app.services.source_pool import SourceLoginResponse, SourcePool
from app.services.worker_service import EnqueueResult, LookupJob, WorkerService
from app.views.telegram_view import TelegramView


class TelegramSender(Protocol):
    def send_message(self, chat_id: int, text: str) -> None: ...

    def send_photo(self, chat_id: int, image: bytes, *, caption: str = "") -> None: ...


@dataclass(slots=True)
class UserRateLimiter:
    minimum_interval_seconds: float
    _last_seen: dict[int, float] = field(init=False, repr=False)
    _lock: Lock = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.minimum_interval_seconds <= 0:
            raise ValueError("minimum_interval_seconds must be greater than zero")
        self._last_seen: dict[int, float] = {}
        self._lock = Lock()

    def allow(self, telegram_user_id: int) -> bool:
        now = monotonic()
        with self._lock:
            previous = self._last_seen.get(telegram_user_id)
            if previous is not None and now - previous < self.minimum_interval_seconds:
                return False
            self._last_seen[telegram_user_id] = now
        return True


class TelegramController:
    MAX_INPUT_LENGTH = 128

    def __init__(
        self,
        users: UserRepository,
        workers: WorkerService,
        source_pool: SourcePool,
        bot: TelegramSender,
        view: TelegramView,
        *,
        rate_limiter: UserRateLimiter,
    ) -> None:
        self.users = users
        self.workers = workers
        self.source_pool = source_pool
        self.bot = bot
        self.view = view
        self.rate_limiter = rate_limiter

    def handle_update(self, update: dict[str, Any]) -> None:
        update_id = update.get("update_id")
        message = update.get("message")
        if not isinstance(update_id, int) or not isinstance(message, dict):
            return
        chat = message.get("chat")
        sender = message.get("from")
        text = message.get("text")
        if not isinstance(chat, dict) or chat.get("type") != "private":
            return
        if not isinstance(sender, dict) or not isinstance(text, str):
            return
        chat_id = chat.get("id")
        telegram_user_id = sender.get("id")
        if not isinstance(chat_id, int) or not isinstance(telegram_user_id, int):
            return
        username = sender.get("username") if isinstance(sender.get("username"), str) else None
        user, _ = self.users.get_or_create_pending(
            telegram_user_id,
            telegram_username=username,
        )
        value = text.strip()
        if len(value) > self.MAX_INPUT_LENGTH:
            self.bot.send_message(chat_id, "Dữ liệu đầu vào quá dài.")
            return
        command, argument = self._parse_command(value)

        if command == "/start":
            self._send_access_state(chat_id, user.status)
            return

        if command in {
            "/approve",
            "/revoke",
            "/block",
            "/users",
            "/status",
            "/login",
            "/captcha",
            "/refresh_captcha",
        }:
            if user.role is not UserRole.ADMIN or user.status is not UserStatus.ACTIVE:
                self.bot.send_message(chat_id, "Lệnh này chỉ dành cho admin.")
                return
            self._handle_admin(command, argument, chat_id)
            return

        if user.status is UserStatus.PENDING:
            self.bot.send_message(chat_id, self.view.pending())
            return
        if user.status is UserStatus.BLOCKED:
            self.bot.send_message(chat_id, self.view.blocked())
            return

        plate = argument if command == "/tracuu" else value if not command else ""
        normalized = plate.strip().upper()
        if not normalized or not LookupController.is_valid_plate(normalized):
            self.bot.send_message(chat_id, self.view.invalid_plate())
            return
        if not self.rate_limiter.allow(telegram_user_id):
            self.bot.send_message(chat_id, "Vui lòng chờ trước khi gửi yêu cầu tiếp theo.")
            return
        if not self.source_pool.ready:
            self.bot.send_message(chat_id, self.view.source_not_ready())
            return

        outcome = self.workers.submit(
            LookupJob(
                update_id=update_id,
                telegram_user_id=telegram_user_id,
                database_user_id=user.id,
                chat_id=chat_id,
                input_plate=normalized,
            )
        )
        if outcome is EnqueueResult.ACCEPTED:
            self.bot.send_message(chat_id, self.view.queued())
        elif outcome is EnqueueResult.BUSY:
            self.bot.send_message(chat_id, self.view.busy())
        # DUPLICATE is deliberately silent: Telegram may redeliver the same update.

    def _handle_admin(self, command: str, argument: str, chat_id: int) -> None:
        if command in {"/approve", "/revoke", "/block"}:
            target_id = self._parse_target_id(argument)
            if target_id is None:
                self.bot.send_message(chat_id, f"Cú pháp: {command} <telegram_id>")
                return
            target = self.users.get_by_telegram_id(target_id)
            if target is None:
                self.bot.send_message(chat_id, "User chưa từng gửi /start cho bot.")
                return
            desired = {
                "/approve": UserStatus.ACTIVE,
                "/revoke": UserStatus.PENDING,
                "/block": UserStatus.BLOCKED,
            }[command]
            if (
                desired is not UserStatus.ACTIVE
                and target.role is UserRole.ADMIN
                and target.status is UserStatus.ACTIVE
                and self.users.count_active_admins() <= 1
            ):
                self.bot.send_message(chat_id, "Không thể vô hiệu admin ACTIVE cuối cùng.")
                return
            updated = self.users.update_status(target_id, desired)
            self.bot.send_message(
                chat_id,
                f"Đã cập nhật {updated.telegram_user_id} thành {updated.status.value}.",
            )
            return
        if command == "/users":
            self.bot.send_message(chat_id, self.view.format_users(self.users.list_all()))
            return
        if command == "/status":
            self.bot.send_message(
                chat_id,
                " | ".join(
                    (
                        f"source_ready={self.source_pool.ready}",
                        f"authenticated_workers={self.source_pool.authenticated_workers}",
                        f"queue={self.workers.pending_count}/{self.workers.queue_size}",
                    )
                ),
            )
            return
        try:
            if command == "/login":
                response = self.source_pool.start_login()
            elif command == "/captcha":
                response = self.source_pool.submit_captcha(argument)
            else:
                response = self.source_pool.refresh_captcha()
        except SourceNotReadyError as exc:
            self.bot.send_message(chat_id, str(exc))
            return
        except VrServiceError as exc:
            self.bot.send_message(
                chat_id,
                f"Thao tác với website nguồn thất bại ({exc.code.value}). Vui lòng thử lại.",
            )
            return
        self._send_login_response(chat_id, response)

    def _send_login_response(self, chat_id: int, response: SourceLoginResponse) -> None:
        self.bot.send_message(chat_id, response.message)
        if response.prompt is not None:
            prompt = response.prompt
            self.bot.send_photo(
                chat_id,
                prompt.image,
                caption=(
                    f"Worker {prompt.worker_number} | "
                    f"CAPTCHA {prompt.attempt}/{prompt.maximum}. "
                    "Trả lời bằng /captcha <mã>."
                ),
            )

    def _send_access_state(self, chat_id: int, status: UserStatus) -> None:
        if status is UserStatus.ACTIVE:
            self.bot.send_message(chat_id, self.view.approved())
        elif status is UserStatus.BLOCKED:
            self.bot.send_message(chat_id, self.view.blocked())
        else:
            self.bot.send_message(chat_id, self.view.pending())

    @staticmethod
    def _parse_command(value: str) -> tuple[str, str]:
        if not value.startswith("/"):
            return "", ""
        head, _, argument = value.partition(" ")
        command = head.split("@", 1)[0].lower()
        return command, argument.strip()

    @staticmethod
    def _parse_target_id(value: str) -> int | None:
        return int(value) if value.isdecimal() and int(value) > 0 else None
