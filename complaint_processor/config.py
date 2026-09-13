"""Configuration loaded from the environment.

Paths resolve against the project root derived from this file's location, not
the current working directory, so the CLI and the Streamlit app see the same
data and output folders regardless of where they are launched from.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env")


class ConfigError(RuntimeError):
    """Raised when configuration is missing or unusable."""


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number, got {raw!r}") from None


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from None


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    openai_model: str
    openai_temperature: float
    max_workers: int
    log_level: str
    project_root: Path
    data_dir: Path
    output_dir: Path

    @property
    def structured_data_dir(self) -> Path:
        return self.output_dir / "structured_data"

    @property
    def customer_emails_dir(self) -> Path:
        return self.output_dir / "customer_emails"

    @property
    def case_summaries_dir(self) -> Path:
        return self.output_dir / "case_summaries"

    @property
    def final_report_path(self) -> Path:
        return self.output_dir / "final_report.csv"

    @property
    def log_path(self) -> Path:
        return self.output_dir / "run.log"

    def ensure_output_dirs(self) -> None:
        """Create the output tree. Safe to call repeatedly."""
        for directory in (
            self.output_dir,
            self.structured_data_dir,
            self.customer_emails_dir,
            self.case_summaries_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def _build_settings() -> Settings:
    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        openai_temperature=_env_float("OPENAI_TEMPERATURE", 0.0),
        max_workers=_env_int("MAX_WORKERS", 4),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        project_root=PROJECT_ROOT,
        data_dir=PROJECT_ROOT / "data",
        output_dir=PROJECT_ROOT / "output",
    )


settings = _build_settings()


def validate(config: Settings | None = None, require_data_dir: bool = True) -> Settings:
    """Check that the settings are usable before any API call is attempted.

    Called by the entry points rather than at import time, so that tests and
    tooling can import this package without a key present.

    require_data_dir is for callers that supply their own documents instead of
    reading the batch folder. An upload has nothing to do with data/ existing,
    and rejecting one on a missing folder would report the wrong cause.
    """
    config = config or settings

    if not config.openai_api_key:
        raise ConfigError(
            "OPENAI_API_KEY is not set. Copy .env.example to .env and add your "
            "key:\n    Copy-Item .env.example .env"
        )

    # Catch an unedited template before the request goes out, so the failure
    # names the real problem instead of arriving as a 401 from OpenAI.
    if "REPLACE" in config.openai_api_key.upper() or config.openai_api_key.endswith(
        "your-key-here"
    ):
        raise ConfigError(
            "OPENAI_API_KEY is still the placeholder value. Edit .env and set your "
            "real key from https://platform.openai.com/api-keys"
        )

    if config.max_workers < 1:
        raise ConfigError(f"MAX_WORKERS must be at least 1, got {config.max_workers}")

    if require_data_dir and not config.data_dir.is_dir():
        raise ConfigError(
            f"Input folder not found: {config.data_dir}\n"
            "Create it and add the complaint documents to process."
        )

    return config
