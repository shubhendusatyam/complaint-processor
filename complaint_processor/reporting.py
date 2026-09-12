"""Writes the four output artifacts.

  output/structured_data/<name>.json    validated extraction, one per document
  output/customer_emails/<name>.txt     generated reply
  output/case_summaries/<name>.md       internal summary
  output/final_report.csv               one row per document, including failures

Every file is written as UTF-8 explicitly. Generated emails contain curly
quotes and accented names, which the Windows default codepage mangles.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

import pandas as pd

from .config import Settings, settings
from .logging_setup import get_logger
from .schemas import REPORT_COLUMNS, ProcessingResult

logger = get_logger(__name__)

ENCODING = "utf-8"

# Excel needs the byte order mark to read accented names correctly from a CSV.
# Every other reader tolerates it.
CSV_ENCODING = "utf-8-sig"


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding=ENCODING)
    return path


def output_stem(result: ProcessingResult, taken: set[str] | None = None) -> str:
    """Base name for this document's output files.

    Two source files can share a stem across formats, for example
    complaint_001.txt and complaint_001.pdf. When that happens the extension is
    folded in so neither silently overwrites the other.
    """
    stem = Path(result.filename).stem
    if taken is None or stem not in taken:
        return stem
    return f"{stem}_{result.file_type}"


def write_structured_data(result: ProcessingResult, directory: Path, stem: str) -> Path | None:
    """Write the validated extraction as JSON, wrapped with its provenance."""
    if result.extraction is None:
        return None

    payload = {
        "source_file": result.filename,
        "file_type": result.file_type,
        "processing_status": result.status,
        "extraction": result.extraction.model_dump(mode="json"),
    }
    return _write(
        directory / f"{stem}.json",
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
    )


def write_customer_email(result: ProcessingResult, directory: Path, stem: str) -> Path | None:
    if result.customer_email is None:
        return None
    return _write(directory / f"{stem}.txt", result.customer_email.render())


def write_case_summary(result: ProcessingResult, directory: Path, stem: str) -> Path | None:
    if result.case_summary is None:
        return None
    header = f"# Case Summary: {result.filename}\n\n"
    return _write(directory / f"{stem}.md", header + result.case_summary.render())


def write_final_report(results: Sequence[ProcessingResult], path: Path) -> Path:
    """Write the consolidated CSV, one row per document.

    Failed documents get a row too, so the report accounts for every input file
    rather than quietly listing only the ones that worked.
    """
    frame = pd.DataFrame(
        [r.to_report_row() for r in results], columns=REPORT_COLUMNS
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding=CSV_ENCODING)
    return path


def write_all(
    results: Sequence[ProcessingResult], config: Settings | None = None
) -> dict[str, object]:
    """Write every artifact for a finished batch and report what was produced."""
    config = config or settings
    config.ensure_output_dirs()

    taken: set[str] = set()
    counts = {"structured_data": 0, "customer_emails": 0, "case_summaries": 0}

    for result in results:
        stem = output_stem(result, taken)
        taken.add(stem)

        if write_structured_data(result, config.structured_data_dir, stem):
            counts["structured_data"] += 1
        if write_customer_email(result, config.customer_emails_dir, stem):
            counts["customer_emails"] += 1
        if write_case_summary(result, config.case_summaries_dir, stem):
            counts["case_summaries"] += 1

    report_path = write_final_report(results, config.final_report_path)

    statuses: dict[str, int] = {}
    for result in results:
        statuses[result.status] = statuses.get(result.status, 0) + 1

    logger.info(
        "Wrote %d structured file(s), %d email(s), %d summary/summaries and %s",
        counts["structured_data"],
        counts["customer_emails"],
        counts["case_summaries"],
        report_path.name,
    )

    return {
        "documents": len(results),
        "statuses": statuses,
        "files_written": counts,
        "final_report": report_path,
    }
