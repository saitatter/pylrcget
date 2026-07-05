from __future__ import annotations

import logging

LOG_VERBOSITY_ERROR = "error"
LOG_VERBOSITY_WARNING = "warning"
LOG_VERBOSITY_INFO = "info"
LOG_VERBOSITY_DEBUG = "debug"

LOG_VERBOSITY_CHOICES = (
    LOG_VERBOSITY_ERROR,
    LOG_VERBOSITY_WARNING,
    LOG_VERBOSITY_INFO,
    LOG_VERBOSITY_DEBUG,
)


def normalize_logging_verbosity(value: str | None) -> str:
    normalized = (value or LOG_VERBOSITY_INFO).strip().lower()
    if normalized in {"error", "errors"}:
        return LOG_VERBOSITY_ERROR
    if normalized in {"warning", "warn", "warnings"}:
        return LOG_VERBOSITY_WARNING
    if normalized in {"debug", "verbose", "verbosity"}:
        return LOG_VERBOSITY_DEBUG
    return LOG_VERBOSITY_INFO


def logging_level_from_verbosity(value: str | None) -> int:
    verbosity = normalize_logging_verbosity(value)
    if verbosity == LOG_VERBOSITY_ERROR:
        return logging.ERROR
    if verbosity == LOG_VERBOSITY_WARNING:
        return logging.WARNING
    if verbosity == LOG_VERBOSITY_DEBUG:
        return logging.DEBUG
    return logging.INFO


def apply_logging_verbosity(value: str | None) -> int:
    level = logging_level_from_verbosity(value)
    root = logging.getLogger()
    root.setLevel(level)
    for handler in root.handlers:
        handler.setLevel(level)
    return level
