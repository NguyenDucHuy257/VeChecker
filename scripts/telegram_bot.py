"""Run the Phase 2 Telegram bot using long polling."""

from __future__ import annotations

from app.config import ConfigError
from app.services.errors import VrServiceError
from app.services.captcha_onnx import CaptchaModelError
from app.telegram_app import create_telegram_application
from app.views.script_view import configure_console_encoding


def main() -> int:
    configure_console_encoding()
    try:
        with create_telegram_application() as application:
            print("Telegram bot đang chạy. Nhấn Ctrl+C để dừng.")
            application.polling.run_forever()
    except KeyboardInterrupt:
        print("Đã dừng Telegram bot.")
        return 0
    except (ConfigError, CaptchaModelError, VrServiceError, OSError, ValueError) as exc:
        print(f"Không thể chạy Telegram bot: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
