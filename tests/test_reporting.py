"""Phase 7: output artifacts."""

from __future__ import annotations

import json
from dataclasses import replace

import pandas as pd
import pytest

from complaint_processor.config import settings
from complaint_processor.reporting import (
    output_stem,
    write_all,
    write_case_summary,
    write_customer_email,
    write_final_report,
    write_structured_data,
)
from complaint_processor.schemas import (
    REPORT_COLUMNS,
    CaseStatus,
    CaseSummary,
    ComplaintCategory,
    ComplaintExtraction,
    CustomerEmail,
    ProcessingResult,
)

# A name and an email body that both break under the Windows default codepage.
EXTRACTED = ComplaintExtraction(
    customer_name="José Da Silva",
    email="jose.dasilva@example.com",
    phone_number="+91 98200 11223",
    complaint_category=ComplaintCategory.PRODUCT_DEFECT,
    issue_description="The unit stopped working.",
    resolution_provided=None,
    is_complaint=True,
    escalation_required=True,
    supporting_document_available=False,
    case_status=CaseStatus.ESCALATED,
)
EMAIL = CustomerEmail(subject="Your case", body="Dear José,\n\nIt didn’t start.")
SUMMARY = CaseSummary(
    case_overview="o",
    key_issue="k",
    action_taken="a",
    current_status="c",
    recommended_next_action="n",
)


def complete(name="complaint_001.txt") -> ProcessingResult:
    return ProcessingResult(
        filename=name,
        file_type="txt",
        extraction=EXTRACTED,
        customer_email=EMAIL,
        case_summary=SUMMARY,
    )


@pytest.fixture
def output_config(tmp_path):
    """Settings pointed at a throwaway output tree."""
    return replace(settings, output_dir=tmp_path / "output", data_dir=tmp_path / "data")


class TestIndividualArtifacts:
    def test_structured_data_is_json_with_provenance(self, tmp_path):
        path = write_structured_data(complete(), tmp_path, "complaint_001")
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["source_file"] == "complaint_001.txt"
        assert payload["processing_status"] == "success"
        assert payload["extraction"]["customer_name"] == "José Da Silva"
        assert payload["extraction"]["case_status"] == "Escalated"

    def test_non_ascii_survives_the_round_trip(self, tmp_path):
        """The Windows default codepage would mangle these characters."""
        path = write_customer_email(complete(), tmp_path, "complaint_001")
        body = path.read_text(encoding="utf-8")
        assert "José" in body
        assert "didn’t" in body
        assert body.startswith("Subject: Your case")

    def test_summary_is_markdown_naming_its_source(self, tmp_path):
        path = write_case_summary(complete(), tmp_path, "complaint_001")
        text = path.read_text(encoding="utf-8")
        assert path.suffix == ".md"
        assert "# Case Summary: complaint_001.txt" in text
        assert "## Recommended Next Action" in text

    def test_missing_outputs_write_no_file(self, tmp_path):
        failed = ProcessingResult.failure("broken.pdf", "pdf", "unreadable")
        assert write_structured_data(failed, tmp_path, "broken") is None
        assert write_customer_email(failed, tmp_path, "broken") is None
        assert write_case_summary(failed, tmp_path, "broken") is None
        assert list(tmp_path.iterdir()) == []


class TestFinalReport:
    def test_failed_documents_still_appear(self, tmp_path):
        """Every input file must be accounted for, not just the ones that worked."""
        results = [
            complete("complaint_001.txt"),
            ProcessingResult.failure("broken.pdf", "pdf", "scanned image, needs OCR"),
        ]
        path = write_final_report(results, tmp_path / "final_report.csv")
        frame = pd.read_csv(path)

        assert len(frame) == 2
        assert list(frame.columns) == REPORT_COLUMNS
        failed = frame[frame["filename"] == "broken.pdf"].iloc[0]
        assert failed["processing_status"] == "failed"
        assert "OCR" in failed["error"]

    def test_accented_names_read_back_correctly(self, tmp_path):
        path = write_final_report([complete()], tmp_path / "final_report.csv")
        frame = pd.read_csv(path)
        assert frame.iloc[0]["customer_name"] == "José Da Silva"


class TestStemCollisions:
    def test_same_stem_across_formats_does_not_overwrite(self):
        """complaint_001.txt and complaint_001.pdf must not share an output name."""
        first = ProcessingResult.failure("complaint_001.txt", "txt", "x")
        second = ProcessingResult.failure("complaint_001.pdf", "pdf", "x")
        taken = {output_stem(first)}
        assert output_stem(second, taken) == "complaint_001_pdf"


class TestWriteAll:
    def test_produces_every_artifact_and_counts_them(self, output_config):
        results = [
            complete("complaint_001.txt"),
            ProcessingResult.failure("broken.pdf", "pdf", "unreadable"),
        ]
        report = write_all(results, config=output_config)

        assert report["documents"] == 2
        assert report["statuses"] == {"success": 1, "failed": 1}
        assert report["files_written"] == {
            "structured_data": 1,
            "customer_emails": 1,
            "case_summaries": 1,
        }
        assert output_config.final_report_path.is_file()
        assert (output_config.structured_data_dir / "complaint_001.json").is_file()
        assert (output_config.customer_emails_dir / "complaint_001.txt").is_file()
        assert (output_config.case_summaries_dir / "complaint_001.md").is_file()

    def test_creates_the_output_tree_if_absent(self, output_config):
        assert not output_config.output_dir.exists()
        write_all([complete()], config=output_config)
        assert output_config.structured_data_dir.is_dir()
