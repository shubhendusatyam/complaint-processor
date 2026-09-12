"""Command line entry point: process every document in the data folder.

Holds no prompts and makes no API calls. It parses arguments, delegates to the
orchestrator, hands the results to the reporting layer, and prints a summary.

    python main.py
    python main.py --data-dir samples --workers 8
    python main.py --log-level DEBUG
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path

from complaint_processor.config import ConfigError, Settings, settings, validate
from complaint_processor.ingestion.base import DocumentLoadError
from complaint_processor.logging_setup import configure_logging
from complaint_processor.orchestrator import Workflow, process_batch
from complaint_processor.reporting import write_all
from complaint_processor.schemas import ProcessingResult


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Process customer complaint documents into structured data, "
        "customer emails and internal case summaries.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="Folder holding the complaint documents (default: data/)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Where to write the results (default: output/)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        help="Documents to process concurrently (default: MAX_WORKERS from .env)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Console and log file verbosity (default: LOG_LEVEL from .env)",
    )
    return parser.parse_args(argv)


def build_settings(args: argparse.Namespace) -> Settings:
    """Apply command line overrides on top of the environment configuration."""
    overrides: dict[str, object] = {}
    if args.data_dir:
        overrides["data_dir"] = args.data_dir.resolve()
    if args.output_dir:
        overrides["output_dir"] = args.output_dir.resolve()
    if args.workers:
        overrides["max_workers"] = args.workers
    if args.log_level:
        overrides["log_level"] = args.log_level
    return dataclasses.replace(settings, **overrides) if overrides else settings


def _report_progress(done: int, total: int, result: ProcessingResult) -> None:
    marker = {"success": "ok", "partial": "partial", "failed": "FAILED"}[result.status]
    print(f"  [{done}/{total}] {result.filename} ... {marker}")


def _print_summary(report: dict[str, object], config: Settings) -> None:
    statuses = report["statuses"]
    files = report["files_written"]

    print()
    print(f"Processed {report['documents']} document(s)")
    for status in ("success", "partial", "failed"):
        if status in statuses:
            print(f"  {status:<8} {statuses[status]}")

    print()
    print("Written to", config.output_dir)
    print(f"  structured_data/  {files['structured_data']}")
    print(f"  customer_emails/  {files['customer_emails']}")
    print(f"  case_summaries/   {files['case_summaries']}")
    print(f"  {config.final_report_path.name}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = build_settings(args)
    configure_logging(config.log_level, log_path=config.output_dir / "run.log")

    try:
        validate(config)
    except ConfigError as exc:
        print(f"Configuration problem:\n  {exc}", file=sys.stderr)
        return 2

    print(f"Reading documents from {config.data_dir}")
    try:
        results = process_batch(
            config=config,
            workflow=Workflow.build(),
            on_progress=_report_progress,
        )
    except DocumentLoadError as exc:
        print(f"Could not read the input folder:\n  {exc}", file=sys.stderr)
        return 2

    if not results:
        print("No supported documents found. Nothing to do.", file=sys.stderr)
        return 1

    report = write_all(results, config=config)
    _print_summary(report, config)

    # Non-zero when any document failed, so a scripted run can detect it.
    return 1 if report["statuses"].get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
