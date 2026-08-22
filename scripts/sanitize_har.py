"""Create redacted diagnostic HTML from the local HAR without request bodies."""

from __future__ import annotations

import base64
import binascii
import json
import os
from pathlib import Path

from bs4 import BeautifulSoup

from app.services.vr_parser import WEBFORMS_FIELD_NAMES, decode_html
from app.views.script_view import configure_console_encoding


def sanitize_html(document: str) -> str:
    """Build an allowlisted diagnostic page; never copy arbitrary source text."""

    soup = BeautifulSoup(document, "html.parser")
    hidden = []
    for name in WEBFORMS_FIELD_NAMES:
        if soup.find("input", attrs={"name": name}) is not None:
            hidden.append(
                f'<input type="hidden" name="{name}" value="synthetic-{name.casefold()}">'
            )
    hidden_html = "\n".join(hidden)

    if soup.select_one("#txtLoaiPT") is not None or soup.select_one("#DGKiemDinh") is not None:
        return f"""<!doctype html>
<html lang="vi"><body data-sanitized-page="result">
{hidden_html}
<span id="LblBinDangKy">00A00000T</span>
<span id="txtLoaiPT">LOẠI PHƯƠNG TIỆN TỔNG HỢP</span>
<span id="txtNhanHieu">NHÃN HIỆU TỔNG HỢP</span>
<table id="DGKiemDinh">
  <tr><td>Đơn vị kiểm định</td><td>Ngày KĐ</td><td>Số tem GCN</td><td>Thời hạn KĐ</td></tr>
  <tr><td>ĐƠN VỊ TỔNG HỢP</td><td>01/01/2030</td><td>SYNTHETIC</td><td>31/12/2030</td></tr>
</table>
</body></html>"""

    if soup.select_one("#txtNguoiDung") is not None or soup.select_one("#captchaImage") is not None:
        error = "REDACTED_ERROR" if _has_page_error(soup) else ""
        return f"""<!doctype html>
<html lang="vi"><body data-sanitized-page="login">
<form action="Login.aspx" method="post">
{hidden_html}
<input name="txtNguoiDung" id="txtNguoiDung" value="">
<input name="txtMatKhau" id="txtMatKhau" type="password" value="">
<img id="captchaImage" src="Images/CaptchaSynthetic.jpg">
<input name="ImaRefresh" id="ImaRefresh" type="image">
<input name="txtCaptcha" id="txtCaptcha" value="">
<input name="btnDangNhap" id="btnDangNhap" type="submit" value="Đăng nhập">
<span id="lblErrMsg">{error}</span>
</form>
</body></html>"""

    if soup.select_one("#txtBienDK") is not None:
        error = "REDACTED_ERROR" if _has_page_error(soup) else ""
        return f"""<!doctype html>
<html lang="vi"><body data-sanitized-page="lookup">
<form action="ThongTinPT.aspx" method="post">
{hidden_html}
<input name="txtBienDK" id="txtBienDK" value="">
<input name="Button1" id="Button1" type="submit" value="Tra cứu">
<span id="lblErrMsg">{error}</span>
</form>
</body></html>"""

    return '<!doctype html><html><body data-sanitized-page="unknown"></body></html>'


def _has_page_error(soup: BeautifulSoup) -> bool:
    error = soup.select_one("#lblErrMsg")
    return bool(error and error.get_text(" ", strip=True))


def _decode_har_content(content: dict) -> str:
    document = content.get("text")
    if not isinstance(document, str):
        raise ValueError("HAR response content.text is missing")
    encoding = str(content.get("encoding", "")).casefold()
    if not encoding:
        return decode_html(document)
    if encoding != "base64":
        raise ValueError(f"Unsupported HAR content encoding: {encoding}")
    try:
        raw = base64.b64decode(document, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Invalid base64 HAR response content") from exc
    return decode_html(raw)


def sanitize_har(input_path: Path, output_dir: Path) -> int:
    payload = json.loads(input_path.read_text(encoding="utf-8-sig"))
    output_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for index, entry in enumerate(payload.get("log", {}).get("entries", [])):
        content = entry.get("response", {}).get("content", {})
        mime_type = str(content.get("mimeType", "")).casefold()
        document = content.get("text")
        if "html" not in mime_type or not isinstance(document, str) or not document:
            continue
        safe = sanitize_html(_decode_har_content(content))
        (output_dir / f"response_{index:03d}.html").write_text(safe, encoding="utf-8")
        count += 1
    return count


def main() -> int:
    configure_console_encoding()
    input_path = Path(os.getenv("HAR_INPUT_FILE", "app.vr.org.vn.har"))
    output_dir = Path(os.getenv("SANITIZED_HAR_DIR", "runtime/sanitized_har"))
    try:
        count = sanitize_har(input_path, output_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Không thể làm sạch HAR: {exc}")
        return 1
    print(f"Đã tạo {count} response HTML đã làm sạch tại {output_dir}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
