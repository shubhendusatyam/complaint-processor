"""Document loaders. One per supported format, behind a shared interface."""

from .base import (
    DocumentLoadError,
    SourceDocument,
    UnsupportedFormatError,
    normalize_text,
)
from .registry import (
    SUPPORTED_EXTENSIONS,
    discover_documents,
    is_supported,
    load_document,
)

__all__ = [
    "DocumentLoadError",
    "SourceDocument",
    "UnsupportedFormatError",
    "normalize_text",
    "SUPPORTED_EXTENSIONS",
    "discover_documents",
    "is_supported",
    "load_document",
]
