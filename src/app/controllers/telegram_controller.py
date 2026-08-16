"""Telegram update routing, authorization and admin commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from time import monotonic
from typing import Any, Protocol

from app.controllers.lookup_controller import LookupController
from app.models import UserRepository, UserRole, UserStatus
from app.services.errors import SourceNotReadyError, VrServiceError
from app.services.source_pool import SourceLoginResponse, UserSourcePool
from app.services.worker_service import EnqueueResult, LookupJob, WorkerService
from app.views.telegram_view import TelegramView


class TelegramSender(Protocol):
    def send_message(self, chat_id: int, text: str) -> None: ...

    def send_photo(self, chat_id: int, image: bytes, *, caption: str = "") -> None: ...

    def delete_message(self, chat_id: int, message_id: int) -> None: ...


@dataclass(slots=True, repr=False)
class LoginDraft:
    username: str | None = None
    started_at: float = field(default_factory=monotonic)


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
        source_pool: UserSourcePool,
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
        self._login_drafts: dict[int, LoginDraft] = {}
        self._login_drafts_lock = Lock()

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
        message_id = message.get("message_id")
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

        if command == "/help":
            if user.status is UserStatus.PENDING:
                help_text = self.view.pending_help()
            elif user.status is UserStatus.BLOCKED:
                help_text = self.view.blocked_help()
            elif user.role is UserRole.ADMIN:
                help_text = self.view.admin_help()
            else:
                help_text = self.view.user_help()
            self.bot.send_message(chat_id, help_text)
            return

        if command in {
            "/approve",
            "/revoke",
            "/block",
            "/users",
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

        if command == "/logout":
            self._clear_login_draft(telegram_user_id)
            logged_out = self.source_pool.logout(telegram_user_id)
            self.bot.send_message(
                chat_id,
                "Đã đăng xuất phiên nguồn." if logged_out else "Bạn chưa đăng nhập nguồn.",
            )
            return
        if command == "/cancel":
            if self._clear_login_draft(telegram_user_id):
                self.bot.send_message(chat_id, "Đã hủy nhập thông tin đăng nhập.")
            else:
                self.bot.send_message(chat_id, "Không có thao tác đăng nhập cần hủy.")
            return
        if command == "/login":
            with self._login_drafts_lock:
                self._login_drafts[telegram_user_id] = LoginDraft()
            self.bot.send_message(
                chat_id,
                "Gửi username tài khoản nguồn. Bot sẽ xóa tin nhắn ngay sau khi nhận. "
                "Dùng /cancel để hủy.",
            )
            return
        if self._get_login_draft(telegram_user_id) is not None:
            self._handle_login_secret(
                telegram_user_id,
                chat_id,
                message_id if isinstance(message_id, int) else None,
                text,
            )
            return
        if command == "/status":
            self.bot.send_message(
                chat_id,
                " | ".join(
                    (
                        f"source_ready={self.source_pool.ready_for(telegram_user_id)}",
                        f"active_sessions={self.source_pool.authenticated_users}",
                        f"queue={self.workers.pending_count}/{self.workers.queue_size}",
                    )
                ),
            )
            return
        if command in {"/captcha", "/refresh_captcha"}:
            try:
                response = (
                    self.source_pool.submit_captcha(telegram_user_id, argument)
                    if command == "/captcha"
                    else self.source_pool.refresh_captcha(telegram_user_id)
                )
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
            return

        plate = argument if command == "/tracuu" else value if not command else ""
        normalized = plate.strip().upper()
        if not normalized or not LookupController.is_valid_plate(normalized):
            self.bot.send_message(chat_id, self.view.invalid_plate())
            return
        if not self.rate_limiter.allow(telegram_user_id):
            self.bot.send_message(chat_id, "Vui lòng chờ trước khi gửi yêu cầu tiếp theo.")
            return
        if not self.source_pool.ready_for(telegram_user_id):
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
            if desired is not UserStatus.ACTIVE:
                self._clear_login_draft(target_id)
                self.source_pool.logout(target_id)
            self.bot.send_message(
                chat_id,
                f"Đã cập nhật {updated.telegram_user_id} thành {updated.status.value}.",
            )
            return
        if command == "/users":
            self.bot.send_message(chat_id, self.view.format_users(self.users.list_all()))
            return
    def _send_login_response(self, chat_id: int, response: SourceLoginResponse) -> None:
        self.bot.send_message(chat_id, response.message)
        if response.prompt is not None:
            prompt = response.prompt
            self.bot.send_photo(
                chat_id,
                prompt.image,
                caption=(
                    f"CAPTCHA tài khoản của bạn {prompt.attempt}/{prompt.maximum}. "
                    "Trả lời bằng /captcha <mã>."
                ),
            )

    def _handle_login_secret(
        self,
        telegram_user_id: int,
        chat_id: int,
        message_id: int | None,
        secret: str,
    ) -> None:
        draft = self._get_login_draft(telegram_user_id)
        if draft is None:
            return
        if monotonic() - draft.started_at > 300:
            self._clear_login_draft(telegram_user_id)
            self._delete_sensitive_message(chat_id, message_id)
            self.bot.send_message(chat_id, "Phiên nhập đăng nhập đã hết hạn. Dùng /login lại.")
            return
        value = secret.strip()
        self._delete_sensitive_message(chat_id, message_id)
        if not value:
            self.bot.send_message(chat_id, "Giá trị không được để trống.")
            return
        if draft.username is None:
            draft.username = value
            self.bot.send_message(
                chat_id,
                "Đã nhận username. Gửi password; bot sẽ xóa tin nhắn ngay sau khi nhận.",
            )
            return

        username = draft.username
        self._clear_login_draft(telegram_user_id)
        try:
            response = self.source_pool.login(telegram_user_id, username, value)
        except VrServiceError as exc:
            self.bot.send_message(
                chat_id,
                f"Đăng nhập nguồn thất bại ({exc.code.value}). Dùng /login để thử lại.",
            )
            return
        except ValueError as exc:
            self.bot.send_message(chat_id, str(exc))
            return
        self._send_login_response(chat_id, response)

    def _delete_sensitive_message(self, chat_id: int, message_id: int | None) -> None:
        if message_id is None:
            self.bot.send_message(chat_id, "Hãy xóa thủ công tin nhắn chứa thông tin đăng nhập.")
            return
        try:
            self.bot.delete_message(chat_id, message_id)
        except Exception:
            self.bot.send_message(
                chat_id,
                "Bot không xóa được tin nhắn credential; hãy xóa thủ công ngay.",
            )

    def _get_login_draft(self, telegram_user_id: int) -> LoginDraft | None:
        with self._login_drafts_lock:
            return self._login_drafts.get(telegram_user_id)

    def _clear_login_draft(self, telegram_user_id: int) -> bool:
        with self._login_drafts_lock:
            return self._login_drafts.pop(telegram_user_id, None) is not None

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
