"""Console interaction used only by explicit Phase 1 Python scripts."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date
from pathlib import Path
import sys
from typing import Any


def configure_console_encoding() -> None:
    """Use UTF-8 on Windows terminals while keeping injected test streams intact."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


class ScriptView:
    def __init__(
        self,
        input_func: Callable[[str], str] = input,
        output_func: Callable[[str], Any] = print,
    ) -> None:
        self._input = input_func
        self._output = output_func

    def request_captcha(self, image_path: Path, attempt: int, maximum: int) -> str:
        self._output(f"CAPTCHA: {image_path}")
        value = self._input(f"Nhập CAPTCHA ({attempt}/{maximum}): ")
        return value.strip()

    def request_plate(self) -> str:
        return self._input("Nhập biển số cần tra cứu: ").strip()

    def show_ready(self) -> None:
        self._output("Đăng nhập thành công. Trạng thái: READY")

    def show_error(self, message: str) -> None:
        self._output(f"Lỗi: {message}")

    def show_info(self, message: str) -> None:
        self._output(message)

    def show_results(self, results: Iterable[Any]) -> None:
        items = list(results)
        if not items:
            self._output("Không tìm thấy dữ liệu phương tiện.")
            return
        for item in items:
            plate = getattr(item, "queried_plate", "")
            vehicle = getattr(item, "vehicle", item)
            vehicle_type = getattr(vehicle, "vehicle_type", "")
            brand = getattr(vehicle, "brand", "")
            expiry = getattr(vehicle, "inspection_expiry", "")
            expiry_text = (
                expiry.strftime("%d/%m/%Y") if isinstance(expiry, date) else str(expiry)
            )
            self._output(f"Biển tra cứu: {plate}")
            self._output(f"Loại phương tiện: {vehicle_type}")
            self._output(f"Thương hiệu/Nhãn hiệu: {brand}")
            self._output(f"Thời hạn kiểm định: {expiry_text}")
