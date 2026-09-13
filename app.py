"""Streamlit interface for the complaint processing workflow.

Holds no prompts and makes no API calls of its own. Every run goes through the
same orchestrator the command line uses, so the two interfaces cannot drift.

    streamlit run app.py
"""

from __future__ import annotations

import dataclasses
import os
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

# Secret names shared with .env; see .streamlit/secrets.toml.example.
_SECRET_KEYS = (
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "OPENAI_TEMPERATURE",
    "MAX_WORKERS",
    "LOG_LEVEL",
)


def _export_secrets_to_env() -> None:
    """Copy Streamlit secrets into the environment.

    Streamlit Community Cloud supplies credentials through st.secrets and has no
    .env file. config.py reads the environment and builds its Settings at import
    time, so this has to run before the package is imported anywhere — which is
    why the call sits between the imports rather than below them.

    An existing environment variable always wins, so this never overrides a key
    that is already set, and locally it does nothing at all.
    """
    try:
        secrets = st.secrets
    except Exception:
        # No secrets file, which is the normal local case: .env covers it.
        return

    for name in _SECRET_KEYS:
        if os.environ.get(name):
            continue
        try:
            value = secrets[name]
        except Exception:
            continue
        if value is not None:
            os.environ[name] = str(value)


_export_secrets_to_env()

from complaint_processor.config import ConfigError, settings, validate  # noqa: E402
from complaint_processor.ingestion.registry import SUPPORTED_EXTENSIONS  # noqa: E402
from complaint_processor.logging_setup import configure_logging  # noqa: E402
from complaint_processor.orchestrator import Workflow, process_batch  # noqa: E402
from complaint_processor.reporting import write_all  # noqa: E402
from complaint_processor.schemas import REPORT_COLUMNS, ProcessingResult  # noqa: E402

STATUS_ICON = {"success": "✅", "partial": "⚠️", "failed": "❌"}

st.set_page_config(page_title="Complaint Processing", page_icon="📋", layout="wide")


@st.cache_resource
def get_workflow() -> Workflow:
    """Build the chains once and reuse them across reruns."""
    return Workflow.build()


def run_batch(paths: list[Path], workers: int, output_dir: Path) -> list[ProcessingResult]:
    config = dataclasses.replace(settings, output_dir=output_dir, max_workers=workers)
    configure_logging(config.log_level, log_path=config.output_dir / "run.log")

    progress = st.progress(0.0, text="Starting...")

    def on_progress(done: int, total: int, result: ProcessingResult) -> None:
        progress.progress(done / total, text=f"{done} of {total}: {result.filename}")

    results = process_batch(
        paths=paths, config=config, workflow=get_workflow(), on_progress=on_progress
    )
    progress.empty()
    write_all(results, config=config)
    return results


def show_extraction(result: ProcessingResult) -> None:
    got = result.extraction
    left, right = st.columns(2)
    with left:
        st.markdown("**Customer**")
        st.write(f"Name: {got.customer_name or '_not recorded_'}")
        st.write(f"Email: {got.email or '_not recorded_'}")
        st.write(f"Phone: {got.phone_number or '_not recorded_'}")
    with right:
        st.markdown("**Case**")
        st.write(f"Category: {got.complaint_category.value}")
        st.write(f"Status: {got.case_status.value}")
        st.write(f"Is a complaint: {got.is_complaint}")
        st.write(f"Escalation required: {got.escalation_required}")
        st.write(f"Supporting evidence: {got.supporting_document_available}")

    st.markdown("**Issue**")
    st.write(got.issue_description)
    st.markdown("**Resolution provided**")
    st.write(got.resolution_provided or "_none recorded_")


def show_result(result: ProcessingResult) -> None:
    if result.error:
        st.error(result.error)
    if result.extraction is None:
        return

    extracted, email, summary = st.tabs(["Extracted data", "Customer email", "Case summary"])
    with extracted:
        show_extraction(result)
    with email:
        if result.customer_email:
            st.text_input("Subject", result.customer_email.subject, disabled=True)
            st.text_area("Body", result.customer_email.body, height=320, disabled=True)
        else:
            st.warning("No email was generated for this document.")
    with summary:
        if result.case_summary:
            st.markdown(result.case_summary.render())
        else:
            st.warning("No summary was generated for this document.")


st.title("📋 Customer Complaint & Case Processing")
st.caption(
    "Extracts structured case data from complaint documents, then drafts a customer "
    "reply and an internal summary for each one."
)

with st.sidebar:
    st.header("Settings")
    workers = st.slider("Parallel documents", 1, 8, settings.max_workers)
    st.caption(f"Model: `{settings.openai_model}`")
    st.caption("Supported: " + ", ".join(sorted(SUPPORTED_EXTENSIONS)))

    try:
        validate(settings)
        st.success("Configuration looks good")
        configured = True
    except ConfigError as exc:
        st.error(str(exc))
        configured = False

source = st.radio(
    "Documents to process",
    ["Upload files", f"Use the data folder ({settings.data_dir.name}/)"],
    horizontal=True,
)

paths: list[Path] = []
output_dir = settings.output_dir

if source == "Upload files":
    uploaded = st.file_uploader(
        "Complaint documents",
        type=[ext.lstrip(".") for ext in sorted(SUPPORTED_EXTENSIONS)],
        accept_multiple_files=True,
    )
    if uploaded:
        # Uploads live only in memory, so stage them where the loaders can read
        # them by path, exactly as the command line does.
        staging = Path(tempfile.mkdtemp(prefix="complaints_"))
        for item in uploaded:
            target = staging / item.name
            target.write_bytes(item.getbuffer())
            paths.append(target)
        output_dir = staging / "output"
else:
    if settings.data_dir.is_dir():
        paths = sorted(
            p for p in settings.data_dir.iterdir()
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
        )
        st.caption(f"{len(paths)} document(s) found in {settings.data_dir}")
    else:
        st.warning(f"No data folder at {settings.data_dir}")

if st.button("Process documents", type="primary", disabled=not (paths and configured)):
    st.session_state["results"] = run_batch(paths, workers, output_dir)
    st.session_state["output_dir"] = output_dir

results: list[ProcessingResult] = st.session_state.get("results", [])

if results:
    st.divider()
    counts = {"success": 0, "partial": 0, "failed": 0}
    for result in results:
        counts[result.status] += 1

    total, ok, partial, failed = st.columns(4)
    total.metric("Documents", len(results))
    ok.metric("Success", counts["success"])
    partial.metric("Partial", counts["partial"])
    failed.metric("Failed", counts["failed"])

    frame = pd.DataFrame([r.to_report_row() for r in results], columns=REPORT_COLUMNS)
    st.subheader("Consolidated report")
    st.dataframe(frame, width="stretch", hide_index=True)
    st.caption(f"Written to {st.session_state['output_dir']}")

    st.subheader("Per document")
    for result in results:
        icon = STATUS_ICON[result.status]
        with st.expander(f"{icon}  {result.filename}  ({result.status})"):
            show_result(result)
