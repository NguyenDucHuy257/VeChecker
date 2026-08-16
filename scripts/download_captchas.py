"""Download numbered CAPTCHA images from the VR login page."""

from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path
from time import sleep

from PIL import Image

from app.config import load_config
from app.services.errors import CaptchaImageUnavailableError, VrServiceError
from app.services.webforms_client import CaptchaChallenge, WebFormsClient


def next_index(output_dir: Path) -> int:
    indexes = [
        int(path.stem)
        for path in output_dir.glob("*.jpg")
        if path.is_file() and path.stem.isdecimal()
    ]
    return max(indexes, default=0) + 1


def save_jpeg(image_bytes: bytes, destination: Path) -> None:
    with Image.open(BytesIO(image_bytes)) as source:
        source.convert("RGB").save(destination, format="JPEG", quality=95)


def download_with_refresh(
    client: WebFormsClient,
    challenge: CaptchaChallenge,
    *,
    delay: float,
    attempts: int = 5,
) -> tuple[bytes, CaptchaChallenge]:
    current = challenge
    for attempt in range(1, attempts + 1):
        try:
            return client.download_captcha(current), current
        except CaptchaImageUnavailableError:
            if attempt == attempts:
                raise
            # sleep(max(delay, 0.5))
            current = client.refresh_captcha()
    raise AssertionError("unreachable")


def load_login_page(client: WebFormsClient, *, delay: float) -> CaptchaChallenge:
    """Keep reloading the login page until the source is usable again."""

    attempt = 0
    while True:
        attempt += 1
        try:
            return client.start_login()
        except VrServiceError as exc:
            print(f"reload attempt={attempt} error={exc}; thử lại...")
            # sleep(max(delay, 0.5))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--output-dir", type=Path, default=Path("runtime/captcha"))
    parser.add_argument(
        "--start",
        type=int,
        default=None,
        help="Số bắt đầu; mặc định nối tiếp file số lớn nhất trong output-dir.",
    )
    parser.add_argument("--delay", type=float, default=0.75)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 1 <= args.count <= 10000:
        raise SystemExit("--count phải nằm trong khoảng 1..10000")
    if args.start is not None and args.start <= 0:
        raise SystemExit("--start phải lớn hơn 0")
    if args.delay < 0:
        raise SystemExit("--delay không được âm")

    config = load_config(require_admin_ids=False, require_telegram_token=False)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    index = args.start if args.start is not None else next_index(args.output_dir)
    client = WebFormsClient(
        base_url=config.vr_base_url,
        username=config.vr_username,
        password=config.vr_password,
        timeout_seconds=config.request_timeout_seconds,
        verify_ssl=config.verify_ssl,
    )
    try:
        challenge: CaptchaChallenge | None = None
        for offset in range(args.count):
            destination = args.output_dir / f"{index + offset:03d}.jpg"
            if destination.exists():
                print(f"{offset + 1:03d}/{args.count:03d} skipped={destination}")
                continue

            if challenge is None:
                challenge = load_login_page(client, delay=args.delay)

            while True:
                try:
                    image_bytes, challenge = download_with_refresh(
                        client, challenge, delay=args.delay
                    )
                    break
                except VrServiceError as exc:
                    # HTTP 400/501, timeouts, network errors, malformed responses,
                    # etc. can leave the WebForms state unusable. Reload the page
                    # and retry the same destination instead of ending the run.
                    print(f"retry={destination} error={exc}; reload trang đăng nhập...")
                    if args.delay:
                        # sleep(args.delay)
                        pass
                    challenge = load_login_page(client, delay=args.delay)

            save_jpeg(image_bytes, destination)
            print(f"{offset + 1:03d}/{args.count:03d} saved={destination}")
            if offset + 1 < args.count:
                if args.delay:
                    # sleep(args.delay)
                    pass
                try:
                    challenge = client.refresh_captcha()
                except VrServiceError as exc:
                    print(f"refresh error={exc}; sẽ reload trang đăng nhập...")
                    challenge = None
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
