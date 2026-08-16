"""Application composition root. Phase 1 is invoked by Python scripts only."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import AppConfig, load_config
from app.controllers.auth_controller import AuthController
from app.controllers.lookup_controller import LookupController
from app.database import Database
from app.logging_config import configure_logging
from app.models import LookupRepository
from app.services.captcha_service import CaptchaFileService
from app.services.webforms_client import WebFormsClient
from app.views.script_view import ScriptView


@dataclass(slots=True)
class Application:
    config: AppConfig
    database: Database
    client: WebFormsClient
    view: ScriptView
    auth: AuthController
    lookups: LookupController

    def close(self) -> None:
        try:
            self.client.close()
        finally:
            CaptchaFileService(self.config.captcha_dir).cleanup()

    def __enter__(self) -> "Application":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def create_application(
    env_file: str | Path = ".env",
    *,
    view: ScriptView | None = None,
) -> Application:
    config = load_config(env_file)
    configure_logging(config.log_level, secrets=config.log_secrets)
    database = Database(config.database_path)
    database.initialize(config.telegram_admin_ids)
    script_view = view or ScriptView()
    client = WebFormsClient(
        base_url=config.vr_base_url,
        username=config.vr_username,
        password=config.vr_password,
        timeout_seconds=config.request_timeout_seconds,
        verify_ssl=config.verify_ssl,
        request_attempts=config.source_request_attempts,
        retry_delay_seconds=config.source_retry_delay_seconds,
    )
    captcha_files = CaptchaFileService(config.captcha_dir)
    captcha_files.cleanup()
    return Application(
        config=config,
        database=database,
        client=client,
        view=script_view,
        auth=AuthController(
            client,
            captcha_files,
            script_view,
            max_attempts=config.max_captcha_attempts,
        ),
        lookups=LookupController(
            client,
            LookupRepository(database),
            candidate_delay_seconds=config.candidate_delay_seconds,
        ),
    )
