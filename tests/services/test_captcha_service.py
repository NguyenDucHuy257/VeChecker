from pathlib import Path

import pytest

from app.services.captcha_service import CaptchaFileService, CaptchaStorageError


def test_save_and_cleanup_only_owned_files(tmp_path: Path) -> None:
    unrelated = tmp_path / "keep.txt"
    unrelated.write_text("keep", encoding="utf-8")
    service = CaptchaFileService(tmp_path)

    saved = service.save(b"fake-jpeg")

    assert saved.read_bytes() == b"fake-jpeg"
    service.cleanup()
    assert not saved.exists()
    assert unrelated.exists()


def test_rejects_empty_captcha(tmp_path: Path) -> None:
    service = CaptchaFileService(tmp_path)

    with pytest.raises(CaptchaStorageError):
        service.save(b"")
