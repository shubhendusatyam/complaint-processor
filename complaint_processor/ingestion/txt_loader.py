"""Plain text loader."""

from __future__ import annotations

from pathlib import Path

from .base import DocumentLoadError

# Tried in order. Complaint exports from Windows tooling are often cp1252,
# and latin-1 decodes any byte sequence, so it never raises.
_ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")


def extract_text(path: Path) -> str:
    last_error: UnicodeDecodeError | None = None

    for encoding in _ENCODINGS:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
        except OSError as exc:
            raise DocumentLoadError(f"Could not read {path.name}: {exc}") from exc

    raise DocumentLoadError(
        f"Could not decode {path.name} with any of {', '.join(_ENCODINGS)}: {last_error}"
    )
