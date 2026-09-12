"""PDF loader built on pypdf."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .base import DocumentLoadError


def extract_text(path: Path) -> str:
    try:
        reader = PdfReader(path)
    except (PdfReadError, OSError, ValueError) as exc:
        raise DocumentLoadError(f"Could not open PDF {path.name}: {exc}") from exc

    if reader.is_encrypted:
        # An empty-password decrypt covers PDFs that are merely permission-locked.
        try:
            reader.decrypt("")
        except Exception as exc:
            raise DocumentLoadError(
                f"{path.name} is password protected and cannot be read"
            ) from exc

    pages: list[str] = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            pages.append(page.extract_text() or "")
        except Exception as exc:
            # One unreadable page should not cost us the rest of the document.
            raise DocumentLoadError(
                f"Failed to extract page {number} of {path.name}: {exc}"
            ) from exc

    text = "\n\n".join(part for part in pages if part.strip())

    if not text.strip():
        raise DocumentLoadError(
            f"{path.name} contains no extractable text. It is most likely a "
            "scanned image, which would need OCR rather than text extraction."
        )

    return text
