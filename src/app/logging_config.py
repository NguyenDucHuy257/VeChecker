"""Small logging setup with mandatory secret redaction."""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterable


_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)(?P<prefix>[\"']?\b(?:password|passwd|pwd|token|captcha|cookie|authorization)"
    r"\b[\"']?\s*[:=]\s*)(?P<quote>[\"']?)(?P<value>[^\s,;}\]\"']+)"
    r"(?P=quote)"
)


class RedactingFormatter(logging.Formatter):
    """Redact configured secret values and common secret assignments."""

    def __init__(self, *args: object, secrets: Iterable[str] = (), **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._secrets = tuple(
            sorted({str(value) for value in secrets if value}, key=len, reverse=True)
        )

    def format(self, record: logging.LogRecord) -> str:
        rendered = super().format(record)
        for secret in self._secrets:
            rendered = rendered.replace(secret, "[REDACTED]")
        return _SENSITIVE_ASSIGNMENT.sub(
            lambda match: (
                f"{match.group('prefix')}{match.group('quote')}"
                f"[REDACTED]{match.group('quote')}"
            ),
            rendered,
        )


def configure_logging(
    level: str | int = "INFO",
    *,
    secrets: Iterable[str] = (),
) -> None:
    """Configure the root logger for the application.

    Existing root handlers are replaced so repeated test/application startup does
    not duplicate log lines.
    """

    if isinstance(level, str):
        normalized = level.upper()
        numeric_level = logging.getLevelNamesMapping().get(normalized)
        if numeric_level is None:
            raise ValueError(f"Invalid log level: {level}")
    else:
        numeric_level = level

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        RedactingFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
            secrets=secrets,
        )
    )
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(numeric_level)
