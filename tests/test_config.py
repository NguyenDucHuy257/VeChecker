import logging
import sys

import pytest

from app.config import ConfigError, load_config
from app.logging_config import RedactingFormatter


def test_load_config_env_overrides_file_and_deduplicates_admins(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "VR_USERNAME=file-user\n"
        "VR_PASSWORD=file-pass\n"
        "TELEGRAM_ADMIN_IDS=10, 20,10\n"
        "REQUEST_TIMEOUT_SECONDS=9\n"
        "STABILITY_INPUT_FILE=tests/custom_plates.txt\n"
        "STABILITY_DELAY_SECONDS=3\n"
        "CANDIDATE_DELAY_SECONDS=2.5\n",
        encoding="utf-8",
    )

    config = load_config(
        env_file,
        environ={"VR_PASSWORD": "process-pass", "VERIFY_SSL": "false"},
    )

    assert config.telegram_admin_ids == (10, 20)
    assert config.request_timeout_seconds == 9
    assert config.verify_ssl is False
    assert config.stability_input_file.as_posix() == "tests/custom_plates.txt"
    assert config.stability_delay_seconds == 3
    assert config.candidate_delay_seconds == 2.5
    assert config.max_workers == 2
    assert config.captcha_mode == "manual"
    assert "file-user" not in repr(config)
    assert "process-pass" not in repr(config)


@pytest.mark.parametrize("raw", ["abc", "1,-2", "1,,2", "0"])
def test_invalid_admin_ids_are_rejected(raw):
    with pytest.raises(ConfigError):
        load_config(
            None,
            environ={
                "VR_USERNAME": "user",
                "VR_PASSWORD": "pass",
                "TELEGRAM_ADMIN_IDS": raw,
            },
        )


def test_missing_credentials_are_rejected():
    with pytest.raises(ConfigError, match="VR_USERNAME"):
        load_config(None, environ={"TELEGRAM_ADMIN_IDS": "1"})


def test_phase_two_config_requires_token_only_for_bot() -> None:
    common = {
        "VR_USERNAME": "user",
        "VR_PASSWORD": "pass",
        "TELEGRAM_ADMIN_IDS": "1",
    }

    config = load_config(None, environ=common)
    assert config.telegram_bot_token == ""

    with pytest.raises(ConfigError, match="TELEGRAM_BOT_TOKEN"):
        load_config(None, environ=common, require_telegram_token=True)


def test_phase_two_config_is_validated_and_token_is_redacted() -> None:
    config = load_config(
        None,
        environ={
            "VR_USERNAME": "user",
            "VR_PASSWORD": "pass",
            "TELEGRAM_ADMIN_IDS": "1",
            "TELEGRAM_BOT_TOKEN": "synthetic-token",
            "MAX_WORKERS": "3",
            "JOB_QUEUE_SIZE": "7",
            "CAPTCHA_MODE": "auto",
            "CAPTCHA_CONFIDENCE_THRESHOLD": "0.92",
            "SOURCE_SERIALIZE_REQUESTS": "false",
            "SOURCE_REQUEST_ATTEMPTS": "4",
            "SOURCE_RETRY_DELAY_SECONDS": "0.25",
        },
        require_telegram_token=True,
    )

    assert config.max_workers == 3
    assert config.job_queue_size == 7
    assert config.captcha_mode == "auto"
    assert config.captcha_confidence_threshold == 0.92
    assert config.source_serialize_requests is False
    assert config.source_request_attempts == 4
    assert config.source_retry_delay_seconds == 0.25
    assert "synthetic-token" not in repr(config)
    assert "synthetic-token" in config.log_secrets


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("MAX_WORKERS", "9"),
        ("TELEGRAM_POLL_TIMEOUT_SECONDS", "51"),
        ("CAPTCHA_MODE", "unknown"),
        ("CAPTCHA_CONFIDENCE_THRESHOLD", "1.1"),
        ("SOURCE_REQUEST_ATTEMPTS", "0"),
        ("SOURCE_RETRY_DELAY_SECONDS", "nan"),
    ],
)
def test_invalid_phase_two_config_is_rejected(key, value) -> None:
    with pytest.raises(ConfigError):
        load_config(
            None,
            environ={
                "VR_USERNAME": "user",
                "VR_PASSWORD": "pass",
                "TELEGRAM_ADMIN_IDS": "1",
                key: value,
            },
        )


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_non_finite_timeout_is_rejected(value):
    with pytest.raises(ConfigError, match="REQUEST_TIMEOUT_SECONDS"):
        load_config(
            None,
            environ={
                "VR_USERNAME": "user",
                "VR_PASSWORD": "pass",
                "TELEGRAM_ADMIN_IDS": "1",
                "REQUEST_TIMEOUT_SECONDS": value,
            },
        )


def test_redacting_formatter_hides_values_and_assignments():
    formatter = RedactingFormatter("%(message)s", secrets=("secret-value",))
    record = logging.LogRecord(
        "test",
        logging.INFO,
        __file__,
        1,
        "credential=%s password=hunter2 captcha:abcd",
        ("secret-value",),
        None,
    )

    rendered = formatter.format(record)

    assert "secret-value" not in rendered
    assert "hunter2" not in rendered
    assert "abcd" not in rendered
    assert rendered.count("[REDACTED]") == 3


def test_redacting_formatter_hides_secrets_inside_exception_traceback():
    formatter = RedactingFormatter("%(message)s\n%(exc_text)s", secrets=("top-secret",))
    try:
        raise RuntimeError("token=top-secret password=hunter2")
    except RuntimeError:
        exc_info = sys.exc_info()
    record = logging.LogRecord(
        "test", logging.ERROR, __file__, 1, "failed top-secret", (), exc_info
    )

    rendered = formatter.format(record)

    assert "top-secret" not in rendered
    assert "hunter2" not in rendered
