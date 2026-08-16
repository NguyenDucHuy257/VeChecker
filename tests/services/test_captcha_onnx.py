from io import BytesIO
import json

import numpy as np
from PIL import Image
import pytest

from app.services.captcha_onnx import CaptchaModelError, OnnxCaptchaRecognizer


class Input:
    name = "captcha"


class FakeSession:
    def __init__(self, output):
        self.output = output
        self.feeds = []

    def get_inputs(self):
        return [Input()]

    def run(self, output_names, feeds):
        self.feeds.append((output_names, feeds))
        return [self.output]


def image_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (20, 10), (128, 64, 32)).save(buffer, format="PNG")
    return buffer.getvalue()


def metadata(tmp_path):
    path = tmp_path / "model.json"
    path.write_text(
        json.dumps(
            {
                "input_width": 12,
                "input_height": 6,
                "length": 4,
                "charset": "ABC",
            }
        ),
        encoding="utf-8",
    )
    return path


def test_preprocess_and_prediction_contract(tmp_path) -> None:
    logits = np.array(
        [[10, 0, 0], [0, 10, 0], [0, 0, 10], [0, 10, 0]], dtype=np.float32
    )
    session = FakeSession(logits)
    recognizer = OnnxCaptchaRecognizer(
        tmp_path / "model.onnx", metadata_path=metadata(tmp_path), session=session
    )

    prediction = recognizer.predict(image_bytes())

    tensor = session.feeds[0][1]["captcha"]
    assert tensor.shape == (1, 1, 6, 12)
    assert tensor.dtype == np.float32
    assert 0 <= float(tensor.min()) <= float(tensor.max()) <= 1
    assert prediction.text == "ABCB"
    assert prediction.confidence > 0.99


def test_invalid_output_shape_fails_closed(tmp_path) -> None:
    recognizer = OnnxCaptchaRecognizer(
        tmp_path / "model.onnx",
        metadata_path=metadata(tmp_path),
        session=FakeSession(np.zeros((4, 4), dtype=np.float32)),
    )

    with pytest.raises(CaptchaModelError, match="shape"):
        recognizer.predict(image_bytes())


def test_non_finite_output_fails_closed(tmp_path) -> None:
    logits = np.zeros((4, 3), dtype=np.float32)
    logits[0, 0] = np.nan
    recognizer = OnnxCaptchaRecognizer(
        tmp_path / "model.onnx",
        metadata_path=metadata(tmp_path),
        session=FakeSession(logits),
    )

    with pytest.raises(CaptchaModelError, match="hữu hạn"):
        recognizer.predict(image_bytes())


def test_invalid_metadata_and_image_fail_closed(tmp_path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    with pytest.raises(CaptchaModelError):
        OnnxCaptchaRecognizer(tmp_path / "model.onnx", metadata_path=bad, session=FakeSession([]))

    recognizer = OnnxCaptchaRecognizer(
        tmp_path / "model.onnx",
        metadata_path=metadata(tmp_path),
        session=FakeSession(np.zeros((4, 3), dtype=np.float32)),
    )
    with pytest.raises(CaptchaModelError):
        recognizer.predict(b"not an image")


def test_missing_onnx_model_fails_closed(tmp_path) -> None:
    with pytest.raises(CaptchaModelError, match="Không thấy model"):
        OnnxCaptchaRecognizer(
            tmp_path / "missing.onnx",
            metadata_path=metadata(tmp_path),
        )
