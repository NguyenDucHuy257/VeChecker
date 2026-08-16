from app.services.telegram_api import TelegramBotClient
from app.telegram_app import create_telegram_application


class FakeSession:
    headers = {}

    def close(self):
        pass


def test_create_telegram_application_builds_isolated_worker_clients(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "VR_USERNAME=user\n"
        "VR_PASSWORD=pass\n"
        "TELEGRAM_ADMIN_IDS=1001\n"
        "TELEGRAM_BOT_TOKEN=synthetic-token\n"
        f"DATABASE_PATH={tmp_path / 'telegram.sqlite3'}\n"
        "MAX_WORKERS=2\n",
        encoding="utf-8",
    )
    bot = TelegramBotClient("synthetic-token", session=FakeSession())

    with create_telegram_application(env_file, bot=bot) as application:
        assert len(application.source_pool.clients) == 2
        assert application.source_pool.clients[0] is not application.source_pool.clients[1]
        assert application.workers.max_workers == 2
        assert application.config.telegram_bot_token == "synthetic-token"
