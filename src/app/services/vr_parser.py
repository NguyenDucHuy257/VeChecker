"""Pure HTML parsing helpers for the VR WebForms pages.

This module deliberately has no HTTP, database, or presentation concerns.  It
accepts response bodies and returns small immutable values that can be consumed
by the WebForms client and controllers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
import re
import unicodedata
from collections.abc import Iterable

from bs4 import BeautifulSoup, UnicodeDammit
from bs4.element import Tag


HTMLDocument = bytes | str
UNKNOWN_VEHICLE_TYPE = "Không có dữ liệu"

WEBFORMS_FIELD_NAMES = (
    "__VIEWSTATE",
    "__VIEWSTATEGENERATOR",
    "__EVENTVALIDATION",
)


class VrParserError(ValueError):
    """Base class for safe, expected parser failures."""


class MissingWebFormsFieldError(VrParserError):
    """Raised when a required WebForms hidden field is absent."""

    def __init__(self, missing_fields: Iterable[str]) -> None:
        self.missing_fields = tuple(missing_fields)
        fields = ", ".join(self.missing_fields)
        super().__init__(f"Missing required WebForms field(s): {fields}")


class EmptyWebFormsFieldError(VrParserError):
    """Raised when a required WebForms hidden field has no value."""

    def __init__(self, empty_fields: Iterable[str]) -> None:
        self.empty_fields = tuple(empty_fields)
        fields = ", ".join(self.empty_fields)
        super().__init__(f"Empty required WebForms field(s): {fields}")


class MissingCaptchaError(VrParserError):
    """Raised when the login page has no usable CAPTCHA image URL."""


class VehicleResultParseError(VrParserError):
    """Raised when a purported result page lacks mandatory result data."""


class PageReportedError(VrParserError):
    """Raised when a result page explicitly reports a lookup error."""

    def __init__(self, error: ParsedPageError) -> None:
        self.error = error
        super().__init__(f"Page reported {error.code.value}: {error.message}")


class LoginErrorCode(str, Enum):
    CAPTCHA_INVALID = "CAPTCHA_INVALID"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    UNKNOWN = "LOGIN_ERROR"


class LookupErrorCode(str, Enum):
    INVALID_PLATE = "INVALID_PLATE"
    NOT_FOUND = "NOT_FOUND"
    UNKNOWN = "LOOKUP_ERROR"


@dataclass(frozen=True, slots=True)
class ParsedPageError:
    code: LoginErrorCode | LookupErrorCode
    message: str


@dataclass(frozen=True, slots=True, repr=False)
class WebFormsState:
    viewstate: str
    viewstate_generator: str
    event_validation: str

    def as_form_fields(self) -> dict[str, str]:
        """Return raw field values; the HTTP client must encode them once."""

        return {
            "__VIEWSTATE": self.viewstate,
            "__VIEWSTATEGENERATOR": self.viewstate_generator,
            "__EVENTVALIDATION": self.event_validation,
        }


@dataclass(frozen=True, slots=True)
class VehicleResult:
    vehicle_type: str
    brand: str
    inspection_expiry: date


_CHARSET_RE = re.compile(
    r"(?:charset\s*=\s*|<meta[^>]+charset\s*=\s*[\"']?)([A-Za-z0-9._-]+)",
    flags=re.IGNORECASE,
)
_DATE_RE = re.compile(r"(?<!\d)(\d{1,2}/\d{1,2}/\d{4})(?!\d)")
_WHITESPACE_RE = re.compile(r"\s+")
_MOJIBAKE_SEQUENCES = (
    "â€",
    "áº",
    "á»",
    "ï»¿",
    "�",
)
_MOJIBAKE_UTF8_LEADS = frozenset("ÃÂÄÆÐ")
# A UTF-8 continuation byte decoded as either Windows-1252 or latin-1.  Pairing
# this with a suspicious lead distinguishes mojibake ``Ãƒ`` from the valid
# Vietnamese letter ``Ã`` in ``NHÃN``.
_MOJIBAKE_CONTINUATIONS = frozenset(
    character
    for byte in range(0x80, 0xC0)
    for character in (
        bytes((byte,)).decode("cp1252", errors="ignore"),
        chr(byte),
    )
    if character
)


def _mojibake_score(value: str) -> int:
    suspicious_pairs = sum(
        left in _MOJIBAKE_UTF8_LEADS and right in _MOJIBAKE_CONTINUATIONS
        for left, right in zip(value, value[1:])
    )
    return suspicious_pairs + sum(
        value.count(sequence) for sequence in _MOJIBAKE_SEQUENCES
    )


def _repair_mojibake(value: str) -> str:
    """Repair the common UTF-8-as-Windows-1252 corruption when provable.

    A conversion is accepted only when it reduces known corruption markers,
    which avoids modifying already-correct Vietnamese text.
    """

    current = value.lstrip("\ufeff")
    for _ in range(2):
        current_score = _mojibake_score(current)
        best = _best_transcode(current)
        best_score = _mojibake_score(best)

        # Correct Vietnamese and mojibake can coexist in one response. If the
        # full string is not encodable as cp1252/latin-1, repair independent
        # lexical segments instead of abandoning the entire conversion.
        if best_score >= current_score and current_score:
            pieces = re.split(r"(\s+|[<>=/\"']+)", current)
            segmented = "".join(_best_transcode(piece) for piece in pieces)
            segmented_score = _mojibake_score(segmented)
            if segmented_score < best_score:
                best = segmented

        if best == current:
            break
        current = best

    return unicodedata.normalize("NFC", current)


def _best_transcode(value: str) -> str:
    best = value
    best_score = _mojibake_score(value)
    for source_encoding in ("cp1252", "latin-1"):
        try:
            candidate = value.encode(source_encoding).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        candidate = unicodedata.normalize("NFC", candidate)
        candidate_score = _mojibake_score(candidate)
        if candidate_score < best_score:
            best = candidate
            best_score = candidate_score
    return best


def _extract_encoding_hint(hint: str | None) -> str | None:
    if not hint:
        return None
    match = _CHARSET_RE.search(hint)
    return match.group(1) if match else hint.strip().strip("\"'")


def decode_html(document: HTMLDocument, declared_encoding: str | None = None) -> str:
    """Decode HTML bytes and repair common Vietnamese mojibake.

    UTF-8 is preferred when it is valid even if an old page declares a stale
    charset.  For legacy bytes, the response/header hint, HTML meta tag, and
    BeautifulSoup's detector are tried before conservative Windows fallbacks.
    """

    if isinstance(document, str):
        return _repair_mojibake(document)
    if not isinstance(document, bytes):
        raise TypeError("document must be bytes or str")

    try:
        return _repair_mojibake(document.decode("utf-8-sig"))
    except UnicodeDecodeError:
        pass

    candidates: list[str] = []
    encodings: list[str] = []

    explicit_encoding = _extract_encoding_hint(declared_encoding)
    if explicit_encoding:
        encodings.append(explicit_encoding)

    ascii_head = document[:4096].decode("ascii", errors="ignore")
    meta_match = _CHARSET_RE.search(ascii_head)
    if meta_match:
        encodings.append(meta_match.group(1))

    detected = UnicodeDammit(document, is_html=True).original_encoding
    if detected:
        encodings.append(detected)
    encodings.extend(("cp1258", "cp1252", "latin-1"))

    seen: set[str] = set()
    for encoding in encodings:
        key = encoding.casefold()
        if key in seen:
            continue
        seen.add(key)
        try:
            candidates.append(_repair_mojibake(document.decode(encoding)))
        except (LookupError, UnicodeDecodeError):
            continue

    if not candidates:
        # Every byte string is decodable with latin-1, so this is defensive.
        return document.decode("utf-8", errors="replace")

    return min(candidates, key=lambda text: (_mojibake_score(text), text.count("�")))


def _soup(
    document: HTMLDocument, declared_encoding: str | None = None
) -> BeautifulSoup:
    return BeautifulSoup(decode_html(document, declared_encoding), "html.parser")


def _clean_text(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", _repair_mojibake(value).replace("\xa0", " ")).strip()


def _tag_value(tag: Tag) -> str:
    if tag.name in {"input", "textarea"} and tag.has_attr("value"):
        return _clean_text(str(tag.get("value", "")))
    return _clean_text(tag.get_text(" ", strip=True))


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFD", _repair_mojibake(value))
    without_marks = "".join(
        character
        for character in normalized
        if unicodedata.category(character) != "Mn"
    )
    without_marks = without_marks.replace("Đ", "D").replace("đ", "d")
    return _WHITESPACE_RE.sub(
        " ", re.sub(r"[^0-9a-zA-Z]+", " ", without_marks)
    ).strip().casefold()


def parse_hidden_fields(
    document: HTMLDocument,
    required_fields: Iterable[str] | None = WEBFORMS_FIELD_NAMES,
    *,
    declared_encoding: str | None = None,
) -> dict[str, str]:
    """Parse hidden inputs by ``name`` (falling back to ``id``)."""

    soup = _soup(document, declared_encoding)
    fields: dict[str, str] = {}
    for element in soup.select('input[type="hidden"]'):
        name = element.get("name") or element.get("id")
        if name:
            fields[str(name)] = str(element.get("value", ""))

    if required_fields is not None:
        missing = [field for field in required_fields if field not in fields]
        if missing:
            raise MissingWebFormsFieldError(missing)
    return fields


def parse_webforms_state(
    document: HTMLDocument, *, declared_encoding: str | None = None
) -> WebFormsState:
    fields = parse_hidden_fields(document, declared_encoding=declared_encoding)
    empty = [name for name in WEBFORMS_FIELD_NAMES if not fields[name].strip()]
    if empty:
        raise EmptyWebFormsFieldError(empty)
    return WebFormsState(
        viewstate=fields["__VIEWSTATE"],
        viewstate_generator=fields["__VIEWSTATEGENERATOR"],
        event_validation=fields["__EVENTVALIDATION"],
    )


def parse_captcha_url(
    document: HTMLDocument, *, declared_encoding: str | None = None
) -> str:
    soup = _soup(document, declared_encoding)
    image = soup.select_one("#captchaImage")
    source = str(image.get("src", "")).strip() if isinstance(image, Tag) else ""
    if not source:
        raise MissingCaptchaError("Missing CAPTCHA image or src attribute")
    return source


def parse_error_message(
    document: HTMLDocument, *, declared_encoding: str | None = None
) -> str | None:
    soup = _soup(document, declared_encoding)
    element = soup.select_one("#lblErrMsg")
    if not isinstance(element, Tag):
        return None
    message = _tag_value(element)
    return message or None


def parse_login_error(
    document: HTMLDocument, *, declared_encoding: str | None = None
) -> ParsedPageError | None:
    message = parse_error_message(document, declared_encoding=declared_encoding)
    if message is None:
        return None

    folded = _fold(message)
    if "ma xac thuc" in folded and any(
        marker in folded for marker in ("chua dung", "khong dung", "sai")
    ):
        code = LoginErrorCode.CAPTCHA_INVALID
    elif any(
        marker in folded for marker in ("tai khoan", "ten dang nhap", "mat khau")
    ) and any(marker in folded for marker in ("khong dung", "sai", "khong hop le")):
        code = LoginErrorCode.INVALID_CREDENTIALS
    else:
        code = LoginErrorCode.UNKNOWN
    return ParsedPageError(code=code, message=message)


def parse_lookup_error(
    document: HTMLDocument, *, declared_encoding: str | None = None
) -> ParsedPageError | None:
    message = parse_error_message(document, declared_encoding=declared_encoding)
    if message is None:
        return None

    folded = _fold(message)
    if any(marker in folded for marker in ("khong dung dinh dang", "sai dinh dang")):
        code = LookupErrorCode.INVALID_PLATE
    elif any(
        marker in folded
        for marker in (
            "khong tim thay",
            "khong co du lieu",
            "khong co thong tin",
            "chua co du lieu",
        )
    ):
        code = LookupErrorCode.NOT_FOUND
    else:
        code = LookupErrorCode.UNKNOWN
    return ParsedPageError(code=code, message=message)


def _find_inspection_expiry_column(rows: list[Tag]) -> tuple[int, int] | None:
    for row_index, row in enumerate(rows):
        cells = row.find_all(["th", "td"], recursive=False)
        for column_index, cell in enumerate(cells):
            header = _fold(cell.get_text(" ", strip=True))
            if "thoi han" in header and ("kd" in header.split() or "kiem dinh" in header):
                return row_index, column_index
    return None


def _parse_dates(value: str) -> list[date]:
    parsed: list[date] = []
    for raw_date in _DATE_RE.findall(value):
        try:
            parsed.append(datetime.strptime(raw_date, "%d/%m/%Y").date())
        except ValueError:
            continue
    return parsed


def parse_vehicle_result(
    document: HTMLDocument, *, declared_encoding: str | None = None
) -> VehicleResult:
    """Parse the three mandatory fields from a successful lookup response."""

    reported_error = parse_lookup_error(document, declared_encoding=declared_encoding)
    if reported_error is not None:
        raise PageReportedError(reported_error)

    soup = _soup(document, declared_encoding)
    vehicle_element = soup.select_one("#txtLoaiPT")
    brand_element = soup.select_one("#txtNhanHieu")
    table = soup.select_one("#DGKiemDinh")

    missing: list[str] = []
    if not isinstance(vehicle_element, Tag):
        missing.append("txtLoaiPT")
    if not isinstance(brand_element, Tag):
        missing.append("txtNhanHieu")
    if not isinstance(table, Tag):
        missing.append("DGKiemDinh")
    if missing:
        raise VehicleResultParseError(
            f"Missing mandatory result element(s): {', '.join(missing)}"
        )

    vehicle_type = _tag_value(vehicle_element) or UNKNOWN_VEHICLE_TYPE
    brand = _tag_value(brand_element)
    if not brand:
        raise VehicleResultParseError("Empty mandatory result value(s): txtNhanHieu")

    rows = list(table.find_all("tr"))
    expiry_column = _find_inspection_expiry_column(rows)
    if expiry_column is None:
        raise VehicleResultParseError("Inspection expiry column was not found")

    header_row_index, column_index = expiry_column
    expiry_dates: list[date] = []
    for row in rows[header_row_index + 1 :]:
        cells = row.find_all(["th", "td"], recursive=False)
        if column_index >= len(cells):
            continue
        expiry_dates.extend(_parse_dates(cells[column_index].get_text(" ", strip=True)))

    if not expiry_dates:
        raise VehicleResultParseError("No valid inspection expiry date was found")

    return VehicleResult(
        vehicle_type=vehicle_type,
        brand=brand,
        inspection_expiry=max(expiry_dates),
    )


__all__ = [
    "HTMLDocument",
    "EmptyWebFormsFieldError",
    "LoginErrorCode",
    "LookupErrorCode",
    "MissingCaptchaError",
    "MissingWebFormsFieldError",
    "PageReportedError",
    "ParsedPageError",
    "VehicleResult",
    "VehicleResultParseError",
    "VrParserError",
    "WEBFORMS_FIELD_NAMES",
    "WebFormsState",
    "decode_html",
    "parse_captcha_url",
    "parse_error_message",
    "parse_hidden_fields",
    "parse_login_error",
    "parse_lookup_error",
    "parse_vehicle_result",
    "parse_webforms_state",
]
