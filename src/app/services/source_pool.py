"""Isolated VR clients for workers plus serialized Telegram CAPTCHA login."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from threading import Lock, RLock
from typing import Callable

from app.controllers.lookup_controller import LookupController
from app.models import LookupRepository, LookupStatus
from app.services.errors import (
    CaptchaImageUnavailableError,
    CaptchaInvalidError,
    SessionExpiredError,
    SourceNotReadyError,
    VrServiceError,
)
from app.services.captcha_onnx import CaptchaModelError, CaptchaRecognizer
from app.services.webforms_client import CaptchaChallenge, WebFormsClient
from app.services.worker_service import JobHandler, LookupJob
from app.views.telegram_view import TelegramView


@dataclass(frozen=True, slots=True, repr=False)
class SourceLoginPrompt:
    worker_number: int
    image: bytes
    attempt: int
    maximum: int


@dataclass(frozen=True, slots=True, repr=False)
class SourceLoginResponse:
    message: str
    prompt: SourceLoginPrompt | None
    ready: bool


class SourcePool:
    def __init__(
        self,
        clients: list[WebFormsClient],
        lookups: LookupRepository,
        send_message: Callable[[int, str], None],
        view: TelegramView,
        *,
        candidate_delay_seconds: float = 2.0,
        serialize_requests: bool = True,
        max_captcha_attempts: int = 3,
        max_image_refreshes: int = 3,
        captcha_mode: str = "manual",
        recognizer: CaptchaRecognizer | None = None,
        confidence_threshold: float = 0.9,
    ) -> None:
        if not clients:
            raise ValueError("SourcePool requires at least one client")
        self.clients = clients
        self.lookups = lookups
        self.send_message = send_message
        self.view = view
        self.candidate_delay_seconds = candidate_delay_seconds
        self.max_captcha_attempts = max_captcha_attempts
        self.max_image_refreshes = max_image_refreshes
        if captcha_mode not in {"manual", "auto"}:
            raise ValueError("captcha_mode must be manual or auto")
        if captcha_mode == "auto" and recognizer is None:
            raise ValueError("auto CAPTCHA mode requires a recognizer")
        self.captcha_mode = captcha_mode
        self.recognizer = recognizer
        self.confidence_threshold = confidence_threshold
        self._source_lock = Lock() if serialize_requests else None
        self._login_lock = RLock()
        self._pending_index: int | None = None
        self._pending_challenge: CaptchaChallenge | None = None
        self._captcha_attempt = 1

    @property
    def ready(self) -> bool:
        return all(client.authenticated for client in self.clients)

    @property
    def authenticated_workers(self) -> int:
        return sum(1 for client in self.clients if client.authenticated)

    def close(self) -> None:
        for client in self.clients:
            client.close()

    def handler_factory(self, worker_index: int) -> JobHandler:
        if worker_index >= len(self.clients):
            raise ValueError("Worker index has no isolated source client")
        client = self.clients[worker_index]

        def handle(job: LookupJob) -> None:
            if not client.authenticated:
                self.send_message(job.chat_id, self.view.source_not_ready())
                raise SourceNotReadyError("Source worker is not authenticated")
            controller = LookupController(
                client,
                self.lookups,
                user_id=job.database_user_id,
                candidate_delay_seconds=self.candidate_delay_seconds,
            )
            guard = self._source_lock if self._source_lock is not None else nullcontext()
            try:
                with guard:
                    result = controller.lookup(job.input_plate)
            except SessionExpiredError:
                client.authenticated = False
                self.send_message(job.chat_id, self.view.source_not_ready())
                raise
            except VrServiceError:
                self.send_message(job.chat_id, "Tra cứu thất bại do nguồn tạm thời không ổn định.")
                raise

            if result.successes:
                self.send_message(job.chat_id, self.view.format_results(result.successes))
            elif result.status is LookupStatus.INVALID:
                self.send_message(job.chat_id, self.view.invalid_plate())
            else:
                self.send_message(job.chat_id, "Không tìm thấy dữ liệu phương tiện.")

        return handle

    def start_login(self) -> SourceLoginResponse:
        with self._login_lock, self._source_guard():
            if self.ready:
                return SourceLoginResponse("Tất cả worker đã đăng nhập.", None, True)
            index = self._next_unauthenticated_index()
            assert index is not None
            client = self.clients[index]
            challenge = client.start_login()
            self._pending_index = index
            self._pending_challenge = challenge
            self._captcha_attempt = 1
            prompt = self._download_prompt(index, challenge)
            response = SourceLoginResponse(
                f"Nhập CAPTCHA cho worker {index + 1}/{len(self.clients)}.",
                prompt,
                False,
            )
            return self._try_auto(response)

    def submit_captcha(self, value: str) -> SourceLoginResponse:
        with self._login_lock, self._source_guard():
            index, client = self._require_pending_login()
            captcha = value.strip()
            if not captcha:
                return SourceLoginResponse("Mã CAPTCHA không được để trống.", None, False)
            try:
                client.submit_login(captcha)
            except CaptchaInvalidError:
                if self._captcha_attempt >= self.max_captcha_attempts:
                    self._clear_pending()
                    return SourceLoginResponse(
                        "Đã nhập sai CAPTCHA quá số lần cho phép. Dùng /login để thử lại.",
                        None,
                        False,
                    )
                self._captcha_attempt += 1
                challenge = client.refresh_captcha()
                self._pending_challenge = challenge
                prompt = self._download_prompt(index, challenge)
                return SourceLoginResponse("CAPTCHA chưa đúng, đã tạo ảnh mới.", prompt, False)

            return self._advance_after_success(index, allow_auto=True)

    def refresh_captcha(self) -> SourceLoginResponse:
        with self._login_lock, self._source_guard():
            index, client = self._require_pending_login()
            challenge = client.refresh_captcha()
            self._pending_challenge = challenge
            prompt = self._download_prompt(index, challenge)
            return SourceLoginResponse("Đã làm mới CAPTCHA.", prompt, False)

    def _download_prompt(
        self,
        index: int,
        challenge: CaptchaChallenge,
    ) -> SourceLoginPrompt:
        client = self.clients[index]
        current = challenge
        for refresh_count in range(self.max_image_refreshes + 1):
            try:
                image = client.download_captcha(current)
                self._pending_challenge = current
                return SourceLoginPrompt(
                    index + 1,
                    image,
                    self._captcha_attempt,
                    self.max_captcha_attempts,
                )
            except CaptchaImageUnavailableError as exc:
                if refresh_count >= self.max_image_refreshes:
                    raise CaptchaImageUnavailableError(
                        "Website nguồn không tạo được ảnh CAPTCHA sau "
                        f"{self.max_image_refreshes} lần làm mới.",
                        status_code=exc.status_code,
                    ) from exc
                current = client.refresh_captcha()
        raise AssertionError("captcha image loop ended unexpectedly")

    def _try_auto(self, response: SourceLoginResponse) -> SourceLoginResponse:
        """Keep solving fresh challenges until the source accepts a CAPTCHA."""

        if self.captcha_mode != "auto" or response.prompt is None:
            return response
        assert self.recognizer is not None
        prompt = response.prompt
        while True:
            try:
                prediction = self.recognizer.predict(prompt.image)
            except CaptchaModelError:
                # A broken/unavailable model cannot recover by refreshing the
                # website. Reset the manual counter and preserve the same image.
                self._captcha_attempt = 1
                prompt = SourceLoginPrompt(
                    prompt.worker_number,
                    prompt.image,
                    self._captcha_attempt,
                    self.max_captcha_attempts,
                )
                return SourceLoginResponse(
                    "Không thể chạy model CAPTCHA; vui lòng nhập tay.", prompt, False
                )

            index, client = self._require_pending_login()
            if prediction.confidence < self.confidence_threshold:
                # Do not submit a weak answer. Ask the source for another image
                # and keep trying automatically; manual attempt limits do not
                # apply to this auto-login loop.
                self._captcha_attempt += 1
                challenge = client.refresh_captcha()
                self._pending_challenge = challenge
                prompt = self._download_prompt(index, challenge)
                continue

            try:
                client.submit_login(prediction.text)
            except CaptchaInvalidError:
                # The rejected login response already contains a new WebForms
                # state and CAPTCHA URL. Solve that new image immediately.
                self._captcha_attempt += 1
                current = client.current_captcha_challenge()
                self._pending_challenge = current
                prompt = self._download_prompt(index, current)
                continue
            return self._advance_after_success(index, allow_auto=True)

    def _advance_after_success(
        self,
        completed_index: int,
        *,
        allow_auto: bool,
    ) -> SourceLoginResponse:
        self._clear_pending()
        next_index = self._next_unauthenticated_index()
        if next_index is None:
            return SourceLoginResponse("Đăng nhập nguồn hoàn tất cho tất cả worker.", None, True)
        next_client = self.clients[next_index]
        challenge = next_client.start_login()
        self._pending_index = next_index
        self._pending_challenge = challenge
        self._captcha_attempt = 1
        prompt = self._download_prompt(next_index, challenge)
        response = SourceLoginResponse(
            f"Worker {completed_index + 1} đã READY. Nhập CAPTCHA cho worker {next_index + 1}.",
            prompt,
            False,
        )
        return self._try_auto(response) if allow_auto else response

    def _next_unauthenticated_index(self) -> int | None:
        return next(
            (index for index, client in enumerate(self.clients) if not client.authenticated),
            None,
        )

    def _source_guard(self):
        return self._source_lock if self._source_lock is not None else nullcontext()

    def _require_pending_login(self) -> tuple[int, WebFormsClient]:
        if self._pending_index is None or self._pending_challenge is None:
            raise SourceNotReadyError("Chưa có CAPTCHA chờ nhập. Dùng /login trước.")
        return self._pending_index, self.clients[self._pending_index]

    def _clear_pending(self) -> None:
        self._pending_index = None
        self._pending_challenge = None
        self._captcha_attempt = 1
