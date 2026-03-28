"""Logging configuration for zen2api."""
from __future__ import annotations

import logging
import re
from typing import Optional

from . import config

_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_REQUEST_PATH_RE = re.compile(r'[A-Z]+\s+([^"\s?]+)')

_HEALTH_ENDPOINTS = frozenset({"/health"})

_initialized = False


def _extract_request_path(record: logging.LogRecord) -> Optional[str]:
    """Extract request path from app and uvicorn access log records."""
    try:
        if isinstance(record.args, tuple) and len(record.args) >= 2:
            return str(record.args[1])
    except Exception:
        pass

    message = record.getMessage()
    match = _REQUEST_PATH_RE.search(message)
    if match:
        return match.group(1)
    return None


def should_log_request(record: logging.LogRecord) -> bool:
    """Return whether the request path should be logged."""
    if config.LOG_HEALTH_CHECK:
        return True

    path = _extract_request_path(record)
    if path is None:
        return True

    paths = {path}
    normalized_paths = {p.lower() for p in paths}
    if normalized_paths & _HEALTH_ENDPOINTS:
        return False

    return True


class RequestPathFilter(logging.Filter):
    """Filter noisy health-check request logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        return should_log_request(record)


def setup() -> None:
    """Configure logging for zen2api."""
    global _initialized
    if _initialized:
        return

    level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # Root logger
    root = logging.getLogger()
    root.setLevel(level)

    # Stderr handler
    stderr_handler = logging.StreamHandler()
    stderr_handler.setLevel(level)
    stderr_handler.setFormatter(formatter)
    root.addHandler(stderr_handler)

    # File handler if configured
    if config.LOG_FILE:
        file_handler = logging.FileHandler(config.LOG_FILE, encoding="utf-8")
        file_handler.setLevel(logging.WARNING)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    # Apply filter to uvicorn access logger
    access_loggers = [logging.getLogger("uvicorn.access")]
    for logger in access_loggers:
        logger.addFilter(RequestPathFilter())

    # Suppress noisy loggers
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)

    _initialized = True


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with zen2api prefix."""
    return logging.getLogger(f"zen2api.{name}")
