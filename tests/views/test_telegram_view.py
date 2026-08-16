from datetime import date
from types import SimpleNamespace

from app.views.telegram_view import TelegramView


def test_result_message_contains_only_requested_vehicle_fields() -> None:
    vehicle = SimpleNamespace(
        vehicle_type="Ô tô con",
        brand="NHÃN HIỆU",
        inspection_expiry=date(2030, 1, 2),
        engine_number="must-not-leak",
    )
    result = SimpleNamespace(queried_plate="00A00000T", vehicle=vehicle)

    rendered = TelegramView.format_results([result])

    assert "00A00000T" in rendered
    assert "Ô tô con" in rendered
    assert "NHÃN HIỆU" in rendered
    assert "02/01/2030" in rendered
    assert "must-not-leak" not in rendered


def test_two_candidates_are_separated() -> None:
    first = SimpleNamespace(
        queried_plate="00A00000T",
        vehicle=SimpleNamespace(vehicle_type="A", brand="B", inspection_expiry="C"),
    )
    second = SimpleNamespace(
        queried_plate="00A00000V",
        vehicle=SimpleNamespace(vehicle_type="D", brand="E", inspection_expiry="F"),
    )

    assert "\n\n" in TelegramView.format_results([first, second])
