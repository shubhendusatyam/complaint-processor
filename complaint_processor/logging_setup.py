"""Logging configuration shared by the CLI and the Streamlit app."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from .config import settings

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# These emit one INFO line per HTTP request, which buries batch progress.
# Matched by prefix: the OpenAI client vendors its transport under names like
# "httpx2", so an exact-name list silently misses them.
NOISY_LOGGER_PREFIXES = ("httpx", "httpcore", "openai", "urllib3", "langsmith")


def configure_logging(level: str | None = None, log_path: Path | None = None) -> None:
    """Attach a console handler and a file handler to the root logger.

    Safe to call more than once; existing handlers are cleared first so the
    Streamlit app's reruns do not stack up duplicate output.
    """
    level_name = (level or settings.log_level).upper()
    resolved_level = getattr(logging, level_name, logging.INFO)
    path = log_path or settings.log_path
    path.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)

    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    root.setLevel(resolved_level)
    root.addHandler(console)
    root.addHandler(file_handler)

    quieten_noisy_loggers()


def quieten_noisy_loggers() -> None:
    """Raise third-party HTTP loggers to WARNING, by name prefix.

    Applied to loggers that already exist and, via a filter on the root, to any
    that appear later once the API clients are constructed.
    """
    for name in list(logging.root.manager.loggerDict):
        if name.startswith(NOISY_LOGGER_PREFIXES):
            logging.getLogger(name).setLevel(logging.WARNING)

    for handler in logging.getLogger().handlers:
        handler.addFilter(_not_noisy)


def _not_noisy(record: logging.LogRecord) -> bool:
    if record.levelno >= logging.WARNING:
        return True
    return not record.name.startswith(NOISY_LOGGER_PREFIXES)


def get_logger(name: str) -> logging.Logger:
    """Module-level logger, so log lines name their origin."""
    return logging.getLogger(name)
