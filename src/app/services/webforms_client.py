"""HTTP adapter for the legacy app.vr.org.vn ASP.NET WebForms pages."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from time import sleep
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag

from app.services.errors import (
    AuthenticationError,
    CaptchaImageUnavailableError,
    CaptchaInvalidError,
    InvalidPlateError,
    SessionExpiredError,
    SourceHttpError,
    SourceNetworkError,
    SourceParseError,
    SourceTimeoutError,
    VehicleNotFoundError,
)
from app.services.vr_parser import (
    LoginErrorCode,
    LookupErrorCode,
    VehicleResult,
    VrParserError,
    WebFormsState,
    decode_html,
    parse_captcha_url,
    parse_login_error,
    parse_lookup_error,
    parse_vehicle_result,
    parse_webforms_state,
)


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, repr=False)
class CaptchaChallenge:
    image_url: str


class WebFormsClient:
    """Stateful Phase 1 client. One instance must be used by one flow at a time."""

    LOGIN_PATH = "Login.aspx"
    LOOKUP_PATH = "ThongTinPT.aspx"
    CAPTCHA_DOWNLOAD_ATTEMPTS = 3
    CAPTCHA_RETRY_DELAY_SECONDS = 0.5
    LOOKUP_HTTP_ATTEMPTS = 3
    LOOKUP_RETRY_DELAY_SECONDS = 1.0
    RETRYABLE_LOOKUP_STATUSES = frozenset({500, 502, 503, 504})

    def __init__(
        self,
        *,
        base_url: str,
        username: str,
        password: str,
        timeout_seconds: float = 15.0,
        verify_ssl: bool = True,
        request_attempts: int = LOOKUP_HTTP_ATTEMPTS,
        retry_delay_seconds: float = LOOKUP_RETRY_DELAY_SECONDS,
        session: requests.Session | Any | None = None,
    ) -> None:
        if request_attempts <= 0:
            raise ValueError("request_attempts must be greater than zero")
        if retry_delay_seconds <= 0:
            raise ValueError("retry_delay_seconds must be greater than zero")
        self.base_url = base_url if base_url.endswith("/") else f"{base_url}/"
        self.username = username
        self.password = password
        self.timeout_seconds = timeout_seconds
        self.verify_ssl = verify_ssl
        self.request_attempts = request_attempts
        self.retry_delay_seconds = retry_delay_seconds
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "DKTLE/0.1 Phase1",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )
        self._login_state: WebFormsState | None = None
        self._captcha_url: str | None = None
        self._login_submit_value = "Đăng nhập"
        self.authenticated = False

    @property
    def login_url(self) -> str:
        return urljoin(self.base_url, self.LOGIN_PATH)

    @property
    def lookup_url(self) -> str:
        return urljoin(self.base_url, self.LOOKUP_PATH)

    def close(self) -> None:
        close = getattr(self.session, "close", None)
        if callable(close):
            close()

    def reset_authentication(self) -> None:
        """Drop cookies and WebForms state while retaining configured credentials."""

        cookies = getattr(self.session, "cookies", None)
        clear = getattr(cookies, "clear", None)
        if callable(clear):
            clear()
        self.authenticated = False
        self._login_state = None
        self._captcha_url = None

    def set_credentials(self, username: str, password: str) -> None:
        """Replace the shared account after clearing all previous session state."""

        username = username.strip()
        if not username or not password:
            raise ValueError("Tài khoản và mật khẩu nguồn không được để trống.")
        self.reset_authentication()
        self.username = username
        self.password = password

    def clear_credentials(self) -> None:
        """Remove the shared account from memory on an explicit admin logout."""

        self.reset_authentication()
        self.username = ""
        self.password = ""

    def start_login(self) -> CaptchaChallenge:
        self.authenticated = False
        self._login_state = None
        self._captcha_url = None
        response = self._request("GET", self.login_url)
        self._raise_for_status(response, operation="GET trang đăng nhập")
        self._update_login_form(response)
        assert self._captcha_url is not None
        return CaptchaChallenge(self._captcha_url)

    def refresh_captcha(self) -> CaptchaChallenge:
        state = self._require_login_state()
        form = state.as_form_fields()
        form.update(
            {
                "txtNguoiDung": self.username,
                "txtMatKhau": self.password,
                "txtCaptcha": "",
                "ImaRefresh.x": "1",
                "ImaRefresh.y": "1",
            }
        )
        response = self._request(
            "POST",
            self.login_url,
            data=form,
            headers=self._form_headers(self.login_url),
            allow_redirects=False,
        )
        self._raise_for_status(response, operation="POST refresh CAPTCHA")
        self._update_login_form(response)
        assert self._captcha_url is not None
        return CaptchaChallenge(self._captcha_url)

    def download_captcha(self, challenge: CaptchaChallenge | None = None) -> bytes:
        image_url = challenge.image_url if challenge else self._captcha_url
        if not image_url:
            raise SourceParseError("Trang đăng nhập chưa cung cấp ảnh CAPTCHA.")
        if not self._is_same_origin(image_url):
            raise SourceParseError("Đường dẫn CAPTCHA khác origin website nguồn.")

        response = None
        for attempt in range(1, self.CAPTCHA_DOWNLOAD_ATTEMPTS + 1):
            response = self._request("GET", image_url)
            if int(response.status_code) != 404:
                break
            if attempt < self.CAPTCHA_DOWNLOAD_ATTEMPTS:
                sleep(self.CAPTCHA_RETRY_DELAY_SECONDS * attempt)

        assert response is not None
        if int(response.status_code) == 404:
            raise CaptchaImageUnavailableError(
                "Ảnh CAPTCHA chưa sẵn sàng sau "
                f"{self.CAPTCHA_DOWNLOAD_ATTEMPTS} lần tải (HTTP 404).",
                status_code=404,
            )
        self._raise_for_status(response, operation="GET ảnh CAPTCHA")
        content = bytes(response.content)
        if not content:
            raise SourceParseError("Website trả ảnh CAPTCHA rỗng.")
        content_type = str(response.headers.get("Content-Type", "")).casefold()
        if content_type and not content_type.startswith("image/"):
            raise SourceParseError("Website không trả về nội dung ảnh CAPTCHA.")
        if not content_type and not self._has_image_signature(content):
            raise SourceParseError("Không xác định được định dạng ảnh CAPTCHA.")
        return content

    def current_captcha_challenge(self) -> CaptchaChallenge:
        """Return the current challenge after a rejected login without refreshing it."""

        if not self._captcha_url:
            raise SourceParseError("Trang đăng nhập chưa cung cấp ảnh CAPTCHA.")
        return CaptchaChallenge(self._captcha_url)

    def submit_login(self, captcha: str) -> None:
        state = self._require_login_state()
        form = state.as_form_fields()
        form.update(
            {
                "txtNguoiDung": self.username,
                "txtMatKhau": self.password,
                "txtCaptcha": captcha,
                "btnDangNhap": self._login_submit_value,
            }
        )
        response = self._request(
            "POST",
            self.login_url,
            data=form,
            headers=self._form_headers(self.login_url),
            allow_redirects=False,
        )

        if response.status_code == 302:
            location = str(response.headers.get("Location", ""))
            target = urljoin(self.login_url, location)
            if self._is_expected_redirect(target, self.LOOKUP_PATH):
                self.authenticated = True
                self._login_state = None
                self._captcha_url = None
                return
            raise AuthenticationError("Website chuyển hướng tới trang không mong đợi.")
        if 300 <= int(response.status_code) < 400:
            raise AuthenticationError(
                f"Website trả redirect đăng nhập không được hỗ trợ: HTTP {response.status_code}."
            )

        self._raise_for_status(response, operation="POST đăng nhập")
        try:
            page_error = parse_login_error(
                response.content,
                declared_encoding=response.headers.get("Content-Type"),
            )
        except VrParserError as exc:
            raise SourceParseError("Không đọc được phản hồi đăng nhập.") from exc

        if page_error and page_error.code is LoginErrorCode.CAPTCHA_INVALID:
            self._update_login_form(response)
            raise CaptchaInvalidError("CAPTCHA chưa đúng.")
        if page_error and page_error.code is LoginErrorCode.INVALID_CREDENTIALS:
            raise AuthenticationError("Tài khoản hoặc mật khẩu không đúng.")
        if page_error is not None:
            raise AuthenticationError("Website từ chối đăng nhập với lỗi chưa nhận diện.")
        # Preserve the latest form state for diagnostics/manual retry, but do not
        # classify an unknown response as a CAPTCHA error.
        self._update_login_form(response)
        raise AuthenticationError("Đăng nhập không thành công.")

    def lookup_candidate(self, plate: str) -> VehicleResult:
        if not self.authenticated:
            raise SessionExpiredError("Chưa đăng nhập hoặc phiên đã hết hạn.")

        for attempt in range(1, self.request_attempts + 1):
            try:
                return self._lookup_candidate_once(plate)
            except (SourceTimeoutError, SourceNetworkError, SourceHttpError) as exc:
                retryable = not isinstance(exc, SourceHttpError) or (
                    exc.status_code in self.RETRYABLE_LOOKUP_STATUSES
                )
                if not retryable:
                    raise
                if attempt >= self.request_attempts:
                    message = f"{exc} Đã thử {self.request_attempts} lần."
                    if not isinstance(exc, SourceHttpError):
                        raise type(exc)(message) from exc
                    raise SourceHttpError(
                        message,
                        status_code=exc.status_code,
                    ) from exc
                sleep(self.retry_delay_seconds * attempt)

        raise AssertionError("lookup retry loop ended unexpectedly")

    def _lookup_candidate_once(self, plate: str) -> VehicleResult:
        form_response = self._request("GET", self.lookup_url)
        if 300 <= int(form_response.status_code) < 400:
            self._handle_lookup_redirect(form_response)
        self._raise_for_status(form_response, operation="GET form tra cứu")
        if self._looks_like_login(form_response.content):
            self.authenticated = False
            raise SessionExpiredError("Phiên nguồn đã hết hạn.")

        try:
            state, submit_value = self._parse_lookup_form(
                form_response.content,
                declared_encoding=form_response.headers.get("Content-Type"),
            )
        except VrParserError as exc:
            raise SourceParseError("Không đọc được form tra cứu.") from exc

        form = state.as_form_fields()
        form.update({"txtBienDK": plate, "Button1": submit_value})
        result_response = self._request(
            "POST",
            self.lookup_url,
            data=form,
            headers=self._form_headers(self.lookup_url),
            allow_redirects=False,
        )

        if 300 <= int(result_response.status_code) < 400:
            self._handle_lookup_redirect(result_response)
        self._raise_for_status(result_response, operation="POST tra cứu")

        if self._looks_like_login(result_response.content):
            self.authenticated = False
            raise SessionExpiredError("Phiên nguồn đã hết hạn.")

        declared = result_response.headers.get("Content-Type")
        try:
            page_error = parse_lookup_error(
                result_response.content,
                declared_encoding=declared,
            )
            if page_error is not None:
                if page_error.code is LookupErrorCode.INVALID_PLATE:
                    raise InvalidPlateError("Biển số không đúng định dạng.")
                if page_error.code is LookupErrorCode.NOT_FOUND:
                    raise VehicleNotFoundError("Không tìm thấy dữ liệu phương tiện.")
                raise SourceParseError("Website trả lỗi tra cứu chưa nhận diện.")
            return parse_vehicle_result(
                result_response.content,
                declared_encoding=declared,
            )
        except (InvalidPlateError, VehicleNotFoundError, SourceParseError):
            raise
        except VrParserError as exc:
            raise SourceParseError("Không parse được kết quả tra cứu.") from exc

    def _update_login_form(self, response: Any) -> None:
        declared = response.headers.get("Content-Type")
        try:
            form = self._find_expected_form(
                response.content,
                declared_encoding=declared,
                expected_url=self.login_url,
                required_names=(
                    "__VIEWSTATE",
                    "__VIEWSTATEGENERATOR",
                    "__EVENTVALIDATION",
                    "txtNguoiDung",
                    "txtMatKhau",
                    "txtCaptcha",
                    "ImaRefresh",
                    "btnDangNhap",
                ),
            )
            fragment = str(form)
            state = parse_webforms_state(fragment)
            source = parse_captcha_url(
                fragment,
            )
        except VrParserError as exc:
            raise SourceParseError("Trang đăng nhập thiếu WebForms state hoặc CAPTCHA.") from exc
        captcha_url = urljoin(self.login_url, source)
        if not self._is_same_origin(captcha_url):
            raise SourceParseError("Đường dẫn CAPTCHA khác origin website nguồn.")
        submit_value = self._required_submit_value(form, "btnDangNhap")
        # Commit all related values together only after every validation succeeds.
        self._login_state = state
        self._captcha_url = captcha_url
        self._login_submit_value = submit_value

    def _parse_lookup_form(
        self,
        content: bytes | str,
        *,
        declared_encoding: str | None,
    ) -> tuple[WebFormsState, str]:
        form = self._find_expected_form(
            content,
            declared_encoding=declared_encoding,
            expected_url=self.lookup_url,
            required_names=(
                "__VIEWSTATE",
                "__VIEWSTATEGENERATOR",
                "__EVENTVALIDATION",
                "txtBienDK",
                "Button1",
            ),
        )
        state = parse_webforms_state(str(form))
        return state, self._required_submit_value(form, "Button1")

    def _require_login_state(self) -> WebFormsState:
        if self._login_state is None:
            raise SourceParseError("Chưa tải form đăng nhập.")
        return self._login_state

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        kwargs.setdefault("timeout", self.timeout_seconds)
        kwargs.setdefault("verify", self.verify_ssl)
        kwargs.setdefault("allow_redirects", False)
        try:
            return self.session.request(method, url, **kwargs)
        except requests.Timeout as exc:
            raise SourceTimeoutError("Website nguồn phản hồi quá thời gian.") from exc
        except requests.RequestException as exc:
            raise SourceNetworkError("Không kết nối được website nguồn.") from exc

    @staticmethod
    def _raise_for_status(response: Any, *, operation: str) -> None:
        status = int(response.status_code)
        if status < 200 or status >= 300:
            raise SourceHttpError(
                f"Website nguồn trả HTTP {status} khi {operation}.",
                status_code=status,
            )

    @staticmethod
    def _looks_like_login(content: bytes | str) -> bool:
        soup = BeautifulSoup(decode_html(content), "html.parser")
        return (
            soup.select_one("#txtNguoiDung") is not None
            and soup.select_one("#txtMatKhau") is not None
        )

    def _is_same_origin(self, target: str) -> bool:
        expected = urlparse(self.base_url)
        actual = urlparse(target)
        return (actual.scheme.casefold(), actual.netloc.casefold()) == (
            expected.scheme.casefold(),
            expected.netloc.casefold(),
        )

    def _is_expected_redirect(self, target: str, expected_path: str) -> bool:
        actual_path = urlparse(target).path.rstrip("/").casefold()
        expected_url = urljoin(self.base_url, expected_path)
        expected_full_path = urlparse(expected_url).path.rstrip("/").casefold()
        return self._is_same_origin(target) and actual_path == expected_full_path

    def _handle_lookup_redirect(self, response: Any) -> None:
        location = str(response.headers.get("Location", ""))
        target = urljoin(self.lookup_url, location)
        if response.status_code == 302 and self._is_expected_redirect(target, self.LOGIN_PATH):
            self.authenticated = False
            raise SessionExpiredError("Phiên nguồn đã hết hạn.")
        raise SourceHttpError(
            f"Website trả redirect tra cứu không mong đợi: HTTP {response.status_code}.",
            status_code=int(response.status_code),
        )

    def _find_expected_form(
        self,
        content: bytes | str,
        *,
        declared_encoding: str | None,
        expected_url: str,
        required_names: tuple[str, ...],
    ) -> Tag:
        soup = BeautifulSoup(decode_html(content, declared_encoding), "html.parser")
        for form in soup.find_all("form"):
            if not isinstance(form, Tag):
                continue
            if not all(form.find(attrs={"name": name}) is not None for name in required_names):
                continue
            action = str(form.get("action", "")).strip()
            target = urljoin(expected_url, action) if action else expected_url
            expected_path = urlparse(expected_url).path
            if not self._is_expected_redirect(target, expected_path):
                raise SourceParseError("Form website nguồn có action không hợp lệ.")
            return form
        raise SourceParseError("Website nguồn thiếu form hoặc control bắt buộc.")

    @staticmethod
    def _required_submit_value(form: Tag, name: str) -> str:
        element = form.find(attrs={"name": name})
        if not isinstance(element, Tag):
            raise SourceParseError(f"Form website nguồn thiếu control {name}.")
        value = str(element.get("value", "")).strip()
        if not value:
            raise SourceParseError(f"Control {name} không có giá trị submit.")
        return value

    @staticmethod
    def _has_image_signature(content: bytes) -> bool:
        return (
            content.startswith(b"\xff\xd8\xff")
            or content.startswith(b"\x89PNG\r\n\x1a\n")
            or content.startswith((b"GIF87a", b"GIF89a"))
            or (len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP")
        )

    @staticmethod
    def _form_headers(referer: str) -> dict[str, str]:
        parsed = urlparse(referer)
        return {
            "Origin": f"{parsed.scheme}://{parsed.netloc}",
            "Referer": referer,
            "Content-Type": "application/x-www-form-urlencoded",
        }
