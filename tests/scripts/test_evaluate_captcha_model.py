from pathlib import Path

import pytest

from app.services.captcha_onnx import CaptchaPrediction
from scripts.evaluate_captcha_model import evaluate, load_manifest


class Recognizer:
    def __init__(self, outputs):
        self.outputs = iter(outputs)

    def predict(self, image):
        return CaptchaPrediction(next(self.outputs), 1.0)


def test_manifest_is_relative_to_its_private_directory(tmp_path) -> None:
    (tmp_path / "a.jpg").write_bytes(b"a")
    (tmp_path / "b.jpg").write_bytes(b"b")
    manifest = tmp_path / "labels.tsv"
    manifest.write_text("a.jpg\tABCD\n# note\nb.jpg\tEFGH\n", encoding="utf-8")

    rows = load_manifest(manifest)

    assert rows == [(tmp_path / "a.jpg", "ABCD"), (tmp_path / "b.jpg", "EFGH")]


def test_manifest_rejects_path_escape(tmp_path) -> None:
    manifest = tmp_path / "labels.tsv"
    manifest.write_text("../outside.jpg\tABCD\n", encoding="utf-8")

    with pytest.raises(ValueError, match="ngoài"):
        load_manifest(manifest)


def test_exact_match_counts_whole_string_only(tmp_path) -> None:
    samples = [(Path("one"), "ABCD"), (Path("two"), "WXYZ")]
    for path, _ in samples:
        path = tmp_path / path
        path.write_bytes(b"image")
    real_samples = [(tmp_path / path, label) for path, label in samples]

    result = evaluate(Recognizer(["ABCD", "WXY1"]), real_samples)

    assert result.total == 2
    assert result.exact_matches == 1
    assert result.accuracy == 0.5
