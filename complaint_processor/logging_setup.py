"""Logging configuration shared by the CLI and the Streamlit app."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from .config import settings

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# These emit one INFO line per HTTP request, which buries batch progress.
NOISY_LOGGERS = ("httpx", "httpcore", "openai", "urllib3")


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

    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Module-level logger, so log lines name their origin."""
    return logging.getLogger(name)
