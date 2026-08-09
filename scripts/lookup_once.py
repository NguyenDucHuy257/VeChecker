"""Phase 1 test script: login once, then look up one input plate."""

from __future__ import annotations

from app.config import ConfigError
from app.main import create_application
from app.models import LookupStatus
from app.services.errors import VrServiceError
from app.views.script_view import configure_console_encoding


def main() -> int:
    configure_console_encoding()
    try:
        with create_application() as application:
            application.auth.login_manual()
            plate = application.view.request_plate()
            result = application.lookups.lookup(plate)
            if result.successes:
                application.view.show_results(result.successes)
                return 0
            if result.status is LookupStatus.INVALID:
                application.view.show_error("Biển số không đúng định dạng.")
            else:
                application.view.show_info("Không tìm thấy dữ liệu phương tiện.")
            return 2
    except (ConfigError, VrServiceError) as exc:
        print(f"Không thể hoàn tất tra cứu: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
