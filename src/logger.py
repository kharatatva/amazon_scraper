"""Central logging configuration for the application."""

import copy
import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src.config import LOG_FILE


_run_id = ContextVar("log_run_id", default="-")
_stage = ContextVar("log_stage", default="-")
_configured_path: Path | None = None
logger = logging.getLogger("amazon_data_scaper_and_analytics")


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        """Exclude noisy third-party log records from the configured handlers."""
        record.run_id = _run_id.get()
        record.stage = _stage.get()
        message = record.getMessage()
        message = re.sub(
            r"(https?://)[^/@\s]+@",
            r"\1<redacted>@",
            message,
        )
        record.msg = message
        record.args = ()
        return True


class _ConsoleFormatter(logging.Formatter):
    """Keep console output concise; full tracebacks remain in the log file."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log records with their timestamp, level, and message."""
        concise_record = copy.copy(record)
        concise_record.exc_info = None
        concise_record.exc_text = None
        return super().format(concise_record)


def configure_logging(
    log_file: str | Path = LOG_FILE,
    *,
    console_level: int = logging.INFO,
    file_level: int = logging.DEBUG,
) -> logging.Logger:
    """Configure one console handler and one rotating file handler."""
    global _configured_path

    target_path = Path(log_file)
    if _configured_path == target_path and logger.handlers:
        return logger

    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()

    target_path.parent.mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    context_filter = _ContextFilter()
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | run=%(run_id)s | stage=%(stage)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.addFilter(context_filter)
    console_handler.setFormatter(_ConsoleFormatter(formatter._fmt, formatter.datefmt))

    file_handler = RotatingFileHandler(
        filename=target_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(file_level)
    file_handler.addFilter(context_filter)
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    _configured_path = target_path
    return logger


@contextmanager
def log_context(*, run_id: int | str | None = None, stage: str | None = None):
    """Attach run and stage identifiers to logs emitted in this context."""
    run_token = _run_id.set(str(run_id) if run_id is not None else "-")
    stage_token = _stage.set(stage or "-")
    try:
        yield
    finally:
        _run_id.reset(run_token)
        _stage.reset(stage_token)


configure_logging()
