from io import BytesIO

from PIL import Image

from app.services.errors import SourceHttpError
from app.services.webforms_client import CaptchaChallenge
from scripts.download_captchas import load_login_page, next_index, save_jpeg


def test_next_index_ignores_non_numbered_files(tmp_path) -> None:
    (tmp_path / "001.jpg").write_bytes(b"x")
    (tmp_path / "010.jpg").write_bytes(b"x")
    (tmp_path / "ABCD.jpg").write_bytes(b"x")

    assert next_index(tmp_path) == 11


def test_save_jpeg_converts_source_image(tmp_path) -> None:
    source = BytesIO()
    Image.new("RGBA", (120, 35), (255, 255, 255, 0)).save(source, format="PNG")
    destination = tmp_path / "001.jpg"

    save_jpeg(source.getvalue(), destination)

    with Image.open(destination) as image:
        assert image.format == "JPEG"
        assert image.size == (120, 35)


def test_load_login_page_retries_source_errors(monkeypatch) -> None:
    class Client:
        calls = 0

        def start_login(self) -> CaptchaChallenge:
            self.calls += 1
            if self.calls < 3:
                raise SourceHttpError("HTTP error", status_code=501)
            return CaptchaChallenge("https://source.test/captcha.jpg")

    client = Client()
    monkeypatch.setattr("scripts.download_captchas.sleep", lambda _delay: None)

    challenge = load_login_page(client, delay=0)

    assert challenge.image_url == "https://source.test/captcha.jpg"
    assert client.calls == 3
