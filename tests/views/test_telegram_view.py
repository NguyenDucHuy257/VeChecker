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


def test_admin_and_user_help_explain_distinct_permissions() -> None:
    admin = TelegramView.admin_help()
    user = TelegramView.user_help()

    assert "/approve <telegram_id>" in admin
    assert "/block <telegram_id>" in admin
    assert "toàn bộ quyền user" in admin
    assert "/login" not in user
    assert "/logout" not in user
    assert "/approve" not in user
    assert "xử lý lần lượt" in user
    assert "37RM00562" in user
    assert "/login" in admin
    assert "/logout" in admin
    assert "tự đăng nhập lại" in admin


def test_restricted_help_does_not_offer_login_as_available_command() -> None:
    assert "chưa được phép đăng nhập" in TelegramView.pending_help()
    assert "không thể /login" in TelegramView.blocked_help()


def test_source_rejection_is_distinct_from_local_format_error() -> None:
    assert TelegramView.invalid_plate() == "Biển số không đúng định dạng."
    rejected = TelegramView.source_rejected_plate()
    assert "Website nguồn từ chối" in rejected
    assert "T/X/V" in rejected
