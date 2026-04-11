from __future__ import annotations

import logging
from collections.abc import Callable


StatusCallback = Callable[[str, int | None], None]


def normalize_notify_type(notify_type: str | None) -> str:
    normalized = (notify_type or "info").strip().lower()
    if normalized == "warn":
        return "warning"
    if normalized in {"info", "success", "warning", "error"}:
        return normalized
    return "info"


def notify_user(
    app_state,
    message: str,
    notify_type: str = "info",
    *,
    show_status: StatusCallback | None = None,
    status_timeout_ms: int | None = None,
) -> None:
    text = (message or "").strip()
    if not text:
        return
    app_state.notify(text, normalize_notify_type(notify_type))
    if show_status is not None:
        show_status(text, status_timeout_ms)


def log_and_notify(
    app_state,
    logger_: logging.Logger,
    log_level: int,
    message: str,
    notify_type: str,
    *,
    show_status: StatusCallback | None = None,
    status_timeout_ms: int | None = None,
) -> None:
    text = (message or "").strip()
    if not text:
        return
    logger_.log(int(log_level), text)
    notify_user(
        app_state,
        text,
        notify_type,
        show_status=show_status,
        status_timeout_ms=status_timeout_ms,
    )


def exception_message(prefix: str, exc: Exception) -> str:
    details = str(exc).strip()
    if not details:
        return prefix.rstrip(".")
    return f"{prefix.rstrip('.')}: {details}"
