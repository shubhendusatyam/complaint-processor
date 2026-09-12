"""Shared contract for document loaders.

Every loader is a callable taking a path and returning raw text. The registry
wraps that text into a SourceDocument, so individual loaders stay small and
deal only with their own file format.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

# Three or more consecutive newlines carry no meaning and waste prompt tokens.
_EXCESS_BLANK_LINES = re.compile(r"\n{3,}")
_TRAILING_SPACES = re.compile(r"[ \t]+$", re.MULTILINE)


class DocumentLoadError(Exception):
    """A document could not be read or produced no usable text.

    Raised per document so the batch can log it and carry on.
    """


class UnsupportedFormatError(DocumentLoadError):
    """The file extension has no registered loader."""


class TextExtractor(Protocol):
    """What every loader module's extract_text function must look like."""

    def __call__(self, path: Path) -> str: ...


class SourceDocument(BaseModel):
    """One ingested document, ready to hand to the extraction chain."""

    filename: str = Field(description="File name including extension")
    path: Path = Field(description="Absolute path on disk")
    file_type: str = Field(description="Lowercase extension without the dot")
    text: str = Field(description="Extracted textual content")

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def stem(self) -> str:
        """Base name without extension, used to name the output files."""
        return self.path.stem


def normalize_text(raw: str) -> str:
    """Tidy extracted text without altering its meaning.

    PDF and DOCX extraction both produce ragged whitespace. Collapsing it keeps
    prompts cheaper and makes the extracted text readable when debugging.
    """
    cleaned = raw.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _TRAILING_SPACES.sub("", cleaned)
    cleaned = _EXCESS_BLANK_LINES.sub("\n\n", cleaned)
    return cleaned.strip()
