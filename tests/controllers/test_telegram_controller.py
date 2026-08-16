from dataclasses import dataclass

from app.controllers.telegram_controller import TelegramController, UserRateLimiter
from app.database import Database
from app.models import UserRepository, UserStatus
from app.services.source_pool import SourceLoginPrompt, SourceLoginResponse
from app.services.worker_service import EnqueueResult
from app.views.telegram_view import TelegramView


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []
        self.photos: list[tuple[int, bytes, str]] = []
        self.deleted: list[tuple[int, int]] = []

    def send_message(self, chat_id, text):
        self.messages.append((chat_id, text))

    def send_photo(self, chat_id, image, *, caption=""):
        self.photos.append((chat_id, image, caption))

    def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))


class FakeWorkers:
    queue_size = 2
    pending_count = 0

    def __init__(self, outcome=EnqueueResult.ACCEPTED) -> None:
        self.outcome = outcome
        self.jobs = []

    def submit(self, job):
        self.jobs.append(job)
        return self.outcome


class FakeSource:
    def __init__(self, *, ready=True) -> None:
        self.ready = ready
        self.authenticated_users = 1 if ready else 0
        self.login_count = 0
        self.logout_count = 0

    def ready_for(self, _telegram_user_id):
        return self.ready

    def login(self, username, password):
        self.login_count += 1
        self.last_credentials = (username, password)
        self.ready = True
        self.authenticated_users = 1
        return SourceLoginResponse("ready", None, True)

    def submit_captcha(self, value):
        return SourceLoginResponse("ready", None, True)

    def refresh_captcha(self):
        return SourceLoginResponse(
            "refreshed",
            SourceLoginPrompt(1, b"new-image", 1, 3),
            False,
        )

    def logout(self):
        self.logout_count += 1
        was_ready = self.ready
        self.ready = False
        self.authenticated_users = 0
        return was_ready


def telegram_update(update_id, user_id, text, *, chat_type="private"):
    return {
        "update_id": update_id,
        "message": {
            "chat": {"id": user_id, "type": chat_type},
            "from": {"id": user_id, "username": f"user{user_id}"},
            "message_id": update_id,
            "text": text,
        },
    }


def make_controller(tmp_path, *, source_ready=True, worker_outcome=EnqueueResult.ACCEPTED):
    database = Database(tmp_path / "telegram.sqlite3")
    database.initialize([1])
    users = UserRepository(database)
    workers = FakeWorkers(worker_outcome)
    source = FakeSource(ready=source_ready)
    bot = FakeBot()
    controller = TelegramController(
        users,
        workers,
        source,
        bot,
        TelegramView(),
        rate_limiter=UserRateLimiter(0.001),
    )
    return controller, users, workers, source, bot


def test_new_user_is_pending_and_cannot_enqueue(tmp_path) -> None:
    controller, users, workers, _, bot = make_controller(tmp_path)

    controller.handle_update(telegram_update(1, 2, "/start"))
    controller.handle_update(telegram_update(2, 2, "00A00000T"))

    assert users.get_by_telegram_id(2).status is UserStatus.PENDING
    assert workers.jobs == []
    assert bot.messages[-1][1] == TelegramView.pending()


def test_admin_approves_user_and_direct_plate_is_enqueued(tmp_path) -> None:
    controller, users, workers, _, bot = make_controller(tmp_path)
    controller.handle_update(telegram_update(1, 2, "/start"))

    controller.handle_update(telegram_update(2, 1, "/approve 2"))
    controller.handle_update(telegram_update(3, 2, "00a00000t"))

    assert users.get_by_telegram_id(2).status is UserStatus.ACTIVE
    assert len(workers.jobs) == 1
    assert workers.jobs[0].chat_id == 2
    assert workers.jobs[0].input_plate == "00A00000T"
    assert bot.messages[-1][1] == TelegramView.queued()


def test_traacuu_alias_is_enqueued_for_active_user(tmp_path) -> None:
    controller, users, workers, _, _ = make_controller(tmp_path)
    users.get_or_create_pending(2)
    users.update_status(2, UserStatus.ACTIVE)

    controller.handle_update(telegram_update(1, 2, "/traacuu 00A00000T"))

    assert len(workers.jobs) == 1
    assert workers.jobs[0].input_plate == "00A00000T"


def test_revoke_and_block_take_effect_immediately(tmp_path) -> None:
    controller, users, workers, source, _ = make_controller(tmp_path)
    users.get_or_create_pending(2)
    users.update_status(2, UserStatus.ACTIVE)

    controller.handle_update(telegram_update(1, 1, "/revoke 2"))
    controller.handle_update(telegram_update(2, 2, "/tracuu 00A00000T"))
    controller.handle_update(telegram_update(3, 1, "/block 2"))
    controller.handle_update(telegram_update(4, 2, "00A00000T"))

    assert workers.jobs == []
    assert users.get_by_telegram_id(2).status is UserStatus.BLOCKED
    assert source.logout_count == 0


