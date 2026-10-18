"""Logging configuration with mandatory secret redaction."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from swiftdrop.redact import redact

LOGGER_NAME = "swiftdrop"


class RedactingFilter(logging.Filter):
    """Redacts the fully formatted message so arguments are covered too."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # malformed format args – keep the raw template
            message = str(record.msg)
        record.msg = redact(message)
        record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


def configure_logging(logs_dir: Path, verbose: bool = False) -> Path:
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "swiftdrop.log"
    root = logging.getLogger(LOGGER_NAME)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(threadName)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter())
    root.addHandler(handler)
    root.propagate = False

    # pywebview logs bridge errors (including tracebacks) on its own logger.
    webview_logger = logging.getLogger("pywebview")
    webview_logger.addFilter(RedactingFilter())
    return log_file


def set_verbose(verbose: bool) -> None:
    logging.getLogger(LOGGER_NAME).setLevel(logging.DEBUG if verbose else logging.INFO)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{name}")
