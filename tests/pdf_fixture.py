"""Minimal text-only PDF writer, used to build test fixtures and sample data.

Avoids pulling in a PDF generation library for what is only ever a few pages
of plain Helvetica text.
"""

from __future__ import annotations

from pathlib import Path

PAGE_WIDTH, PAGE_HEIGHT = 612, 792
MARGIN_X, MARGIN_TOP = 60, 740
FONT_SIZE, LEADING = 11, 15
LINES_PER_PAGE = 44


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _content_stream(lines: list[str]) -> bytes:
    parts = [
        "BT",
        f"/F1 {FONT_SIZE} Tf",
        f"{LEADING} TL",
        f"{MARGIN_X} {MARGIN_TOP} Td",
    ]
    for index, line in enumerate(lines):
        if index:
            parts.append("T*")
        parts.append(f"({_escape(line)}) Tj")
    parts.append("ET")
    return "\n".join(parts).encode("latin-1", errors="replace")


def write_pdf(path: Path, text: str) -> Path:
    """Write `text` to `path` as a PDF, wrapping onto extra pages as needed."""
    all_lines = text.replace("\r\n", "\n").split("\n")
    pages = [
        all_lines[i : i + LINES_PER_PAGE]
        for i in range(0, max(len(all_lines), 1), LINES_PER_PAGE)
    ] or [[""]]

    font_obj = 3
    page_objs = [4 + 2 * i for i in range(len(pages))]
    content_objs = [num + 1 for num in page_objs]

    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: (
            "<< /Type /Pages /Kids ["
            + " ".join(f"{n} 0 R" for n in page_objs)
            + f"] /Count {len(pages)} >>"
        ).encode("latin-1"),
        font_obj: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }

    for page_num, content_num, lines in zip(page_objs, content_objs, pages):
        objects[page_num] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
            f"/Contents {content_num} 0 R "
            f"/Resources << /Font << /F1 {font_obj} 0 R >> >> >>"
        ).encode("latin-1")
        stream = _content_stream(lines)
        objects[content_num] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1")
            + stream
            + b"\nendstream"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += f"{number} 0 obj\n".encode("latin-1") + objects[number] + b"\nendobj\n"

    xref_offset = len(out)
    count = max(objects) + 1
    out += f"xref\n0 {count}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for number in range(1, count):
        out += f"{offsets[number]:010d} 00000 n \n".encode("latin-1")
    out += (
        f"trailer\n<< /Size {count} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n"
    ).encode("latin-1")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out))
    return path
