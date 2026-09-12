"""Maps file extensions to loaders and turns files into SourceDocuments.

This is the only module that knows which formats are supported. Adding a
format means writing a loader and adding one entry to LOADERS.
"""

from __future__ import annotations

from pathlib import Path

from ..logging_setup import get_logger
from . import docx_loader, pdf_loader, txt_loader
from .base import (
    DocumentLoadError,
    SourceDocument,
    TextExtractor,
    UnsupportedFormatError,
    normalize_text,
)

logger = get_logger(__name__)

LOADERS: dict[str, TextExtractor] = {
    ".txt": txt_loader.extract_text,
    ".pdf": pdf_loader.extract_text,
    ".docx": docx_loader.extract_text,
}

SUPPORTED_EXTENSIONS = frozenset(LOADERS)


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in LOADERS


def get_loader(path: Path) -> TextExtractor:
    loader = LOADERS.get(path.suffix.lower())
    if loader is None:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise UnsupportedFormatError(
            f"No loader for {path.name}. Supported formats: {supported}"
        )
    return loader


def load_document(path: Path) -> SourceDocument:
    """Read one file into a SourceDocument.

    Raises DocumentLoadError on any failure, so the caller decides whether to
    skip the document or abort. The batch orchestrator skips.
    """
    loader = get_loader(path)
    raw = loader(path)
    text = normalize_text(raw)

    if not text:
        raise DocumentLoadError(f"{path.name} produced no text after extraction")

    document = SourceDocument(
        filename=path.name,
        path=path.resolve(),
        file_type=path.suffix.lower().lstrip("."),
        text=text,
    )
    logger.debug("Loaded %s (%d characters)", document.filename, document.char_count)
    return document


def discover_documents(data_dir: Path) -> list[Path]:
    """List the processable files in a folder, sorted for a stable run order.

    Unsupported and hidden files are skipped with a log line rather than an
    error, so dropping a stray README into the data folder does not break a run.
    """
    if not data_dir.is_dir():
        raise DocumentLoadError(f"Input folder not found: {data_dir}")

    found: list[Path] = []
    for entry in sorted(data_dir.iterdir()):
        if not entry.is_file() or entry.name.startswith("."):
            continue
        if is_supported(entry):
            found.append(entry)
        else:
            logger.warning("Skipping unsupported file: %s", entry.name)

    if not found:
        logger.warning(
            "No supported documents found in %s. Expected one of: %s",
            data_dir,
            ", ".join(sorted(SUPPORTED_EXTENSIONS)),
        )

    return found
