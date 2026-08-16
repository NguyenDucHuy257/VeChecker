"""Long-polling loop for Telegram updates."""

from __future__ import annotations

import logging
from threading import Event

from app.controllers.telegram_controller import TelegramController
from app.services.errors import TelegramApiError
from app.services.telegram_api import TelegramBotClient


LOGGER = logging.getLogger(__name__)


class TelegramPollingService:
    def __init__(
        self,
        bot: TelegramBotClient,
        controller: TelegramController,
        *,
        poll_timeout_seconds: int = 25,
    ) -> None:
        self.bot = bot
        self.controller = controller
        self.poll_timeout_seconds = poll_timeout_seconds
        self.offset: int | None = None

    def run_forever(self, stop_event: Event | None = None) -> None:
        stop = stop_event or Event()
        while not stop.is_set():
            try:
                self.run_once()
            except TelegramApiError as exc:
                LOGGER.warning("Telegram polling error code=%s", exc.code.value)
                stop.wait(2.0)

    def run_once(self) -> int:
        updates = self.bot.get_updates(
            offset=self.offset,
            timeout=self.poll_timeout_seconds,
        )
        handled = 0
        for update in updates:
            update_id = update.get("update_id")
            if not isinstance(update_id, int):
                continue
            try:
                self.controller.handle_update(update)
            except Exception:
                LOGGER.exception("Telegram update handler failed")
            finally:
                self.offset = max(self.offset or 0, update_id + 1)
            handled += 1
        return handled
