"""Phase 2 Telegram application composition root."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import AppConfig, load_config
from app.controllers.telegram_controller import TelegramController, UserRateLimiter
from app.database import Database
from app.logging_config import configure_logging
from app.models import LookupRepository, TelegramUpdateRepository, UserRepository
from app.services.source_pool import UserSourcePool
from app.services.captcha_onnx import OnnxCaptchaRecognizer
from app.services.telegram_api import TelegramBotClient
from app.services.telegram_polling import TelegramPollingService
from app.services.webforms_client import WebFormsClient
from app.services.worker_service import WorkerService
from app.views.telegram_view import TelegramView


@dataclass(slots=True)
class TelegramApplication:
    config: AppConfig
    database: Database
    bot: TelegramBotClient
    source_pool: UserSourcePool
    workers: WorkerService
    controller: TelegramController
    polling: TelegramPollingService

    def close(self) -> None:
        try:
            self.workers.close()
        finally:
            try:
                self.source_pool.close()
            finally:
                self.bot.close()

    def __enter__(self) -> "TelegramApplication":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def create_telegram_application(
    env_file: str | Path = ".env",
    *,
    bot: TelegramBotClient | None = None,
) -> TelegramApplication:
    config = load_config(
        env_file,
        require_vr_credentials=False,
        require_telegram_token=True,
    )
    configure_logging(config.log_level, secrets=config.log_secrets)
    database = Database(config.database_path)
    database.initialize(config.telegram_admin_ids)
    recognizer = (
        OnnxCaptchaRecognizer(config.captcha_model_path)
        if config.captcha_mode == "auto"
        else None
    )
    telegram_bot = bot or TelegramBotClient(
        config.telegram_bot_token,
        timeout_seconds=max(35.0, config.telegram_poll_timeout_seconds + 5.0),
    )
    view = TelegramView()
    def client_factory(username: str, password: str) -> WebFormsClient:
        return WebFormsClient(
            base_url=config.vr_base_url,
            username=username,
            password=password,
            timeout_seconds=config.request_timeout_seconds,
            verify_ssl=config.verify_ssl,
            request_attempts=config.source_request_attempts,
            retry_delay_seconds=config.source_retry_delay_seconds,
        )

    source_pool = UserSourcePool(
        client_factory,
        LookupRepository(database),
        telegram_bot.send_message,
        view,
        candidate_delay_seconds=config.candidate_delay_seconds,
        serialize_requests=config.source_serialize_requests,
        max_captcha_attempts=config.max_captcha_attempts,
        captcha_mode=config.captcha_mode,
        recognizer=recognizer,
        confidence_threshold=config.captcha_confidence_threshold,
    )
    workers = WorkerService(
        source_pool.handler_factory,
        TelegramUpdateRepository(database),
        max_workers=config.max_workers,
        queue_size=config.job_queue_size,
    )
    controller = TelegramController(
        UserRepository(database),
        workers,
        source_pool,
        telegram_bot,
        view,
        rate_limiter=UserRateLimiter(config.user_rate_limit_seconds),
    )
    polling = TelegramPollingService(
        telegram_bot,
        controller,
        poll_timeout_seconds=config.telegram_poll_timeout_seconds,
    )
    return TelegramApplication(
        config,
        database,
        telegram_bot,
        source_pool,
        workers,
        controller,
        polling,
    )
