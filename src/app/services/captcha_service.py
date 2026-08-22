"""Temporary CAPTCHA image storage for Phase 1 manual entry."""

from __future__ import annotations

from pathlib import Path


class CaptchaStorageError(RuntimeError):
    pass


class CaptchaFileService:
    """Owns one predictable CAPTCHA file and never removes unrelated files."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.current_path = self.directory / "current_captcha.jpg"

    def save(self, image: bytes) -> Path:
        if not image:
            raise CaptchaStorageError("Ảnh CAPTCHA rỗng.")
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.directory / "current_captcha.tmp"
        temporary.write_bytes(image)
        temporary.replace(self.current_path)
        return self.current_path.resolve()

    def cleanup(self) -> None:
        for path in (self.current_path, self.directory / "current_captcha.tmp"):
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                raise CaptchaStorageError(
                    f"Không thể xóa ảnh CAPTCHA tạm: {path.name}"
                ) from exc
