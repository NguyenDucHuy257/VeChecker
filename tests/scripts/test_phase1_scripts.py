from __future__ import annotations

import json
import base64
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.sanitize_har import sanitize_har, sanitize_html
from scripts import lookup_once, manual_login
from scripts import stability_test as stability_script
from scripts.stability_test import load_inputs


def test_load_inputs_ignores_comments_and_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "plates.txt"
    path.write_text("# comment\n\n 00A00000 \n00A00000T\n", encoding="utf-8")

    assert load_inputs(path) == ["00A00000", "00A00000T"]


def test_stability_input_requires_existing_nonempty_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_inputs(tmp_path / "missing.txt")
    empty = tmp_path / "empty.txt"
    empty.write_text("# only comment", encoding="utf-8")
    with pytest.raises(ValueError):
        load_inputs(empty)


def test_sanitize_html_removes_sensitive_values() -> None:
    source = """
    <form>
      <input name="txtNguoiDung" value="sensitive-user">
      <input name="txtMatKhau" value="sensitive-password">
      <input type="hidden" name="__VIEWSTATE" value="sensitive-state">
      <span id="txtSoMay">sensitive-engine</span>
      <span id="txtLoaiPT">sensitive-type</span>
      <table id="DGKiemDinh"><tr><td>sensitive-certificate</td></tr></table>
    </form>
    """

    result = sanitize_html(source)

    for secret in (
        "sensitive-user",
        "sensitive-password",
        "sensitive-state",
        "sensitive-engine",
        "sensitive-type",
        "sensitive-certificate",
    ):
        assert secret not in result
    assert "LOẠI PHƯƠNG TIỆN TỔNG HỢP" in result


def test_sanitize_har_never_writes_request_payload(tmp_path: Path) -> None:
    source = tmp_path / "input.har"
    output = tmp_path / "output"
    payload = {
        "log": {
            "entries": [
                {
                    "request": {"postData": {"text": "request-secret"}},
                    "response": {
                        "content": {
                            "mimeType": "text/html",
                            "text": '<input name="txtMatKhau" value="response-secret">',
                        }
                    },
                }
            ]
        }
    }
    source.write_text(json.dumps(payload), encoding="utf-8")

    assert sanitize_har(source, output) == 1
    rendered = (output / "response_000.html").read_text(encoding="utf-8")
    assert "request-secret" not in rendered
    assert "response-secret" not in rendered


def test_sanitize_har_decodes_base64_before_allowlist_rebuild(tmp_path: Path) -> None:
    source = tmp_path / "base64.har"
    output = tmp_path / "output"
    raw_html = b'<span id="unexpectedDynamicField">base64-secret</span>'
    payload = {
        "log": {
            "entries": [
                {
                    "request": {},
                    "response": {
                        "content": {
                            "mimeType": "text/html",
                            "encoding": "base64",
                            "text": base64.b64encode(raw_html).decode("ascii"),
                        }
                    },
                }
            ]
        }
    }
    source.write_text(json.dumps(payload), encoding="utf-8")

    assert sanitize_har(source, output) == 1
    rendered = (output / "response_000.html").read_text(encoding="utf-8")
    assert "base64-secret" not in rendered
    assert "unexpectedDynamicField" not in rendered


class FakeApplication:
    def __init__(self, *, plate_file: Path | None = None) -> None:
        self.auth = SimpleNamespace(login_manual=lambda: None)
        self.result = SimpleNamespace(successes=(), status="NOT_FOUND")
        self.lookups = SimpleNamespace(lookup=lambda _: self.result)
        self.messages: list[str] = []
        self.view = SimpleNamespace(
            request_plate=lambda: "00A00000T",
            show_results=lambda value: self.messages.append(f"results:{len(value)}"),
            show_error=self.messages.append,
            show_info=self.messages.append,
        )
        self.config = SimpleNamespace(
            stability_input_file=plate_file,
            stability_delay_seconds=2.0,
        )

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


def test_manual_login_script_main(monkeypatch) -> None:
    application = FakeApplication()
    called: list[bool] = []
    application.auth.login_manual = lambda: called.append(True)
    monkeypatch.setattr(manual_login, "create_application", lambda: application)

    assert manual_login.main() == 0
    assert called == [True]


def test_lookup_once_script_main(monkeypatch) -> None:
    application = FakeApplication()
    application.result = SimpleNamespace(
        successes=(SimpleNamespace(),),
        status="SUCCESS",
    )
    monkeypatch.setattr(lookup_once, "create_application", lambda: application)

    assert lookup_once.main() == 0
    assert application.messages == ["results:1"]


def test_stability_main_reads_path_and_delay_from_application_config(
    tmp_path: Path, monkeypatch
) -> None:
    plate_file = tmp_path / "plates.txt"
    plate_file.write_text("00A00000T\n", encoding="utf-8")
    application = FakeApplication(plate_file=plate_file)
    application.result = SimpleNamespace(
        successes=(SimpleNamespace(),),
        status="SUCCESS",
    )
    monkeypatch.setattr(stability_script, "create_application", lambda: application)

    assert stability_script.main() == 0
    assert any("1/1" in message for message in application.messages)


def test_stability_main_fails_when_no_lookup_succeeds(tmp_path: Path, monkeypatch) -> None:
    plate_file = tmp_path / "plates.txt"
    plate_file.write_text("00A00000T\n", encoding="utf-8")
    application = FakeApplication(plate_file=plate_file)
    monkeypatch.setattr(stability_script, "create_application", lambda: application)

    assert stability_script.main() == 2
