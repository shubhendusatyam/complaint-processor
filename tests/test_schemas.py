"""Phase 3: structured output schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from complaint_processor.schemas import (
    REPORT_COLUMNS,
    CaseStatus,
    CaseSummary,
    ComplaintCategory,
    ComplaintExtraction,
    CustomerEmail,
    ProcessingResult,
)

VALID = {
    "customer_name": "Anita Deshpande",
    "email": "anita.deshpande@example.com",
    "phone_number": "+91 98200 11223",
    "complaint_category": "Product Defect",
    "issue_description": "The purifier stopped dispensing water after four days.",
    "resolution_provided": "Replacement unit shipped and installed.",
    "is_complaint": True,
    "escalation_required": False,
    "supporting_document_available": True,
    "case_status": "Resolved",
}

# The ten fields the spec names, by their schema names.
REQUIRED_SPEC_FIELDS = {
    "customer_name",
    "email",
    "phone_number",
    "complaint_category",
    "issue_description",
    "resolution_provided",
    "is_complaint",
    "escalation_required",
    "supporting_document_available",
    "case_status",
}


class TestExtractionContract:
    def test_carries_every_field_the_spec_requires(self):
        assert REQUIRED_SPEC_FIELDS <= set(ComplaintExtraction.model_fields)

    def test_parses_a_complete_record(self):
        got = ComplaintExtraction(**VALID)
        assert got.customer_name == "Anita Deshpande"
        assert got.complaint_category is ComplaintCategory.PRODUCT_DEFECT
        assert got.case_status is CaseStatus.RESOLVED
        assert got.is_complaint is True

    def test_rejects_a_category_outside_the_vocabulary(self):
        with pytest.raises(ValidationError):
            ComplaintExtraction(**{**VALID, "complaint_category": "Spaceship Defect"})

    def test_requires_the_non_optional_fields(self):
        with pytest.raises(ValidationError):
            ComplaintExtraction(customer_name="Anita Deshpande")


class TestNullNormalization:
    @pytest.mark.parametrize(
        "placeholder", ["", "  ", "N/A", "n/a", "None", "not provided", "Unknown", "-"]
    )
    def test_placeholder_contact_values_become_none(self, placeholder):
        got = ComplaintExtraction(
            **{**VALID, "customer_name": placeholder, "phone_number": placeholder}
        )
        assert got.customer_name is None
        assert got.phone_number is None

    def test_surrounding_whitespace_is_stripped(self):
        got = ComplaintExtraction(**{**VALID, "customer_name": "  Ravi Menon  "})
        assert got.customer_name == "Ravi Menon"

    @pytest.mark.parametrize("bad", ["customer at example dot com", "anita@localhost", "x"])
    def test_values_that_are_not_addresses_become_none(self, bad):
        """A hallucinated placeholder in the email column is worse than a blank."""
        assert ComplaintExtraction(**{**VALID, "email": bad}).email is None

    def test_a_real_address_survives(self):
        assert ComplaintExtraction(**VALID).email == "anita.deshpande@example.com"

    def test_missing_resolution_becomes_none(self):
        got = ComplaintExtraction(**{**VALID, "resolution_provided": "not available"})
        assert got.resolution_provided is None


class TestRendering:
    def test_email_renders_with_subject_header(self):
        rendered = CustomerEmail(subject="Your purifier case", body="Dear Anita,").render()
        assert rendered.startswith("Subject: Your purifier case")
        assert "Dear Anita," in rendered

    def test_summary_renders_all_five_sections(self):
        summary = CaseSummary(
            case_overview="Overview text",
            key_issue="Key issue text",
            action_taken="Action text",
            current_status="Status text",
            recommended_next_action="Next action text",
        )
        rendered = summary.render()
        for heading in (
            "## Case Overview",
            "## Key Issue",
            "## Action Taken",
            "## Current Status",
            "## Recommended Next Action",
        ):
            assert heading in rendered


class TestProcessingResult:
    def _summary(self):
        return CaseSummary(
            case_overview="o",
            key_issue="k",
            action_taken="a",
            current_status="c",
            recommended_next_action="n",
        )

    def test_success_row_carries_the_extracted_values(self):
        result = ProcessingResult(
            filename="complaint_001.txt",
            file_type="txt",
            extraction=ComplaintExtraction(**VALID),
            customer_email=CustomerEmail(subject="s", body="b"),
            case_summary=self._summary(),
        )
        row = result.to_report_row()
        assert result.succeeded is True
        assert row["processing_status"] == "success"
        assert row["complaint_category"] == "Product Defect"
        assert row["case_status"] == "Resolved"
        assert row["customer_email_generated"] is True
        assert row["case_summary_generated"] is True
        assert row["error"] is None

    def test_missing_followup_is_reported_as_partial(self):
        """Structured data is sound but one task is missing: re-run that task."""
        result = ProcessingResult(
            filename="complaint_001.txt",
            file_type="txt",
            extraction=ComplaintExtraction(**VALID),
            customer_email=CustomerEmail(subject="s", body="b"),
        )
        assert result.succeeded is True
        assert result.status == "partial"

    def test_failed_document_still_produces_a_row(self):
        """A failure must appear in the report, not vanish from it."""
        result = ProcessingResult.failure("broken.pdf", "pdf", "scanned image, needs OCR")
        row = result.to_report_row()
        assert result.succeeded is False
        assert row["processing_status"] == "failed"
        assert row["error"] == "scanned image, needs OCR"
        assert row["customer_name"] is None

    def test_rows_match_the_declared_column_order(self):
        result = ProcessingResult.failure("x.txt", "txt", "boom")
        assert list(result.to_report_row()) == REPORT_COLUMNS

    def test_extraction_alone_is_usable_but_incomplete(self):
        result = ProcessingResult(
            filename="a.txt", file_type="txt", extraction=ComplaintExtraction(**VALID)
        )
        assert result.succeeded is True
        assert result.status == "partial"
