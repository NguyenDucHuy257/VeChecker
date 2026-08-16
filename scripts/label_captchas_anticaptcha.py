"""Label unlabelled CAPTCHA images with Anti-Captcha and rename them safely."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from pathlib import Path
from typing import NamedTuple


API_KEY_ENV = "ANTICAPTCHA_API_KEY"
LABEL_LENGTH = 4
NO_SLOT_ERROR = "ERROR_NO_SLOT_AVAILABLE"


class SolveResult(NamedTuple):
    source: Path
    label: str | None
    error: str | None


def unlabelled_images(directory: Path) -> list[Path]:
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file()
        and path.suffix.casefold() in {".jpg", ".jpeg"}
        and len(path.stem) != LABEL_LENGTH
    )


def valid_label(value: str) -> bool:
    return len(value) == LABEL_LENGTH and value.isascii() and value.isalnum()


def solve_with_retry(solver: object, path: Path) -> tuple[str | int, int]:
    """Retry immediately while Anti-Captcha's worker queue has no free slot."""

    retries = 0
    while True:
        answer = solver.solve_and_return_solution(str(path))
        if answer != 0 or str(solver.error_code) != NO_SLOT_ERROR:
            return answer, retries
        retries += 1


def solve_image(path: Path, api_key: str) -> SolveResult:
    # Mỗi worker dùng solver riêng; không chia sẻ mutable client giữa các thread.
    from anticaptchaofficial.imagecaptcha import imagecaptcha

    solver = imagecaptcha()
    solver.set_verbose(0)
    solver.set_key(api_key)
    solver.set_soft_id(0)
    solver.set_case(True)
    solver.set_minLength(LABEL_LENGTH)
    solver.set_maxLength(LABEL_LENGTH)

    answer, retries = solve_with_retry(solver, path)
    if retries:
        print(f"retried={path.name} reason={NO_SLOT_ERROR} attempts={retries}")
    if answer == 0:
        return SolveResult(path, None, str(solver.error_code))

    label = str(answer).strip()
    if not valid_label(label):
        return SolveResult(path, None, f"nhãn không hợp lệ: {label!r}")
    return SolveResult(path, label, None)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir", type=Path, default=Path("runtime/captcha")
    )
    parser.add_argument("--workers", type=int, default=100)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Chỉ xử lý tối đa N ảnh; hữu ích để chạy thử trước.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 1 <= args.workers <= 100:
        raise SystemExit("--workers phải nằm trong khoảng 1..100")
    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit phải lớn hơn 0")
    if not args.input_dir.is_dir():
        raise SystemExit(f"Không tìm thấy thư mục: {args.input_dir}")

    api_key = os.environ.get(API_KEY_ENV, "").strip()
    if not api_key:
        raise SystemExit(f"Thiếu biến môi trường {API_KEY_ENV}")

    images = unlabelled_images(args.input_dir)
    if args.limit is not None:
        images = images[: args.limit]
    if not images:
        print("Không có ảnh chưa dán nhãn.")
        return 0

    print(f"found={len(images)} workers={min(args.workers, len(images))}")
    renamed = failed = collisions = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(solve_image, path, api_key): path for path in images}
        for completed, future in enumerate(as_completed(futures), start=1):
            source = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                failed += 1
                print(f"{completed}/{len(images)} failed={source.name} error={exc}")
                continue

            if result.error is not None or result.label is None:
                failed += 1
                print(
                    f"{completed}/{len(images)} failed={source.name} "
                    f"error={result.error}"
                )
                continue

            destination = source.with_name(f"{result.label}{source.suffix.lower()}")
            if destination.exists():
                collisions += 1
                print(
                    f"{completed}/{len(images)} collision={source.name} "
                    f"target={destination.name}; giữ nguyên file nguồn"
                )
                continue

            source.rename(destination)
            renamed += 1
            print(
                f"{completed}/{len(images)} renamed={source.name} -> {destination.name}"
            )

    print(
        f"done total={len(images)} renamed={renamed} "
        f"failed={failed} collisions={collisions}"
    )
    return 0 if failed == 0 and collisions == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
