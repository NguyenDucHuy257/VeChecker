"""Controller for the manual Phase 1 login flow."""

from __future__ import annotations

from typing import Protocol

from app.services.captcha_service import CaptchaFileService
from app.services.errors import (
    AuthenticationError,
    CaptchaAttemptsExceededError,
    CaptchaImageUnavailableError,
    CaptchaInvalidError,
)
from app.services.webforms_client import CaptchaChallenge, WebFormsClient


class ManualLoginView(Protocol):
    def request_captcha(self, image_path, attempt: int, maximum: int) -> str: ...

    def show_error(self, message: str) -> None: ...

    def show_ready(self) -> None: ...


class AuthController:
    def __init__(
        self,
        client: WebFormsClient,
        captcha_files: CaptchaFileService,
        view: ManualLoginView,
        *,
        max_attempts: int = 3,
        max_image_refreshes: int = 3,
    ) -> None:
        if max_attempts <= 0:
            raise ValueError("max_attempts must be greater than zero")
        if max_image_refreshes <= 0:
            raise ValueError("max_image_refreshes must be greater than zero")
        self.client = client
        self.captcha_files = captcha_files
        self.view = view
        self.max_attempts = max_attempts
        self.max_image_refreshes = max_image_refreshes

    def login_manual(self) -> None:
        challenge = self.client.start_login()
        for attempt in range(1, self.max_attempts + 1):
            captcha_text = self._request_captcha(challenge, attempt)
            if not captcha_text:
                self.view.show_error("CAPTCHA không được để trống.")
                if attempt < self.max_attempts:
                    challenge = self.client.refresh_captcha()
                continue

            try:
                self.client.submit_login(captcha_text)
            except CaptchaInvalidError:
                self.view.show_error("CAPTCHA chưa đúng.")
                if attempt < self.max_attempts:
                    challenge = self.client.refresh_captcha()
                continue
            except AuthenticationError:
                raise
            else:
                self.view.show_ready()
                return

        raise CaptchaAttemptsExceededError(
            f"Đã nhập sai hoặc bỏ trống CAPTCHA {self.max_attempts} lần."
        )

    def _request_captcha(self, challenge: CaptchaChallenge, attempt: int) -> str:
        current = challenge
        for refresh_count in range(self.max_image_refreshes + 1):
            try:
                image = self.client.download_captcha(current)
                break
            except CaptchaImageUnavailableError as exc:
                if refresh_count >= self.max_image_refreshes:
                    raise CaptchaImageUnavailableError(
                        "Website nguồn không tạo được ảnh CAPTCHA sau "
                        f"{self.max_image_refreshes} lần làm mới. "
                        "Hãy chờ một lúc rồi chạy lại.",
                        status_code=exc.status_code,
                    ) from exc
                next_refresh = refresh_count + 1
                self.view.show_error(
                    "Ảnh CAPTCHA chưa sẵn sàng, đang làm mới "
                    f"({next_refresh}/{self.max_image_refreshes})."
                )
                current = self.client.refresh_captcha()
        else:  # pragma: no cover - the bounded loop always breaks or raises
            raise AssertionError("captcha refresh loop ended unexpectedly")
        path = self.captcha_files.save(image)
        try:
            return self.view.request_captcha(path, attempt, self.max_attempts)
        finally:
            self.captcha_files.cleanup()
