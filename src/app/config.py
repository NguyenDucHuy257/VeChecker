"""Application configuration loaded from environment variables.

The project intentionally does not depend on a dotenv package in Phase 1.  Values
from the real process environment take precedence over values in ``.env``.
Secrets are never included in ``AppConfig.__repr__``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import os
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse


class ConfigError(ValueError):
    """Raised when required configuration is missing or malformed."""


@dataclass(frozen=True, slots=True)
class AppConfig:
    vr_username: str = field(repr=False)
    vr_password: str = field(repr=False)
    telegram_bot_token: str = field(repr=False)
    telegram_admin_ids: tuple[int, ...]
    database_path: Path
    captcha_dir: Path
    stability_input_file: Path
    stability_delay_seconds: float
    candidate_delay_seconds: float
    vr_base_url: str = "https://app.vr.org.vn/ptpublicweb/"
    request_timeout_seconds: float = 15.0
    source_request_attempts: int = 3
    source_retry_delay_seconds: float = 1.0
    max_captcha_attempts: int = 3
    verify_ssl: bool = True
    log_level: str = "INFO"
    max_workers: int = 2
    job_queue_size: int = 20
    telegram_poll_timeout_seconds: int = 25
    user_rate_limit_seconds: float = 2.0
    source_serialize_requests: bool = True
    captcha_mode: str = "manual"
    captcha_model_path: Path = Path("models/captcha/model.onnx")
    captcha_confidence_threshold: float = 0.9

    @property
    def log_secrets(self) -> tuple[str, ...]:
        """Secrets that logging formatters must redact."""

        return tuple(
            value
            for value in (
                self.vr_username,
                self.vr_password,
                self.telegram_bot_token,
            )
            if value
        )


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    if not path.is_file():
        raise ConfigError(f"Env path is not a file: {path}")

    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise ConfigError(f"Cannot read env file: {path}") from exc

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ConfigError(f"Invalid env entry at {path}:{line_number}")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise ConfigError(f"Empty env key at {path}:{line_number}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _required(values: Mapping[str, str], key: str) -> str:
    value = values.get(key, "").strip()
    if not value:
        raise ConfigError(f"Missing required setting: {key}")
    return value


def _parse_admin_ids(raw: str, *, required: bool) -> tuple[int, ...]:
    if not raw.strip():
        if required:
            raise ConfigError("Missing required setting: TELEGRAM_ADMIN_IDS")
        return ()

    result: list[int] = []
    seen: set[int] = set()
    for part in raw.split(","):
        value = part.strip()
        if not value or not value.isdecimal():
            raise ConfigError("TELEGRAM_ADMIN_IDS must contain positive integers separated by commas")
        admin_id = int(value)
        if admin_id <= 0 or admin_id > 2**63 - 1:
            raise ConfigError("TELEGRAM_ADMIN_IDS contains an out-of-range ID")
        if admin_id not in seen:
            seen.add(admin_id)
            result.append(admin_id)
    return tuple(result)


def _parse_bool(raw: str, key: str) -> bool:
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{key} must be true or false")


def _parse_positive_float(raw: str, key: str) -> float:
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be a number") from exc
    if not math.isfinite(value) or value <= 0:
        raise ConfigError(f"{key} must be greater than zero")
    return value


def _parse_positive_int(raw: str, key: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer") from exc
    if value <= 0:
        raise ConfigError(f"{key} must be greater than zero")
    return value


def _parse_probability(raw: str, key: str) -> float:
    value = _parse_positive_float(raw, key)
    if value > 1:
        raise ConfigError(f"{key} must be less than or equal to one")
    return value


def _normalize_base_url(raw: str) -> str:
    value = raw.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError("VR_BASE_URL must be an absolute HTTP(S) URL")
    return value if value.endswith("/") else f"{value}/"


def load_config(
    env_file: str | Path | None = ".env",
    *,
    environ: Mapping[str, str] | None = None,
    require_vr_credentials: bool = True,
    require_admin_ids: bool = True,
    require_telegram_token: bool = False,
) -> AppConfig:
    """Load and validate application settings.

    ``environ`` is injectable for deterministic tests.  When omitted, the real
    process environment is used.  Environment values always override ``.env``.
    """

    file_values = _read_env_file(Path(env_file)) if env_file is not None else {}
    process_values = dict(os.environ if environ is None else environ)
    values = {**file_values, **process_values}

    if require_vr_credentials:
        username = _required(values, "VR_USERNAME")
        password = _required(values, "VR_PASSWORD")
    else:
        username = values.get("VR_USERNAME", "").strip()
        password = values.get("VR_PASSWORD", "").strip()

    if require_telegram_token:
        telegram_bot_token = _required(values, "TELEGRAM_BOT_TOKEN")
    else:
        telegram_bot_token = values.get("TELEGRAM_BOT_TOKEN", "").strip()

    admin_ids = _parse_admin_ids(
        values.get("TELEGRAM_ADMIN_IDS", ""),
        required=require_admin_ids,
    )
    database_path_raw = values.get("DATABASE_PATH", "runtime/dktle.sqlite3").strip()
    captcha_dir_raw = values.get("CAPTCHA_DIR", "runtime/captcha").strip()
    stability_input_raw = values.get(
        "STABILITY_INPUT_FILE", "tests/live_plates.txt"
    ).strip()
    if not database_path_raw:
        raise ConfigError("DATABASE_PATH cannot be empty")
    if not captcha_dir_raw:
        raise ConfigError("CAPTCHA_DIR cannot be empty")
    if not stability_input_raw:
        raise ConfigError("STABILITY_INPUT_FILE cannot be empty")
    database_path = Path(database_path_raw).expanduser()
    captcha_dir = Path(captcha_dir_raw).expanduser()

    log_level = values.get("LOG_LEVEL", "INFO").strip().upper()
    valid_log_levels = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
    if log_level not in valid_log_levels:
        raise ConfigError(f"LOG_LEVEL must be one of: {', '.join(sorted(valid_log_levels))}")

    max_workers = _parse_positive_int(values.get("MAX_WORKERS", "2"), "MAX_WORKERS")
    if max_workers > 8:
        raise ConfigError("MAX_WORKERS must be less than or equal to 8")
    poll_timeout = _parse_positive_int(
        values.get("TELEGRAM_POLL_TIMEOUT_SECONDS", "25"),
        "TELEGRAM_POLL_TIMEOUT_SECONDS",
    )
    if poll_timeout > 50:
        raise ConfigError("TELEGRAM_POLL_TIMEOUT_SECONDS must be <= 50")
    captcha_mode = values.get("CAPTCHA_MODE", "manual").strip().lower()
    if captcha_mode not in {"manual", "auto"}:
        raise ConfigError("CAPTCHA_MODE must be manual or auto")
    captcha_model_raw = values.get(
        "CAPTCHA_MODEL_PATH", "models/captcha/model.onnx"
    ).strip()
    if not captcha_model_raw:
        raise ConfigError("CAPTCHA_MODEL_PATH cannot be empty")

    return AppConfig(
        vr_username=username,
        vr_password=password,
        telegram_bot_token=telegram_bot_token,
        telegram_admin_ids=admin_ids,
        database_path=database_path,
        captcha_dir=captcha_dir,
        stability_input_file=Path(stability_input_raw).expanduser(),
        stability_delay_seconds=_parse_positive_float(
            values.get("STABILITY_DELAY_SECONDS", "2"),
            "STABILITY_DELAY_SECONDS",
        ),
        candidate_delay_seconds=_parse_positive_float(
            values.get("CANDIDATE_DELAY_SECONDS", "2"),
            "CANDIDATE_DELAY_SECONDS",
        ),
        vr_base_url=_normalize_base_url(
            values.get("VR_BASE_URL", "https://app.vr.org.vn/ptpublicweb/")
        ),
        request_timeout_seconds=_parse_positive_float(
            values.get("REQUEST_TIMEOUT_SECONDS", "15"),
            "REQUEST_TIMEOUT_SECONDS",
        ),
        source_request_attempts=_parse_positive_int(
            values.get("SOURCE_REQUEST_ATTEMPTS", "3"),
            "SOURCE_REQUEST_ATTEMPTS",
        ),
        source_retry_delay_seconds=_parse_positive_float(
            values.get("SOURCE_RETRY_DELAY_SECONDS", "1"),
            "SOURCE_RETRY_DELAY_SECONDS",
        ),
        max_captcha_attempts=_parse_positive_int(
            values.get("MAX_CAPTCHA_ATTEMPTS", "3"),
            "MAX_CAPTCHA_ATTEMPTS",
        ),
        verify_ssl=_parse_bool(values.get("VERIFY_SSL", "true"), "VERIFY_SSL"),
        log_level=log_level,
        max_workers=max_workers,
        job_queue_size=_parse_positive_int(
            values.get("JOB_QUEUE_SIZE", "20"), "JOB_QUEUE_SIZE"
        ),
        telegram_poll_timeout_seconds=poll_timeout,
        user_rate_limit_seconds=_parse_positive_float(
            values.get("USER_RATE_LIMIT_SECONDS", "2"),
            "USER_RATE_LIMIT_SECONDS",
        ),
        source_serialize_requests=_parse_bool(
            values.get("SOURCE_SERIALIZE_REQUESTS", "true"),
            "SOURCE_SERIALIZE_REQUESTS",
        ),
        captcha_mode=captcha_mode,
        captcha_model_path=Path(captcha_model_raw).expanduser(),
        captcha_confidence_threshold=_parse_probability(
            values.get("CAPTCHA_CONFIDENCE_THRESHOLD", "0.9"),
            "CAPTCHA_CONFIDENCE_THRESHOLD",
        ),
    )
