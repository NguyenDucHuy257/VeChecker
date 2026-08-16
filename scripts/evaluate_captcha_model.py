"""Evaluate exact-match accuracy on a private, independently labelled set."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from app.services.captcha_onnx import CaptchaRecognizer, OnnxCaptchaRecognizer


MINIMUM_SAMPLES = 50
REQUIRED_ACCURACY = 0.90


@dataclass(frozen=True, slots=True)
class Evaluation:
    total: int
    exact_matches: int

    @property
    def accuracy(self) -> float:
        return self.exact_matches / self.total if self.total else 0.0


def load_manifest(path: Path) -> list[tuple[Path, str]]:
    """Read UTF-8 TSV rows: relative_image_path<TAB>expected_text."""

    base = path.parent.resolve()
    rows: list[tuple[Path, str]] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        filename, separator, label = line.partition("\t")
        if not separator or not filename.strip() or not label.strip():
            raise ValueError(f"Manifest không hợp lệ tại dòng {number}.")
        image_path = (base / filename.strip()).resolve()
        if base not in image_path.parents:
            raise ValueError(f"Đường dẫn ảnh nằm ngoài thư mục manifest tại dòng {number}.")
        rows.append((image_path, label.strip()))
    return rows


def evaluate(
    recognizer: CaptchaRecognizer,
    samples: list[tuple[Path, str]],
) -> Evaluation:
    matches = 0
    for image_path, expected in samples:
        prediction = recognizer.predict(image_path.read_bytes())
        matches += int(prediction.text == expected)
    return Evaluation(len(samples), matches)


def main() -> int:
    parser = argparse.ArgumentParser(description="Đánh giá exact-match CAPTCHA ONNX")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--model", type=Path, default=Path("models/captcha/model.onnx"))
    arguments = parser.parse_args()

    samples = load_manifest(arguments.manifest)
    if len(samples) < MINIMUM_SAMPLES:
        print(f"FAIL: cần ít nhất {MINIMUM_SAMPLES} mẫu độc lập; hiện có {len(samples)}.")
        return 2
    result = evaluate(OnnxCaptchaRecognizer(arguments.model), samples)
    status = "PASS" if result.accuracy >= REQUIRED_ACCURACY else "FAIL"
    print(
        f"{status}: exact-match={result.exact_matches}/{result.total} "
        f"({result.accuracy:.2%}); ngưỡng={REQUIRED_ACCURACY:.0%}."
    )
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
