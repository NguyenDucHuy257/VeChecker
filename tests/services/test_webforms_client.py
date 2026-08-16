from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import requests

from app.services.errors import (
    AuthenticationError,
    CaptchaInvalidError,
    InvalidPlateError,
    SessionExpiredError,
    SourceHttpError,
    SourceNetworkError,
    SourceParseError,
    SourceTimeoutError,
    VehicleNotFoundError,
)
from app.services.webforms_client import CaptchaChallenge, WebFormsClient


FIXTURES = Path(__file__).parents[1] / "fixtures" / "sanitized"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class FakeResponse:
    def __init__(
        self,
        content: bytes = b"",
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.content = content
        self.status_code = status
        self.headers = (
            {"Content-Type": "text/html; charset=utf-8"}
            if headers is None
            else headers
        )


class FakeSession:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.headers: dict[str, str] = {}
        self.closed = False

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError("Unexpected HTTP call")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    def close(self) -> None:
        self.closed = True


def make_client(session: FakeSession) -> WebFormsClient:
    return WebFormsClient(
        base_url="https://source.test/ptpublicweb/",
        username="synthetic-user",
        password="synthetic-password",
        session=session,
    )


def test_start_login_and_download_captcha() -> None:
    session = FakeSession(
        [
            FakeResponse(fixture("login_form.html")),
            FakeResponse(b"jpeg", headers={"Content-Type": "image/jpeg"}),
        ]
    )
    client = make_client(session)

    challenge = client.start_login()
    image = client.download_captcha(challenge)

    assert challenge.image_url == (
        "https://source.test/ptpublicweb/Images/CaptchaSynthetic001.jpg"
    )
    assert image == b"jpeg"
    assert [call[0] for call in session.calls] == ["GET", "GET"]
    assert all(call[2]["allow_redirects"] is False for call in session.calls)
    assert all(call[2]["timeout"] == 15.0 for call in session.calls)
    assert all(call[2]["verify"] is True for call in session.calls)


def test_captcha_download_retries_transient_404(monkeypatch: pytest.MonkeyPatch) -> None:
    delays: list[float] = []
    monkeypatch.setattr("app.services.webforms_client.sleep", delays.append)
    session = FakeSession(
        [
            FakeResponse(status=404),
            FakeResponse(status=404),
            FakeResponse(b"jpeg", headers={"Content-Type": "image/jpeg"}),
        ]
    )
    client = make_client(session)

    image = client.download_captcha(
        CaptchaChallenge(
            "https://source.test/ptpublicweb/Images/CaptchaSynthetic002.jpg"
        )
    )

    assert image == b"jpeg"
    assert delays == [0.5, 1.0]
    assert [call[0] for call in session.calls] == ["GET", "GET", "GET"]


def test_captcha_download_reports_persistent_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.webforms_client.sleep", lambda _: None)
    session = FakeSession([FakeResponse(status=404) for _ in range(3)])
    client = make_client(session)

    with pytest.raises(SourceHttpError, match="3 lần tải.*404"):
        client.download_captcha(
            CaptchaChallenge(
                "https://source.test/ptpublicweb/Images/CaptchaSynthetic002.jpg"
            )
        )

    assert len(session.calls) == 3


def test_refresh_uses_latest_raw_state_then_submit_uses_refreshed_state() -> None:
    session = FakeSession(
        [
            FakeResponse(fixture("login_form.html")),
            FakeResponse(fixture("login_refreshed.html")),
            FakeResponse(
                status=302,
                headers={"Location": "/ptpublicweb/ThongTinPT.aspx"},
            ),
        ]
    )
    client = make_client(session)

    client.start_login()
    client.refresh_captcha()
    client.submit_login("AB12")

    refresh_data = session.calls[1][2]["data"]
    assert refresh_data["__VIEWSTATE"] == "synthetic-view-state"
    assert refresh_data["__EVENTVALIDATION"] == "synthetic-event-validation"
    assert "btnDangNhap" not in refresh_data
    assert refresh_data["ImaRefresh.x"] == "1"
    submit_data = session.calls[2][2]["data"]
    assert submit_data["__VIEWSTATE"] == "refreshed-synthetic-view-state"
    assert submit_data["__EVENTVALIDATION"] == "refreshed-synthetic-validation"
    assert "ImaRefresh.x" not in submit_data
    assert submit_data["txtCaptcha"] == "AB12"
    assert client.authenticated is True


def test_bad_captcha_updates_state_for_required_refresh() -> None:
    session = FakeSession(
        [
            FakeResponse(fixture("login_form.html")),
            FakeResponse(fixture("login_captcha_error.html")),
            FakeResponse(fixture("login_refreshed.html")),
        ]
    )
    client = make_client(session)
    client.start_login()

    with pytest.raises(CaptchaInvalidError):
        client.submit_login("WRONG")
    refreshed = client.refresh_captcha()

    refresh_data = session.calls[2][2]["data"]
    assert refresh_data["__VIEWSTATE"] == "new-synthetic-view-state"
    assert refreshed.image_url.endswith("CaptchaSynthetic002.jpg")


def test_login_rejects_external_redirect() -> None:
    session = FakeSession(
        [
            FakeResponse(fixture("login_form.html")),
            FakeResponse(
                status=302,
                headers={"Location": "https://other.test/ptpublicweb/ThongTinPT.aspx"},
            ),
        ]
    )
    client = make_client(session)
    client.start_login()

    with pytest.raises(AuthenticationError):
        client.submit_login("AB12")


@pytest.mark.parametrize("status", [301, 303, 307, 308])
def test_login_accepts_only_har_confirmed_302(status: int) -> None:
    session = FakeSession(
        [
            FakeResponse(fixture("login_form.html")),
            FakeResponse(
                status=status,
                headers={"Location": "/ptpublicweb/ThongTinPT.aspx"},
            ),
        ]
    )
    client = make_client(session)
    client.start_login()

    with pytest.raises(AuthenticationError):
        client.submit_login("AB12")


def test_login_credential_error_does_not_require_a_new_captcha_form() -> None:
    credential_error = (
        '<span id="lblErrMsg">Tên đăng nhập hoặc mật khẩu không đúng.</span>'.encode(
            "utf-8"
        )
    )
    session = FakeSession(
        [FakeResponse(fixture("login_form.html")), FakeResponse(credential_error)]
    )
    client = make_client(session)
    client.start_login()

    with pytest.raises(AuthenticationError, match="mật khẩu"):
        client.submit_login("AB12")


def test_captcha_response_must_be_image() -> None:
    session = FakeSession(
        [
            FakeResponse(fixture("login_form.html")),
            FakeResponse(b"<html></html>", headers={"Content-Type": "text/html"}),
        ]
    )
    client = make_client(session)
    challenge = client.start_login()

    with pytest.raises(SourceParseError):
        client.download_captcha(challenge)


def test_captcha_challenge_cannot_leave_source_origin() -> None:
    client = make_client(FakeSession([]))

    with pytest.raises(SourceParseError):
        client.download_captcha(CaptchaChallenge("https://other.test/captcha.jpg"))


def test_captcha_without_content_type_requires_image_signature() -> None:
    session = FakeSession(
        [
            FakeResponse(fixture("login_form.html")),
            FakeResponse(b"not-an-image", headers={}),
        ]
    )
    client = make_client(session)
    challenge = client.start_login()

    with pytest.raises(SourceParseError):
        client.download_captcha(challenge)


def test_lookup_success_uses_fresh_form_state_and_raw_plate() -> None:
    session = FakeSession(
        [
            FakeResponse(fixture("lookup_form.html")),
            FakeResponse(fixture("lookup_success_multiple.html")),
        ]
    )
    client = make_client(session)
    client.authenticated = True

    result = client.lookup_candidate("00A00000T")

    assert result.vehicle_type == "Xe tải thử nghiệm"
    assert result.brand == "THƯƠNG HIỆU TỔNG HỢP"
    assert result.inspection_expiry.isoformat() == "2031-12-14"
    payload = session.calls[1][2]["data"]
    assert payload["txtBienDK"] == "00A00000T"
    assert payload["__VIEWSTATE"] == "lookup-synthetic-state"
    assert [call[0] for call in session.calls] == ["GET", "POST"]
    assert session.calls[1][2]["allow_redirects"] is False


def test_lookup_four_digit_plate_preserves_lowercase_source_payload() -> None:
    session = FakeSession(
        [
            FakeResponse(fixture("lookup_form.html")),
            FakeResponse(fixture("lookup_success_single.html")),
        ]
    )
    client = make_client(session)
    client.authenticated = True

    client.lookup_candidate("37s3456")

    payload = session.calls[1][2]["data"]
    assert payload["txtBienDK"] == "37s3456"
    assert payload["__VIEWSTATE"] == "lookup-synthetic-state"
    assert payload["__VIEWSTATEGENERATOR"] == "LOOKUP01"
    assert payload["__EVENTVALIDATION"] == "lookup-synthetic-validation"


def test_lookup_500_retries_with_a_fresh_get_and_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delays: list[float] = []
    monkeypatch.setattr("app.services.webforms_client.sleep", delays.append)
    retry_form = fixture("lookup_form.html").replace(
        b"lookup-synthetic-state",
        b"retry-lookup-state",
    )
    session = FakeSession(
        [
            FakeResponse(fixture("lookup_form.html")),
            FakeResponse(status=500),
            FakeResponse(retry_form),
            FakeResponse(fixture("lookup_success_single.html")),
        ]
    )
    client = make_client(session)
    client.authenticated = True

    result = client.lookup_candidate("00A00000T")

    assert result.brand == "NHÃN HIỆU MẪU"
    assert [call[0] for call in session.calls] == ["GET", "POST", "GET", "POST"]
    assert session.calls[1][2]["data"]["__VIEWSTATE"] == "lookup-synthetic-state"
    assert session.calls[3][2]["data"]["__VIEWSTATE"] == "retry-lookup-state"
    assert delays == [1.0]


@pytest.mark.parametrize(
    "failure",
    [requests.ConnectTimeout("connect"), requests.ReadTimeout("read")],
)
def test_lookup_timeout_retries_with_fresh_request(
    monkeypatch: pytest.MonkeyPatch, failure: requests.RequestException
) -> None:
    delays: list[float] = []
    monkeypatch.setattr("app.services.webforms_client.sleep", delays.append)
    session = FakeSession(
        [
            failure,
            FakeResponse(fixture("lookup_form.html")),
            FakeResponse(fixture("lookup_success_single.html")),
        ]
    )
    client = make_client(session)
    client.authenticated = True

    result = client.lookup_candidate("00A00000T")

    assert result.brand == "NHÃN HIỆU MẪU"
    assert [call[0] for call in session.calls] == ["GET", "GET", "POST"]
    assert delays == [1.0]


def test_lookup_persistent_network_error_uses_configured_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delays: list[float] = []
    monkeypatch.setattr("app.services.webforms_client.sleep", delays.append)
    session = FakeSession([requests.ConnectionError("offline") for _ in range(2)])
    client = WebFormsClient(
        base_url="https://source.test/ptpublicweb/",
        username="synthetic-user",
        password="synthetic-password",
        request_attempts=2,
        retry_delay_seconds=0.25,
        session=session,
    )
    client.authenticated = True

    with pytest.raises(SourceNetworkError, match="Đã thử 2 lần"):
        client.lookup_candidate("00A00000T")

    assert len(session.calls) == 2
    assert delays == [0.25]


def test_lookup_persistent_500_stops_after_three_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delays: list[float] = []
    monkeypatch.setattr("app.services.webforms_client.sleep", delays.append)
    session = FakeSession([FakeResponse(status=500) for _ in range(3)])
    client = make_client(session)
    client.authenticated = True

    with pytest.raises(SourceHttpError) as captured:
        client.lookup_candidate("00A00000T")

    assert captured.value.status_code == 500
    assert "GET form tra cứu" in str(captured.value)
    assert "Đã thử 3 lần" in str(captured.value)
    assert [call[0] for call in session.calls] == ["GET", "GET", "GET"]
    assert delays == [1.0, 2.0]


def test_lookup_persistent_post_500_reports_the_failed_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.webforms_client.sleep", lambda _: None)
    responses = []
    for _ in range(3):
        responses.extend(
            [FakeResponse(fixture("lookup_form.html")), FakeResponse(status=500)]
        )
    session = FakeSession(responses)
    client = make_client(session)
    client.authenticated = True

    with pytest.raises(SourceHttpError) as captured:
        client.lookup_candidate("00A00000T")

    assert captured.value.status_code == 500
    assert "POST tra cứu" in str(captured.value)
    assert "Đã thử 3 lần" in str(captured.value)
    assert [call[0] for call in session.calls] == [
        "GET",
        "POST",
        "GET",
        "POST",
        "GET",
        "POST",
    ]


def test_lookup_400_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    delays: list[float] = []
    monkeypatch.setattr("app.services.webforms_client.sleep", delays.append)
    session = FakeSession([FakeResponse(status=400)])
    client = make_client(session)
    client.authenticated = True

    with pytest.raises(SourceHttpError) as captured:
        client.lookup_candidate("00A00000T")

    assert captured.value.status_code == 400
    assert len(session.calls) == 1
    assert delays == []


@pytest.mark.parametrize(
    ("fixture_name", "exception_type"),
    [
        ("lookup_invalid.html", InvalidPlateError),
        ("lookup_not_found.html", VehicleNotFoundError),
    ],
)
def test_lookup_page_errors_are_classified(fixture_name, exception_type) -> None:
    session = FakeSession(
        [FakeResponse(fixture("lookup_form.html")), FakeResponse(fixture(fixture_name))]
    )
    client = make_client(session)
    client.authenticated = True

    with pytest.raises(exception_type):
        client.lookup_candidate("00A00000T")


def test_lookup_detects_session_expiry() -> None:
    session = FakeSession([FakeResponse(fixture("login_form.html"))])
    client = make_client(session)
    client.authenticated = True

    with pytest.raises(SessionExpiredError):
        client.lookup_candidate("00A00000T")
    assert client.authenticated is False


def test_lookup_detects_session_expiry_after_post() -> None:
    session = FakeSession(
        [FakeResponse(fixture("lookup_form.html")), FakeResponse(fixture("login_form.html"))]
    )
    client = make_client(session)
    client.authenticated = True

    with pytest.raises(SessionExpiredError):
        client.lookup_candidate("00A00000T")

    assert client.authenticated is False


def test_empty_lookup_response_fails_closed_without_retry() -> None:
    session = FakeSession([FakeResponse(b"")])
    client = make_client(session)
    client.authenticated = True

    with pytest.raises(SourceParseError):
        client.lookup_candidate("00A00000T")

    assert len(session.calls) == 1


def test_lookup_302_to_login_marks_session_expired() -> None:
    session = FakeSession(
        [
            FakeResponse(
                status=302,
                headers={"Location": "/ptpublicweb/Login.aspx"},
            )
        ]
    )
    client = make_client(session)
    client.authenticated = True

    with pytest.raises(SessionExpiredError):
        client.lookup_candidate("00A00000T")


def test_lookup_rejects_unexpected_redirect() -> None:
    session = FakeSession(
        [
            FakeResponse(fixture("lookup_form.html")),
            FakeResponse(status=302, headers={"Location": "/unexpected.aspx"}),
        ]
    )
    client = make_client(session)
    client.authenticated = True

    with pytest.raises(SourceHttpError):
        client.lookup_candidate("00A00000T")


def test_two_candidates_each_get_a_fresh_form() -> None:
    session = FakeSession(
        [
            FakeResponse(fixture("lookup_form.html")),
            FakeResponse(fixture("lookup_success_single.html")),
            FakeResponse(fixture("lookup_form.html")),
            FakeResponse(fixture("lookup_success_single.html")),
        ]
    )
    client = make_client(session)
    client.authenticated = True

    client.lookup_candidate("00A00000T")
    client.lookup_candidate("00A00000V")

    assert [call[0] for call in session.calls] == ["GET", "POST", "GET", "POST"]
    assert session.calls[1][2]["data"]["txtBienDK"] == "00A00000T"
    assert session.calls[3][2]["data"]["txtBienDK"] == "00A00000V"


def test_login_and_lookup_forms_require_expected_controls() -> None:
    bad_login = fixture("login_form.html").replace(
        b'name="txtCaptcha"', b'name="removedCaptcha"'
    )
    client = make_client(FakeSession([FakeResponse(bad_login)]))
    with pytest.raises(SourceParseError):
        client.start_login()

    bad_lookup = fixture("lookup_form.html").replace(
        b'name="Button1"', b'name="removedButton"'
    )
    client = make_client(FakeSession([FakeResponse(bad_lookup)]))
    client.authenticated = True
    with pytest.raises(SourceParseError):
        client.lookup_candidate("00A00000T")


def test_timeout_maps_to_stable_error() -> None:
    client = make_client(FakeSession([requests.Timeout("synthetic timeout")]))

    with pytest.raises(SourceTimeoutError):
        client.start_login()


def test_close_closes_injected_session() -> None:
    session = FakeSession([])
    client = make_client(session)

    client.close()

    assert session.closed is True


def test_reset_authentication_clears_cookies_but_keeps_client_reusable() -> None:
    session = requests.Session()
    session.cookies.set("ASP.NET_SessionId", "synthetic-cookie")
    client = make_client(session)
    client.authenticated = True

    client.reset_authentication()

    assert client.authenticated is False
    assert len(session.cookies) == 0
    assert client.username == "synthetic-user"

    client.set_credentials("replacement-user", "replacement-password")
    assert client.username == "replacement-user"
    client.clear_credentials()
    assert client.username == ""
    assert client.password == ""
