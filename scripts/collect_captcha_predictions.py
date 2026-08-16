"""Download fresh CAPTCHA images and save model predictions for visual review."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from time import sleep

from PIL import Image, ImageDraw

from app.config import load_config
from app.services.captcha_onnx import OnnxCaptchaRecognizer
from app.services.errors import CaptchaImageUnavailableError
from app.services.webforms_client import WebFormsClient


@dataclass(frozen=True, slots=True)
class SavedPrediction:
    index: int
    filename: str
    prediction: str
    confidence: float
    decision: str


def save_prediction(
    image_bytes: bytes,
    *,
    output_dir: Path,
    index: int,
    prediction: str,
    confidence: float,
    threshold: float,
) -> SavedPrediction:
    decision = "auto" if confidence >= threshold else "manual"
    filename = f"{index:03d}_{prediction}_{confidence:.4f}_{decision}.png"
    with Image.open(BytesIO(image_bytes)) as source:
        source.convert("RGB").save(output_dir / filename, format="PNG")
    return SavedPrediction(index, filename, prediction, confidence, decision)


def write_manifest(output_dir: Path, rows: list[SavedPrediction]) -> None:
    lines = ["index\tfilename\tprediction\tconfidence\tdecision"]
    lines.extend(
        f"{row.index}\t{row.filename}\t{row.prediction}\t{row.confidence:.6f}\t{row.decision}"
        for row in rows
    )
    (output_dir / "predictions.tsv").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def write_contact_sheet(output_dir: Path, rows: list[SavedPrediction]) -> None:
    columns = 4
    cell_width, cell_height = 190, 78
    row_count = (len(rows) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * cell_width, row_count * cell_height), "white")
    draw = ImageDraw.Draw(sheet)
    for offset, row in enumerate(rows):
        x = (offset % columns) * cell_width
        y = (offset // columns) * cell_height
        with Image.open(output_dir / row.filename) as source:
            image = source.convert("RGB")
            sheet.paste(image, (x + 4, y + 4))
        color = "green" if row.decision == "auto" else "darkorange"
        draw.text(
            (x + 4, y + 44),
            f"{row.index:03d}  {row.prediction}  {row.confidence:.3f}  {row.decision}",
            fill=color,
        )
    sheet.save(output_dir / "contact_sheet.png", format="PNG")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("runtime/captcha_prediction_review")
    )
    parser.add_argument("--model", type=Path, default=Path("models/captcha/model.onnx"))
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--delay", type=float, default=0.5)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 1 <= args.count <= 100:
        raise SystemExit("--count phải nằm trong khoảng 1..100")
    if not 0 < args.threshold <= 1:
        raise SystemExit("--threshold phải thuộc khoảng (0, 1]")
    if args.delay < 0:
        raise SystemExit("--delay không được âm")

    config = load_config(require_admin_ids=False, require_telegram_token=False)
    recognizer = OnnxCaptchaRecognizer(args.model)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    client = WebFormsClient(
        base_url=config.vr_base_url,
        username=config.vr_username,
        password=config.vr_password,
        timeout_seconds=config.request_timeout_seconds,
        verify_ssl=config.verify_ssl,
    )
    rows: list[SavedPrediction] = []
    try:
        challenge = client.start_login()
        for index in range(1, args.count + 1):
            for download_attempt in range(1, 6):
                try:
                    image_bytes = client.download_captcha(challenge)
                    break
                except CaptchaImageUnavailableError:
                    if download_attempt == 5:
                        raise
                    sleep(max(args.delay, 0.5))
                    challenge = client.refresh_captcha()
            prediction = recognizer.predict(image_bytes)
            row = save_prediction(
                image_bytes,
                output_dir=args.output_dir,
                index=index,
                prediction=prediction.text,
                confidence=prediction.confidence,
                threshold=args.threshold,
            )
            rows.append(row)
            print(
                f"{index:03d}/{args.count:03d} prediction={row.prediction} "
                f"confidence={row.confidence:.4f} decision={row.decision}"
            )
            if index < args.count:
                if args.delay:
                    sleep(args.delay)
                challenge = client.refresh_captcha()
    finally:
        client.close()

    write_manifest(args.output_dir, rows)
    write_contact_sheet(args.output_dir, rows)
    auto = sum(row.decision == "auto" for row in rows)
    print(f"saved={len(rows)} auto={auto} manual={len(rows)-auto} dir={args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
