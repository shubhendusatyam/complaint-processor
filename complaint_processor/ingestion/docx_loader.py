"""Word document loader built on python-docx.

Complaint forms routinely put the customer details in a table, so paragraph
text alone would silently drop the name, email and phone number. This loader
walks the document body in order and reads both paragraphs and tables.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import docx
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from .base import DocumentLoadError


def _iter_blocks(parent) -> Iterator[Paragraph | Table]:
    """Yield paragraphs and tables in the order they appear in the document."""
    body = parent.element.body
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield Table(child, parent)


def _render_table(table: Table) -> str:
    """Flatten a table to one line per row, cells separated by a pipe.

    Keeps the label-to-value pairing intact, which is what the extraction
    chain needs in order to read a details table correctly.
    """
    lines: list[str] = []
    for row in table.rows:
        cells = [cell.text.strip() for cell in row.cells]
        if any(cells):
            lines.append(" | ".join(cells))
    return "\n".join(lines)


def extract_text(path: Path) -> str:
    try:
        document = docx.Document(str(path))
    except Exception as exc:
        raise DocumentLoadError(f"Could not open Word document {path.name}: {exc}") from exc

    parts: list[str] = []
    for block in _iter_blocks(document):
        if isinstance(block, Paragraph):
            if block.text.strip():
                parts.append(block.text)
        else:
            rendered = _render_table(block)
            if rendered:
                parts.append(rendered)

    text = "\n".join(parts)

    if not text.strip():
        raise DocumentLoadError(f"{path.name} contains no readable text")

    return text
