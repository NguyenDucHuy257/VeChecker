"""Stable service errors shared by controllers and scripts."""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    CONFIG_ERROR = "CONFIG_ERROR"
    CAPTCHA_INVALID = "CAPTCHA_INVALID"
    CAPTCHA_ATTEMPTS_EXCEEDED = "CAPTCHA_ATTEMPTS_EXCEEDED"
    AUTH_FAILED = "AUTH_FAILED"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    INVALID_PLATE = "INVALID_PLATE"
    NOT_FOUND = "NOT_FOUND"
    PARSE_ERROR = "PARSE_ERROR"
    SOURCE_TIMEOUT = "SOURCE_TIMEOUT"
    SOURCE_NETWORK_ERROR = "SOURCE_NETWORK_ERROR"
    SOURCE_HTTP_ERROR = "SOURCE_HTTP_ERROR"
    SOURCE_ERROR = "SOURCE_ERROR"
    TELEGRAM_API_ERROR = "TELEGRAM_API_ERROR"
    SOURCE_NOT_READY = "SOURCE_NOT_READY"


class VrServiceError(RuntimeError):
    """Base exception that is safe for controller-level classification."""

    code = ErrorCode.SOURCE_ERROR
    retryable = False

    def __init__(self, message: str = "") -> None:
        super().__init__(message or self.code.value)


class CaptchaInvalidError(VrServiceError):
    code = ErrorCode.CAPTCHA_INVALID


class CaptchaAttemptsExceededError(VrServiceError):
    code = ErrorCode.CAPTCHA_ATTEMPTS_EXCEEDED


class AuthenticationError(VrServiceError):
    code = ErrorCode.AUTH_FAILED


class SessionExpiredError(VrServiceError):
    code = ErrorCode.SESSION_EXPIRED


class InvalidPlateError(VrServiceError):
    code = ErrorCode.INVALID_PLATE


class VehicleNotFoundError(VrServiceError):
    code = ErrorCode.NOT_FOUND


class SourceParseError(VrServiceError):
    code = ErrorCode.PARSE_ERROR


class SourceTimeoutError(VrServiceError):
    code = ErrorCode.SOURCE_TIMEOUT
    retryable = True


class SourceNetworkError(VrServiceError):
    code = ErrorCode.SOURCE_NETWORK_ERROR
    retryable = True


class SourceHttpError(VrServiceError):
    code = ErrorCode.SOURCE_HTTP_ERROR

    def __init__(self, message: str = "", *, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


class CaptchaImageUnavailableError(SourceHttpError):
    """The source returned a CAPTCHA path whose image is not available yet."""

    retryable = True


class TelegramApiError(VrServiceError):
    code = ErrorCode.TELEGRAM_API_ERROR
    retryable = True


class SourceNotReadyError(VrServiceError):
    code = ErrorCode.SOURCE_NOT_READY
