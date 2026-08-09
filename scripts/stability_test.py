"""Phase 1 sequential stability script; configuration comes from .env."""

from __future__ import annotations

from pathlib import Path
import time

from app.config import ConfigError
from app.main import create_application
from app.models import LookupStatus
from app.services.errors import VrServiceError
from app.views.script_view import configure_console_encoding


def load_inputs(path: Path) -> list[str]:
    if not path.is_file():
        raise FileNotFoundError(
            f"Không thấy file test {path}. Hãy sao chép tests/live_plates.example.txt "
            "thành tests/live_plates.txt và thay bằng dữ liệu được phép."
        )
    values = [
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not values:
        raise ValueError("Danh sách biển số test đang rỗng.")
    return values


def main() -> int:
    configure_console_encoding()
    try:
        with create_application() as application:
            delay = application.config.stability_delay_seconds
            if delay < 2:
                raise ValueError("STABILITY_DELAY_SECONDS phải từ 2 giây trở lên.")
            plates = load_inputs(application.config.stability_input_file)
            application.auth.login_manual()
            success = invalid = not_found = 0
            for index, plate in enumerate(plates, start=1):
                application.view.show_info(f"Đang kiểm tra {index}/{len(plates)}")
                result = application.lookups.lookup(plate)
                if result.successes:
                    success += 1
                    application.view.show_results(result.successes)
                elif result.status is LookupStatus.INVALID:
                    invalid += 1
                    application.view.show_info("Kết quả: INVALID")
                else:
                    not_found += 1
                    application.view.show_info("Kết quả: NOT_FOUND")
                if index < len(plates):
                    time.sleep(delay)

        print(
            "Hoàn tất stability test: "
            f"total={len(plates)}, success={success}, invalid={invalid}, "
            f"not_found={not_found}"
        )
        if success == 0:
            print("Stability test không có kết quả SUCCESS để đối chiếu.")
            return 2
        return 0
    except (ConfigError, VrServiceError, OSError, ValueError) as exc:
        print(f"Stability test thất bại: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
