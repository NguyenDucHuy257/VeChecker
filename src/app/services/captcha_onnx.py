"""Fixed-length CAPTCHA inference contract for a licensed ONNX model."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import json
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from PIL import Image


class CaptchaModelError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True, repr=False)
class CaptchaPrediction:
    text: str
    confidence: float


class CaptchaRecognizer(Protocol):
    def predict(self, image: bytes) -> CaptchaPrediction: ...


@dataclass(frozen=True, slots=True)
class CaptchaModelMetadata:
    input_width: int
    input_height: int
    length: int
    charset: str
    input_name: str | None = None
    output_name: str | None = None

    @classmethod
    def load(cls, path: Path) -> "CaptchaModelMetadata":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            metadata = cls(
                input_width=int(payload["input_width"]),
                input_height=int(payload["input_height"]),
                length=int(payload["length"]),
                charset=str(payload["charset"]),
                input_name=payload.get("input_name"),
                output_name=payload.get("output_name"),
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CaptchaModelError("Không đọc được metadata CAPTCHA ONNX.") from exc
        if (
            metadata.input_width <= 0
            or metadata.input_height <= 0
            or metadata.length <= 0
            or len(metadata.charset) < 2
            or len(set(metadata.charset)) != len(metadata.charset)
        ):
            raise CaptchaModelError("Metadata CAPTCHA ONNX không hợp lệ.")
        return metadata


class OnnxCaptchaRecognizer:
    def __init__(
        self,
        model_path: str | Path,
        *,
        metadata_path: str | Path | None = None,
        session: Any | None = None,
    ) -> None:
        self.model_path = Path(model_path)
        sidecar = (
            Path(metadata_path)
            if metadata_path is not None
            else self.model_path.with_suffix(".json")
        )
        self.metadata = CaptchaModelMetadata.load(sidecar)
        if session is None:
            if not self.model_path.is_file():
                raise CaptchaModelError("Không thấy model CAPTCHA ONNX.")
            try:
                import onnxruntime as ort

                session = ort.InferenceSession(
                    str(self.model_path),
                    providers=["CPUExecutionProvider"],
                )
            except Exception as exc:
                raise CaptchaModelError("Không load được model CAPTCHA ONNX.") from exc
        self.session = session
        inputs = list(self.session.get_inputs())
        if not inputs:
            raise CaptchaModelError("Model CAPTCHA không có input.")
        self.input_name = self.metadata.input_name or inputs[0].name

    def preprocess(self, image: bytes) -> np.ndarray:
        if not image:
            raise CaptchaModelError("Ảnh CAPTCHA rỗng.")
        try:
            with Image.open(BytesIO(image)) as source:
                grayscale = source.convert("L").resize(
                    (self.metadata.input_width, self.metadata.input_height),
                    Image.Resampling.BILINEAR,
                )
                array = np.asarray(grayscale, dtype=np.float32) / 255.0
        except (OSError, ValueError) as exc:
            raise CaptchaModelError("Không tiền xử lý được ảnh CAPTCHA.") from exc
        return np.ascontiguousarray(array[np.newaxis, np.newaxis, :, :])

    def predict(self, image: bytes) -> CaptchaPrediction:
        tensor = self.preprocess(image)
        output_names = [self.metadata.output_name] if self.metadata.output_name else None
        try:
            outputs = self.session.run(output_names, {self.input_name: tensor})
        except Exception as exc:
            raise CaptchaModelError("ONNX inference CAPTCHA thất bại.") from exc
        if not outputs:
            raise CaptchaModelError("Model CAPTCHA không trả output.")
        logits = np.asarray(outputs[0], dtype=np.float32)
        if logits.ndim == 3 and logits.shape[0] == 1:
            logits = logits[0]
        expected = (self.metadata.length, len(self.metadata.charset))
        if logits.shape != expected:
            raise CaptchaModelError(
                f"Output CAPTCHA phải có shape {expected}, nhận {tuple(logits.shape)}."
            )
        if not np.isfinite(logits).all():
            raise CaptchaModelError("Output CAPTCHA chứa giá trị không hữu hạn.")
        shifted = logits - np.max(logits, axis=1, keepdims=True)
        probabilities = np.exp(shifted)
        probabilities /= np.sum(probabilities, axis=1, keepdims=True)
        indexes = np.argmax(probabilities, axis=1)
        text = "".join(self.metadata.charset[int(index)] for index in indexes)
        confidence = float(np.min(probabilities[np.arange(self.metadata.length), indexes]))
        if len(text) != self.metadata.length or any(
            character not in self.metadata.charset for character in text
        ):
            raise CaptchaModelError("Kết quả CAPTCHA nằm ngoài charset/độ dài cho phép.")
        return CaptchaPrediction(text, confidence)
