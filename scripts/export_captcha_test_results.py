"""Run an ONNX model on the deterministic test split and export review files."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import shutil

from app.services.captcha_onnx import OnnxCaptchaRecognizer
from train_captcha_model import load_samples, split_samples


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("runtime/dataset"))
    parser.add_argument(
        "--model", type=Path, default=Path("models/captcha/model_6063.onnx")
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("runtime/model_6063_test_results"),
    )
    parser.add_argument("--seed", type=int, default=20260815)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    samples = load_samples(args.dataset)
    _, _, test = split_samples(
        samples, seed=args.seed, validation_ratio=0.1, test_ratio=0.1
    )
    recognizer = OnnxCaptchaRecognizer(args.model)
    correct_dir = args.output_dir / "correct"
    incorrect_dir = args.output_dir / "incorrect"
    correct_dir.mkdir(parents=True, exist_ok=True)
    incorrect_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, str]] = []
    correct = 0
    for index, sample in enumerate(test, 1):
        prediction = recognizer.predict(sample.path.read_bytes())
        is_correct = prediction.text == sample.label
        correct += int(is_correct)
        category = "correct" if is_correct else "incorrect"
        filename = (
            f"{index:04d}__expected-{sample.label}__pred-{prediction.text}"
            f"__conf-{prediction.confidence:.4f}{sample.path.suffix.lower()}"
        )
        destination = (correct_dir if is_correct else incorrect_dir) / filename
        shutil.copy2(sample.path, destination)
        rows.append(
            {
                "source": str(sample.path),
                "expected": sample.label,
                "predicted": prediction.text,
                "confidence": f"{prediction.confidence:.6f}",
                "correct": str(is_correct).lower(),
                "exported_file": str(destination.relative_to(args.output_dir)),
            }
        )

    with (args.output_dir / "results.tsv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys(), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    total = len(test)
    print(
        f"total={total} correct={correct} incorrect={total - correct} "
        f"exact={correct / total:.2%} output={args.output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
