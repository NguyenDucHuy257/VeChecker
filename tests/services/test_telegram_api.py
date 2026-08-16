from typing import Any

import pytest

from app.services.errors import TelegramApiError
from app.services.telegram_api import TelegramBotClient


class FakeResponse:
    def __init__(self, payload: Any, status: int = 200) -> None:
        self.payload = payload
        self.status_code = status

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def test_long_poll_and_messages_use_expected_bot_api_contract() -> None:
    session = FakeSession(
        [
            FakeResponse({"ok": True, "result": [{"update_id": 5}]}),
            FakeResponse({"ok": True, "result": {"message_id": 1}}),
            FakeResponse({"ok": True, "result": {"message_id": 2}}),
        ]
    )
    client = TelegramBotClient("synthetic-token", session=session)

    assert client.get_updates(offset=5, timeout=25) == [{"update_id": 5}]
    client.send_message(1001, "hello")
    client.send_photo(1001, b"jpeg", caption="captcha")

    assert session.calls[0][0].endswith("/getUpdates")
    assert session.calls[0][1]["json"]["offset"] == 5
    assert session.calls[1][1]["json"] == {"chat_id": 1001, "text": "hello"}
    assert session.calls[2][1]["files"]["photo"][0] == "captcha.jpg"
    assert "synthetic-token" not in repr(client)


def test_api_error_does_not_expose_response_description() -> None:
    session = FakeSession(
        [FakeResponse({"ok": False, "error_code": 401, "description": "secret detail"})]
    )
    client = TelegramBotClient("synthetic-token", session=session)

    with pytest.raises(TelegramApiError) as captured:
        client.send_message(1, "hello")

    assert "secret detail" not in str(captured.value)
