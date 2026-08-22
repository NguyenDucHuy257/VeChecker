"""Import four-character CAPTCHA filenames into the training dataset."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import shutil


LABEL_LENGTH = 4


def valid_source(path: Path) -> bool:
    return (
        path.is_file()
        and path.suffix.casefold() in {".jpg", ".jpeg"}
        and len(path.stem) == LABEL_LENGTH
        and path.stem.isascii()
        and path.stem.isalnum()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("runtime/captcha"))
    parser.add_argument("--dataset", type=Path, default=Path("runtime/dataset"))
    args = parser.parse_args()

    manifest = args.dataset / "labels.tsv"
    images_dir = args.dataset / "images"
    if not args.source.is_dir() or not manifest.is_file():
        raise SystemExit("Thiếu source CAPTCHA hoặc labels.tsv của dataset")
    images_dir.mkdir(parents=True, exist_ok=True)

    with manifest.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    known_labels = {row["label"] for row in rows}
    imported = skipped = 0
    for source in sorted(args.source.iterdir()):
        if not valid_source(source):
            continue
        label = source.stem
        if label in known_labels:
            skipped += 1
            continue
        destination = images_dir / f"{label}.jpg"
        if destination.exists():
            raise SystemExit(f"Tên đích xung đột ngoài manifest: {destination}")
        shutil.copy2(source, destination)
        rows.append({"filename": f"images/{destination.name}", "label": label})
        known_labels.add(label)
        imported += 1

    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["filename", "label"], delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    print(f"imported={imported} existing_labels={skipped} total={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
