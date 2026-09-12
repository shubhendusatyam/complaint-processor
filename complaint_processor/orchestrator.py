"""Workflow orchestration: the three AI tasks, per document and across a batch.

Two levels of concurrency:

  * Within one document, the email and summary tasks both depend only on the
    extraction, so once it is available they run together via RunnableParallel.
  * Across documents, a thread pool runs whole pipelines side by side.

The dependency is what shapes this. Extraction must finish first because it is
the input to the other two, which is why this is a workflow rather than one
combined prompt.

Failure is contained per document. A document that fails is still returned as a
ProcessingResult so it appears in the final report instead of vanishing.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

from langchain_core.runnables import Runnable, RunnableParallel

from .chains.base import ChainError, format_case_data
from .chains.email import build_email_chain
from .chains.extraction import build_extraction_chain
from .chains.summary import build_summary_chain
from .config import Settings, settings
from .ingestion.base import DocumentLoadError, SourceDocument
from .ingestion.registry import discover_documents, load_document
from .logging_setup import get_logger
from .schemas import ProcessingResult

logger = get_logger(__name__)

ProgressCallback = Callable[[int, int, ProcessingResult], None]


@dataclass(frozen=True)
class Workflow:
    """The three chains, built once and shared across every document.

    Building them per document would re-create the model client for each file
    for no benefit.
    """

    extraction: Runnable
    followups: Runnable

    @classmethod
    def build(cls, retry: bool = True) -> "Workflow":
        # Both follow-up tasks take the same input, so RunnableParallel runs
        # them concurrently and returns both results in one step.
        followups = RunnableParallel(
            customer_email=build_email_chain(retry=retry),
            case_summary=build_summary_chain(retry=retry),
        )
        return cls(extraction=build_extraction_chain(retry=retry), followups=followups)


def process_document(document: SourceDocument, workflow: Workflow) -> ProcessingResult:
    """Run all three AI tasks for one already-loaded document.

    Never raises. Every failure becomes a ProcessingResult carrying the reason.
    """
    try:
        extraction = workflow.extraction.invoke(
            {"filename": document.filename, "document_text": document.text}
        )
    except Exception as exc:
        logger.error("Extraction failed for %s: %s", document.filename, exc)
        return ProcessingResult.failure(
            document.filename, document.file_type, f"Extraction failed: {exc}"
        )

    logger.info(
        "Extracted %s: category=%s status=%s",
        document.filename,
        extraction.complaint_category.value,
        extraction.case_status.value,
    )

    try:
        followups = workflow.followups.invoke({"case_data": format_case_data(extraction)})
    except Exception as exc:
        # The structured data is still good, so keep it and record the gap.
        logger.error("Follow-up tasks failed for %s: %s", document.filename, exc)
        return ProcessingResult.from_document(
            document,
            extraction=extraction,
            error=f"Email and summary generation failed: {exc}",
        )

    logger.info("Completed %s", document.filename)
    return ProcessingResult.from_document(
        document,
        extraction=extraction,
        customer_email=followups["customer_email"],
        case_summary=followups["case_summary"],
    )


def process_file(path: Path, workflow: Workflow) -> ProcessingResult:
    """Load one file and run the workflow over it."""
    try:
        document = load_document(path)
    except DocumentLoadError as exc:
        logger.error("Could not read %s: %s", path.name, exc)
        return ProcessingResult.failure(
            path.name, path.suffix.lower().lstrip("."), str(exc)
        )
    return process_document(document, workflow)


def process_batch(
    paths: Sequence[Path] | None = None,
    config: Settings | None = None,
    workflow: Workflow | None = None,
    max_workers: int | None = None,
    on_progress: ProgressCallback | None = None,
) -> list[ProcessingResult]:
    """Process every document, returning one result per file in input order.

    Results keep the input order regardless of which finishes first, so the
    report is reproducible across runs.
    """
    config = config or settings
    workflow = workflow or Workflow.build()
    if paths is None:
        paths = discover_documents(config.data_dir)
    paths = list(paths)

    if not paths:
        logger.warning("Nothing to process")
        return []

    workers = max(1, min(max_workers or config.max_workers, len(paths)))
    logger.info("Processing %d document(s) with %d worker(s)", len(paths), workers)

    results: dict[Path, ProcessingResult] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(process_file, path, workflow): path for path in paths}
        for done, future in enumerate(as_completed(futures), start=1):
            path = futures[future]
            result = future.result()  # process_file never raises
            results[path] = result
            if on_progress is not None:
                on_progress(done, len(paths), result)

    ordered = [results[path] for path in paths]
    _log_summary(ordered)
    return ordered


def _log_summary(results: Iterable[ProcessingResult]) -> None:
    counts: dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    logger.info(
        "Batch finished: %s",
        ", ".join(f"{count} {status}" for status, count in sorted(counts.items())),
    )
