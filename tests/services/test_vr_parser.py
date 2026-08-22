from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.services.vr_parser import (
    EmptyWebFormsFieldError,
    LoginErrorCode,
    LookupErrorCode,
    MissingCaptchaError,
    MissingWebFormsFieldError,
    PageReportedError,
    VehicleResultParseError,
    decode_html,
    parse_captcha_url,
    parse_error_message,
    parse_hidden_fields,
    parse_login_error,
    parse_lookup_error,
    parse_vehicle_result,
    parse_webforms_state,
)


FIXTURES = Path(__file__).parents[1] / "fixtures" / "sanitized"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_parse_webforms_state_and_captcha_url() -> None:
    document = fixture_bytes("login_form.html")

    state = parse_webforms_state(document)

    assert state.viewstate == "synthetic-view-state"
    assert state.viewstate_generator == "SYNTHETIC01"
    assert state.event_validation == "synthetic-event-validation"
    assert state.as_form_fields() == {
        "__VIEWSTATE": "synthetic-view-state",
        "__VIEWSTATEGENERATOR": "SYNTHETIC01",
        "__EVENTVALIDATION": "synthetic-event-validation",
    }
    assert parse_captcha_url(document) == "Images/CaptchaSynthetic001.jpg"
    assert "synthetic-view-state" not in repr(state)


def test_parse_hidden_fields_can_return_optional_fields() -> None:
    fields = parse_hidden_fields(fixture_bytes("login_form.html"))

    assert fields["optionalField"] == "optional-value"


def test_missing_webforms_state_reports_exact_fields() -> None:
    document = b'<input type="hidden" name="__VIEWSTATE" value="state">'

    with pytest.raises(MissingWebFormsFieldError) as captured:
        parse_webforms_state(document)

    assert captured.value.missing_fields == (
        "__VIEWSTATEGENERATOR",
        "__EVENTVALIDATION",
    )


def test_empty_webforms_state_is_rejected() -> None:
    document = """
    <input type="hidden" name="__VIEWSTATE" value="">
    <input type="hidden" name="__VIEWSTATEGENERATOR" value="GEN">
    <input type="hidden" name="__EVENTVALIDATION" value="VALID">
    """

    with pytest.raises(EmptyWebFormsFieldError) as captured:
        parse_webforms_state(document)

    assert captured.value.empty_fields == ("__VIEWSTATE",)


def test_missing_captcha_src_is_rejected() -> None:
    with pytest.raises(MissingCaptchaError):
        parse_captcha_url('<img id="captchaImage">')


def test_empty_error_label_has_no_error() -> None:
    document = fixture_bytes("login_form.html")

    assert parse_error_message(document) is None
    assert parse_login_error(document) is None


def test_login_captcha_error_is_classified() -> None:
    error = parse_login_error(fixture_bytes("login_captcha_error.html"))

    assert error is not None
    assert error.code is LoginErrorCode.CAPTCHA_INVALID
    assert "mã xác thực" in error.message


@pytest.mark.parametrize(
    ("message", "expected_code"),
    [
        ("Tên đăng nhập hoặc mật khẩu không đúng.", LoginErrorCode.INVALID_CREDENTIALS),
        ("Hệ thống tạm thời từ chối yêu cầu.", LoginErrorCode.UNKNOWN),
    ],
)
def test_other_login_errors_are_classified(
    message: str, expected_code: LoginErrorCode
) -> None:
    error = parse_login_error(f'<span id="lblErrMsg">{message}</span>')

    assert error is not None
    assert error.code is expected_code


def test_lookup_invalid_plate_is_classified() -> None:
    error = parse_lookup_error(fixture_bytes("lookup_invalid.html"))

    assert error is not None
    assert error.code is LookupErrorCode.INVALID_PLATE


def test_lookup_not_found_is_classified() -> None:
    error = parse_lookup_error(fixture_bytes("lookup_not_found.html"))

    assert error is not None
    assert error.code is LookupErrorCode.NOT_FOUND


def test_parse_single_inspection_result() -> None:
    result = parse_vehicle_result(fixture_bytes("lookup_success_single.html"))

    assert result.vehicle_type == "Ô tô con thử nghiệm"
    assert result.brand == "NHÃN HIỆU MẪU"
    assert result.inspection_expiry == date(2030, 1, 2)


def test_parse_multiple_rows_selects_latest_expiry() -> None:
    result = parse_vehicle_result(fixture_bytes("lookup_success_multiple.html"))

    assert result.vehicle_type == "Xe tải thử nghiệm"
    assert result.brand == "THƯƠNG HIỆU TỔNG HỢP"
    assert result.inspection_expiry == date(2031, 12, 14)


