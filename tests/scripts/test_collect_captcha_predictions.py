from io import BytesIO

from PIL import Image

from scripts.collect_captcha_predictions import save_prediction, write_contact_sheet, write_manifest


def image_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (120, 35), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_save_prediction_and_review_artifacts(tmp_path) -> None:
    first = save_prediction(
        image_bytes(), output_dir=tmp_path, index=1, prediction="Aa01",
        confidence=0.75, threshold=0.5
    )
    second = save_prediction(
        image_bytes(), output_dir=tmp_path, index=2, prediction="lI10",
        confidence=0.25, threshold=0.5
    )

    write_manifest(tmp_path, [first, second])
    write_contact_sheet(tmp_path, [first, second])

    assert first.decision == "auto"
    assert second.decision == "manual"
    assert (tmp_path / first.filename).is_file()
    assert "Aa01\t0.750000\tauto" in (tmp_path / "predictions.tsv").read_text()
    assert (tmp_path / "contact_sheet.png").is_file()