def test_last_active_admin_cannot_be_blocked(tmp_path) -> None:
    controller, users, _, _, bot = make_controller(tmp_path)

    controller.handle_update(telegram_update(1, 1, "/block 1"))

    assert users.get_by_telegram_id(1).status is UserStatus.ACTIVE
    assert "admin ACTIVE cuối cùng" in bot.messages[-1][1]


def test_invalid_input_and_source_not_ready_do_not_enqueue(tmp_path) -> None:
    controller, users, workers, source, bot = make_controller(tmp_path, source_ready=False)
    users.get_or_create_pending(2)
    users.update_status(2, UserStatus.ACTIVE)

    controller.handle_update(telegram_update(1, 2, "BAD"))
    controller.handle_update(telegram_update(2, 2, "00A00000T"))

    assert workers.jobs == []
    assert bot.messages[-2][1] == TelegramView.invalid_plate()
    assert bot.messages[-1][1] == TelegramView.source_not_ready()


def test_queue_full_returns_busy(tmp_path) -> None:
    controller, users, workers, _, bot = make_controller(
        tmp_path,
        worker_outcome=EnqueueResult.BUSY,
    )
    users.get_or_create_pending(2)
    users.update_status(2, UserStatus.ACTIVE)

    controller.handle_update(telegram_update(1, 2, "/tracuu 00A00000T"))

    assert len(workers.jobs) == 1
    assert bot.messages[-1][1] == TelegramView.busy()


def test_only_admin_can_login_and_logout_shared_source(tmp_path) -> None:
    controller, users, _, _, bot = make_controller(tmp_path, source_ready=False)
    users.get_or_create_pending(2)
    users.update_status(2, UserStatus.ACTIVE)

    controller.handle_update(telegram_update(1, 2, "/login"))
    controller.handle_update(telegram_update(2, 2, "/logout"))
    controller.handle_update(telegram_update(3, 1, "/login"))
    controller.handle_update(telegram_update(4, 1, "shared-user"))
    controller.handle_update(telegram_update(5, 1, "shared-password"))
    controller.handle_update(telegram_update(6, 1, "/logout"))

    source = controller.source_pool
    assert source.login_count == 1
    assert source.last_credentials == ("shared-user", "shared-password")
    assert source.logout_count == 1
    assert bot.deleted == [(1, 4), (1, 5)]
    assert bot.messages[0][1] == "Lệnh này chỉ dành cho admin."
    assert bot.messages[1][1] == "Lệnh này chỉ dành cho admin."
    assert bot.messages[-1][1] == "Đã đăng xuất phiên nguồn."


def test_pending_user_cannot_start_source_login(tmp_path) -> None:
    controller, _, _, source, bot = make_controller(tmp_path, source_ready=False)

    controller.handle_update(telegram_update(1, 2, "/login"))

    assert source.login_count == 0
    assert bot.messages[-1][1] == TelegramView.pending()


def test_help_is_selected_by_role_and_access_state(tmp_path) -> None:
    controller, users, _, _, bot = make_controller(tmp_path)
    users.get_or_create_pending(2)
    users.get_or_create_pending(3)
    users.update_status(3, UserStatus.BLOCKED)
    users.get_or_create_pending(4)
    users.update_status(4, UserStatus.ACTIVE)

    controller.handle_update(telegram_update(1, 1, "/help"))
    controller.handle_update(telegram_update(2, 2, "/help"))
    controller.handle_update(telegram_update(3, 3, "/help"))
    controller.handle_update(telegram_update(4, 4, "/help"))

    assert bot.messages[0][1] == TelegramView.admin_help()
    assert bot.messages[1][1] == TelegramView.pending_help()
    assert bot.messages[2][1] == TelegramView.blocked_help()
    assert bot.messages[3][1] == TelegramView.user_help()


def test_group_updates_are_ignored(tmp_path) -> None:
    controller, users, workers, _, bot = make_controller(tmp_path)

    controller.handle_update(telegram_update(1, 2, "/start", chat_type="group"))

    assert users.get_by_telegram_id(2) is None
    assert workers.jobs == []
    assert bot.messages == []


def test_oversized_private_input_is_rejected_before_enqueue(tmp_path) -> None:
    controller, users, workers, _, bot = make_controller(tmp_path)
    users.get_or_create_pending(2)
    users.update_status(2, UserStatus.ACTIVE)

    controller.handle_update(telegram_update(1, 2, "A" * 129))

    assert workers.jobs == []
    assert bot.messages[-1][1] == "Dữ liệu đầu vào quá dài."
