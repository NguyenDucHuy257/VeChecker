"""Minimal Telegram Bot API adapter using long polling."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Any

import requests

from app.services.errors import TelegramApiError


@dataclass(slots=True, repr=False)
class TelegramBotClient:
    token: str = field(repr=False)
    timeout_seconds: float = 35.0
    session: Any = None
    _poll_session: Any = field(init=False, repr=False)
    _send_session: Any = field(init=False, repr=False)
    _send_lock: Lock = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.token.strip():
            raise ValueError("Telegram bot token cannot be empty")
        if self.session is None:
            self._poll_session = requests.Session()
            self._send_session = requests.Session()
        else:
            # Injection hook for deterministic tests. Production always uses two
            # sessions so long polling never blocks an outgoing response.
            self._poll_session = self.session
            self._send_session = self.session
        self._send_lock = Lock()

    def close(self) -> None:
        seen: set[int] = set()
        for session in (self._poll_session, self._send_session):
            if id(session) in seen:
                continue
            seen.add(id(session))
            close = getattr(session, "close", None)
            if callable(close):
                close()

    def get_updates(self, *, offset: int | None, timeout: int) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            payload["offset"] = offset
        result = self._call(
            "getUpdates",
            poll=True,
            json=payload,
            timeout=max(self.timeout_seconds, timeout + 5),
        )
        if not isinstance(result, list):
            raise TelegramApiError("Telegram getUpdates trả dữ liệu không hợp lệ.")
        return [item for item in result if isinstance(item, dict)]

    def send_message(self, chat_id: int, text: str) -> None:
        self._call("sendMessage", json={"chat_id": chat_id, "text": text})

    def send_photo(self, chat_id: int, image: bytes, *, caption: str = "") -> None:
        if not image:
            raise ValueError("Telegram photo cannot be empty")
        self._call(
            "sendPhoto",
            data={"chat_id": str(chat_id), "caption": caption},
            files={"photo": ("captcha.jpg", image, "image/jpeg")},
        )

    def _call(self, method: str, *, poll: bool = False, **kwargs: Any) -> Any:
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        kwargs.setdefault("timeout", self.timeout_seconds)
        try:
            if poll:
                response = self._poll_session.post(url, **kwargs)
            else:
                with self._send_lock:
                    response = self._send_session.post(url, **kwargs)
        except requests.RequestException as exc:
            raise TelegramApiError(f"Không kết nối được Telegram khi gọi {method}.") from exc
        if int(response.status_code) < 200 or int(response.status_code) >= 300:
            raise TelegramApiError(
                f"Telegram API trả HTTP {response.status_code} khi gọi {method}."
            )
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise TelegramApiError("Telegram API trả JSON không hợp lệ.") from exc
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            error_code = payload.get("error_code") if isinstance(payload, dict) else None
            raise TelegramApiError(
                f"Telegram API từ chối {method} (code={error_code or 'unknown'})."
            )
        return payload.get("result")