def test_inspection_expiry_column_can_change_order() -> None:
    document = """
        <span id="txtLoaiPT">Phương tiện mẫu</span>
        <span id="txtNhanHieu">Nhãn hiệu mẫu</span>
        <table id="DGKiemDinh">
          <tr><th>Thời hạn KĐ</th><th>Đơn vị</th><th>Số tem</th></tr>
          <tr><td>09/08/2034</td><td>Đơn vị A</td><td>ABC</td></tr>
        </table>
    """

    result = parse_vehicle_result(document)

    assert result.inspection_expiry == date(2034, 8, 9)


def test_mojibake_is_repaired_in_values_and_table_header() -> None:
    result = parse_vehicle_result(fixture_bytes("lookup_mojibake.html"))

    assert result.vehicle_type == "Ô tô khảo nghiệm"
    assert result.brand == "NHÃN HIỆU MẪU"
    assert result.inspection_expiry == date(2033, 8, 9)


def test_valid_utf8_wins_over_stale_declared_charset() -> None:
    document = (
        '<meta charset="iso-8859-1"><span id="value">Loại phương tiện</span>'
    ).encode("utf-8")

    decoded = decode_html(document, "text/html; charset=iso-8859-1")

    assert "Loại phương tiện" in decoded


def test_decode_html_repairs_an_already_decoded_mojibake_string() -> None:
    assert decode_html("Loáº¡i phÆ°Æ¡ng tiá»‡n") == "Loại phương tiện"


def test_decode_html_repairs_mixed_mojibake_and_correct_vietnamese() -> None:
    assert decode_html("Loáº¡i phương tiện") == "Loại phương tiện"


@pytest.mark.parametrize(
    "fixture_name",
    ["lookup_bad_expiry.html", "lookup_missing_expiry_column.html"],
)
def test_invalid_or_missing_expiry_is_a_parse_error(fixture_name: str) -> None:
    with pytest.raises(VehicleResultParseError):
        parse_vehicle_result(fixture_bytes(fixture_name))


def test_empty_inspection_table_is_a_parse_error() -> None:
    document = """
        <span id="txtLoaiPT">Phương tiện mẫu</span>
        <span id="txtNhanHieu">Nhãn hiệu mẫu</span>
        <table id="DGKiemDinh">
          <tr><td>Đơn vị</td><td>Thời hạn KĐ</td></tr>
        </table>
    """

    with pytest.raises(VehicleResultParseError, match="No valid inspection"):
        parse_vehicle_result(document)


def test_missing_mandatory_result_selector_is_a_parse_error() -> None:
    document = """
        <span id="txtLoaiPT">Phương tiện mẫu</span>
        <table id="DGKiemDinh">
          <tr><td>Thời hạn KĐ</td></tr>
          <tr><td>01/01/2030</td></tr>
        </table>
    """

    with pytest.raises(VehicleResultParseError, match="txtNhanHieu"):
        parse_vehicle_result(document)


def test_lookup_error_page_cannot_be_parsed_as_success() -> None:
    with pytest.raises(PageReportedError) as captured:
        parse_vehicle_result(fixture_bytes("lookup_invalid.html"))

    assert captured.value.error.code is LookupErrorCode.INVALID_PLATE


def test_malformed_html_is_parsed_when_required_data_is_unambiguous() -> None:
    document = """
        <span id=txtLoaiPT>Phương tiện mẫu</span>
        <span id=txtNhanHieu>Thương hiệu mẫu</span>
        <table id=DGKiemDinh>
          <tr><td>Đơn vị<td>Thời hạn KĐ
          <tr><td>Đơn vị tổng hợp<td>07/06/2032
        </table>
    """

    result = parse_vehicle_result(document)

    assert result.vehicle_type == "Phương tiện mẫu"
    assert result.brand == "Thương hiệu mẫu"
    assert result.inspection_expiry == date(2032, 6, 7)


def test_valid_dates_survive_unrelated_bad_rows() -> None:
    document = """
        <span id="txtLoaiPT">Phương tiện mẫu</span>
        <span id="txtNhanHieu">Thương hiệu mẫu</span>
        <table id="DGKiemDinh">
          <tr><td>Thời hạn KĐ</td></tr>
          <tr><td>31/02/2035</td></tr>
          <tr><td>Không xác định</td></tr>
          <tr><td>11/10/2034</td></tr>
        </table>
    """

    result = parse_vehicle_result(document)

    assert result.inspection_expiry == date(2034, 10, 11)
