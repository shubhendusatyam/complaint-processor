"""Phase 6: workflow orchestration and batch processing.

Uses stub chains rather than the API, so failure isolation and ordering can be
checked deterministically and for free.
"""

from __future__ import annotations

from langchain_core.runnables import RunnableLambda, RunnableParallel

from complaint_processor.orchestrator import (
    Workflow,
    process_batch,
    process_document,
    process_file,
)
from complaint_processor.ingestion.base import SourceDocument
from complaint_processor.schemas import (
    CaseStatus,
    CaseSummary,
    ComplaintCategory,
    ComplaintExtraction,
    CustomerEmail,
)

from .pdf_fixture import write_pdf

EXTRACTED = ComplaintExtraction(
    customer_name="Anita Deshpande",
    email="anita.deshpande@example.com",
    complaint_category=ComplaintCategory.PRODUCT_DEFECT,
    issue_description="The purifier stopped dispensing water.",
    resolution_provided="Replacement shipped.",
    is_complaint=True,
    escalation_required=False,
    supporting_document_available=True,
    case_status=CaseStatus.RESOLVED,
)
EMAIL = CustomerEmail(subject="Your case", body="Dear Anita,")
SUMMARY = CaseSummary(
    case_overview="o",
    key_issue="k",
    action_taken="a",
    current_status="c",
    recommended_next_action="n",
)


def _boom(message):
    def raise_it(_):
        raise RuntimeError(message)

    return RunnableLambda(raise_it)


def working_workflow() -> Workflow:
    return Workflow(
        extraction=RunnableLambda(lambda _: EXTRACTED),
        followups=RunnableParallel(
            customer_email=RunnableLambda(lambda _: EMAIL),
            case_summary=RunnableLambda(lambda _: SUMMARY),
        ),
    )


def document(name="complaint_001.txt") -> SourceDocument:
    return SourceDocument(
        filename=name, path=f"C:/fake/{name}", file_type="txt", text="Complaint: no water."
    )


class TestProcessDocument:
    def test_successful_document_carries_all_three_outputs(self):
        result = process_document(document(), working_workflow())
        assert result.status == "success"
        assert result.extraction.customer_name == "Anita Deshpande"
        assert result.customer_email.subject == "Your case"
        assert result.case_summary.key_issue == "k"
        assert result.error is None

    def test_extraction_failure_is_recorded_not_raised(self):
        workflow = Workflow(
            extraction=_boom("model unavailable"), followups=working_workflow().followups
        )
        result = process_document(document(), workflow)
        assert result.status == "failed"
        assert "model unavailable" in result.error
        assert result.extraction is None

    def test_followup_failure_keeps_the_extraction(self):
        """Structured data survives so only the failed task needs re-running."""
        workflow = Workflow(
            extraction=RunnableLambda(lambda _: EXTRACTED),
            followups=_boom("rate limited"),
        )
        result = process_document(document(), workflow)
        assert result.status == "partial"
        assert result.extraction is not None
        assert result.customer_email is None
        assert "rate limited" in result.error


class TestProcessFile:
    def test_unreadable_file_becomes_a_failed_result(self, tmp_path):
        path = tmp_path / "broken.pdf"
        path.write_bytes(b"not a pdf")
        result = process_file(path, working_workflow())
        assert result.status == "failed"
        assert result.filename == "broken.pdf"
        assert result.file_type == "pdf"

    def test_unsupported_file_becomes_a_failed_result(self, tmp_path):
        path = tmp_path / "notes.md"
        path.write_text("nope", encoding="utf-8")
        result = process_file(path, working_workflow())
        assert result.status == "failed"
        assert "No loader" in result.error


class TestProcessBatch:
    def _data_dir(self, tmp_path):
        (tmp_path / "complaint_001.txt").write_text("a complaint", encoding="utf-8")
        write_pdf(tmp_path / "complaint_002.pdf", "another complaint")
        (tmp_path / "complaint_003.txt").write_text("a third", encoding="utf-8")
        return tmp_path

    def test_processes_every_document(self, tmp_path):
        paths = sorted(self._data_dir(tmp_path).iterdir())
        results = process_batch(paths=paths, workflow=working_workflow(), max_workers=3)
        assert len(results) == 3
        assert all(r.status == "success" for r in results)

    def test_results_keep_input_order_despite_concurrency(self, tmp_path):
        """The report must be reproducible, not ordered by whichever finished first."""
        paths = sorted(self._data_dir(tmp_path).iterdir())
        results = process_batch(paths=paths, workflow=working_workflow(), max_workers=3)
        assert [r.filename for r in results] == [p.name for p in paths]

    def test_one_bad_document_does_not_stop_the_batch(self, tmp_path):
        data = self._data_dir(tmp_path)
        (data / "broken.pdf").write_bytes(b"not a pdf")
        paths = sorted(data.iterdir())

        results = process_batch(paths=paths, workflow=working_workflow(), max_workers=2)

        assert len(results) == 4
        statuses = {r.filename: r.status for r in results}
        assert statuses["broken.pdf"] == "failed"
        assert statuses["complaint_001.txt"] == "success"

    def test_empty_input_returns_empty_list(self, tmp_path):
        assert process_batch(paths=[], workflow=working_workflow()) == []

    def test_progress_callback_fires_once_per_document(self, tmp_path):
        paths = sorted(self._data_dir(tmp_path).iterdir())
        seen = []
        process_batch(
            paths=paths,
            workflow=working_workflow(),
            max_workers=2,
            on_progress=lambda done, total, result: seen.append((done, total)),
        )
        assert [d for d, _ in seen] == [1, 2, 3]
        assert all(total == 3 for _, total in seen)
