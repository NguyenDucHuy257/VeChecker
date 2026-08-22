from datetime import date
from types import SimpleNamespace

from app.views.script_view import ScriptView


def test_request_captcha_strips_input(tmp_path) -> None:
    output: list[str] = []
    view = ScriptView(lambda _: " 1234 ", output.append)

    value = view.request_captcha(tmp_path / "captcha.jpg", 1, 3)

    assert value == "1234"
    assert any("captcha.jpg" in line for line in output)


def test_show_results_outputs_only_required_fields() -> None:
    output: list[str] = []
    view = ScriptView(output_func=output.append)
    vehicle = SimpleNamespace(
        vehicle_type="Ô tô tải",
        brand="TEST BRAND",
        inspection_expiry=date(2030, 12, 31),
        engine_number="must-not-print",
    )
    item = SimpleNamespace(queried_plate="00A00000T", vehicle=vehicle)

    view.show_results([item])

    joined = "\n".join(output)
    assert "Ô tô tải" in joined
    assert "TEST BRAND" in joined
    assert "31/12/2030" in joined
    assert "must-not-print" not in joined
