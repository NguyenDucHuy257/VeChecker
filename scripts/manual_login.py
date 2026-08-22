"""Phase 1 test script: verify manual CAPTCHA login only."""

from __future__ import annotations

from app.config import ConfigError
from app.main import create_application
from app.services.errors import VrServiceError
from app.views.script_view import configure_console_encoding


def main() -> int:
    configure_console_encoding()
    try:
        with create_application() as application:
            application.auth.login_manual()
        return 0
    except (ConfigError, VrServiceError) as exc:
        print(f"Không thể hoàn tất kiểm tra đăng nhập: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
