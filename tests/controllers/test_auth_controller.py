from pathlib import Path

import pytest

from app.controllers.auth_controller import AuthController
from app.services.captcha_service import CaptchaFileService
from app.services.errors import (
    AuthenticationError,
    CaptchaAttemptsExceededError,
    CaptchaImageUnavailableError,
    CaptchaInvalidError,
)
from app.services.webforms_client import CaptchaChallenge


class FakeClient:
    def __init__(self, outcomes) -> None:
        self.outcomes = list(outcomes)
        self.refresh_count = 0
        self.submitted: list[str] = []

    def start_login(self):
        return CaptchaChallenge("https://source.test/captcha-1.jpg")

    def refresh_captcha(self):
        self.refresh_count += 1
        return CaptchaChallenge(f"https://source.test/captcha-{self.refresh_count + 1}.jpg")

    def download_captcha(self, challenge):
        return b"synthetic-image"

    def submit_login(self, captcha):
        self.submitted.append(captcha)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome


class FakeView:
    def __init__(self, answers) -> None:
        self.answers = iter(answers)
        self.errors: list[str] = []
        self.ready = False

    def request_captcha(self, image_path, attempt, maximum):
        assert Path(image_path).exists()
        return next(self.answers)

    def show_error(self, message):
        self.errors.append(message)

    def show_ready(self):
        self.ready = True


def test_login_success_cleans_temporary_image(tmp_path) -> None:
    client = FakeClient([None])
    view = FakeView(["AB12"])
    files = CaptchaFileService(tmp_path)

    AuthController(client, files, view, max_attempts=3).login_manual()

    assert view.ready is True
    assert client.submitted == ["AB12"]
    assert not files.current_path.exists()


def test_bad_captcha_refreshes_before_next_attempt(tmp_path) -> None:
    client = FakeClient([CaptchaInvalidError(), None])
    view = FakeView(["BAD1", "GOOD"])

    AuthController(client, CaptchaFileService(tmp_path), view).login_manual()

    assert client.refresh_count == 1
    assert client.submitted == ["BAD1", "GOOD"]
    assert view.ready is True


def test_missing_initial_captcha_refreshes_without_consuming_human_attempt(tmp_path) -> None:
    class MissingInitialCaptchaClient(FakeClient):
        def __init__(self) -> None:
            super().__init__([None])
            self.download_count = 0

        def download_captcha(self, challenge):
            self.download_count += 1
            if self.download_count == 1:
                raise CaptchaImageUnavailableError("synthetic missing image")
            return b"synthetic-image"

    client = MissingInitialCaptchaClient()
    view = FakeView(["GOOD"])

    AuthController(client, CaptchaFileService(tmp_path), view).login_manual()

    assert client.refresh_count == 1
    assert client.download_count == 2
    assert client.submitted == ["GOOD"]
    assert view.errors == ["Ảnh CAPTCHA chưa sẵn sàng, đang làm mới (1/3)."]
    assert view.ready is True


def test_persistent_missing_captcha_stops_after_bounded_refreshes(tmp_path) -> None:
    class MissingCaptchaClient(FakeClient):
        def __init__(self) -> None:
            super().__init__([])
            self.download_count = 0

        def download_captcha(self, challenge):
            self.download_count += 1
            raise CaptchaImageUnavailableError(
                "synthetic missing image",
                status_code=404,
            )

    client = MissingCaptchaClient()
    view = FakeView(["UNUSED"])

    with pytest.raises(CaptchaImageUnavailableError, match="sau 2 lần làm mới"):
        AuthController(
            client,
            CaptchaFileService(tmp_path),
            view,
            max_image_refreshes=2,
        ).login_manual()

    assert client.download_count == 3
    assert client.refresh_count == 2
    assert client.submitted == []
    assert view.errors == [
        "Ảnh CAPTCHA chưa sẵn sàng, đang làm mới (1/2).",
        "Ảnh CAPTCHA chưa sẵn sàng, đang làm mới (2/2).",
    ]


def test_empty_or_bad_captcha_stops_at_max_attempts(tmp_path) -> None:
    client = FakeClient([CaptchaInvalidError(), CaptchaInvalidError()])
    view = FakeView(["", "BAD1", "BAD2"])

    with pytest.raises(CaptchaAttemptsExceededError):
        AuthController(
            client,
            CaptchaFileService(tmp_path),
            view,
            max_attempts=3,
        ).login_manual()

    assert client.refresh_count == 2
    assert client.submitted == ["BAD1", "BAD2"]


def test_authentication_error_does_not_retry(tmp_path) -> None:
    client = FakeClient([AuthenticationError()])
    view = FakeView(["AB12"])

    with pytest.raises(AuthenticationError):
        AuthController(client, CaptchaFileService(tmp_path), view).login_manual()

    assert client.refresh_count == 0
    assert client.submitted == ["AB12"]
