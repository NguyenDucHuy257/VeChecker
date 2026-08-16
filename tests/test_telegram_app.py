from app.services.telegram_api import TelegramBotClient
from app.telegram_app import create_telegram_application


class FakeSession:
    headers = {}

    def close(self):
        pass


def test_create_telegram_application_builds_one_shared_fifo_source(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TELEGRAM_ADMIN_IDS=1001\n"
        "TELEGRAM_BOT_TOKEN=synthetic-token\n"
        "VR_USERNAME=shared-account\n"
        "VR_PASSWORD=shared-password\n"
        f"DATABASE_PATH={tmp_path / 'telegram.sqlite3'}\n"
        "MAX_WORKERS=2\n",
        encoding="utf-8",
    )
    bot = TelegramBotClient("synthetic-token", session=FakeSession())

    with create_telegram_application(env_file, bot=bot) as application:
        assert application.source_pool.authenticated_users == 0
        assert len(application.source_pool.clients) == 1
        assert application.config.vr_username == "shared-account"
        assert application.config.vr_password == "shared-password"
        assert application.workers.max_workers == 1
        assert application.workers.queue_size == 20
        assert application.config.telegram_bot_token == "synthetic-token"
