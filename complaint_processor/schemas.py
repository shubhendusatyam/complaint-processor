"""Structured output schemas for the three AI tasks.

These models are the contract between the LLM and the rest of the system. The
field descriptions are not documentation: they are sent to the model as part of
the JSON schema and are the main lever for extraction quality. Edit them with
that in mind.

The spec requires that structured extraction pass through a schema rather than
saving the raw LLM response, so nothing downstream ever sees unvalidated text.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .ingestion.base import SourceDocument

# Values a model returns when it means "absent". Mapping them to None keeps the
# report free of strings like "N/A" masquerading as data.
_NULL_TOKENS = frozenset(
    {
        "",
        "-",
        "--",
        "n/a",
        "na",
        "none",
        "null",
        "nil",
        "not provided",
        "not available",
        "not specified",
        "not mentioned",
        "unknown",
        "unspecified",
    }
)


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.lower() in _NULL_TOKENS:
            return None
        return stripped
    return value


class ComplaintCategory(str, Enum):
    """Fixed vocabulary, so the report can be grouped and counted reliably."""

    PRODUCT_DEFECT = "Product Defect"
    SERVICE_QUALITY = "Service Quality"
    BILLING = "Billing"
    DELIVERY = "Delivery"
    INSTALLATION = "Installation"
    WARRANTY = "Warranty"
    TECHNICAL_SUPPORT = "Technical Support"
    STAFF_CONDUCT = "Staff Conduct"
    REFUND = "Refund"
    GENERAL_ENQUIRY = "General Enquiry"
    OTHER = "Other"


class CaseStatus(str, Enum):
    OPEN = "Open"
    IN_PROGRESS = "In Progress"
    PENDING_CUSTOMER = "Pending Customer"
    ESCALATED = "Escalated"
    RESOLVED = "Resolved"
    CLOSED = "Closed"


class ComplaintExtraction(BaseModel):
    """The ten fields the spec requires, extracted from one document."""

    customer_name: Optional[str] = Field(
        default=None,
        description=(
            "Full name of the customer who raised the case. Return null if the "
            "document does not state a name. Never infer a name from an email address."
        ),
    )
    email: Optional[str] = Field(
        default=None,
        description=(
            "Customer email address exactly as written in the document. Return "
            "null if absent. Do not construct or guess an address."
        ),
    )
    phone_number: Optional[str] = Field(
        default=None,
        description=(
            "Customer contact phone number exactly as written, keeping any country "
            "code. Return null if absent."
        ),
    )
    complaint_category: ComplaintCategory = Field(
        description=(
            "The single category that best fits the main issue. Use General Enquiry "
            "when the document is a question rather than a complaint, and Other only "
            "when no other category applies."
        ),
    )
    issue_description: str = Field(
        description=(
            "Two or three sentences describing the problem the customer reported, "
            "in your own words, using only facts stated in the document."
        ),
    )
    resolution_provided: Optional[str] = Field(
        default=None,
        description=(
            "What the company has actually done so far to resolve the case. Return "
            "null if no action has been taken or none is described. Do not record "
            "planned or promised actions as completed."
        ),
    )
    is_complaint: bool = Field(
        description=(
            "True if the document expresses dissatisfaction or reports a problem. "
            "False if it is purely an enquiry, a request for information, or "
            "feedback with no problem reported."
        ),
    )
    escalation_required: bool = Field(
        description=(
            "True if the document states the case was escalated, requests a "
            "supervisor or manager, threatens legal or regulatory action, reports a "
            "safety risk, or shows the issue is unresolved beyond its promised "
            "timeframe. False otherwise."
        ),
    )
    supporting_document_available: bool = Field(
        description=(
            "True if the document mentions an attachment, invoice, receipt, photo, "
            "warranty card, screenshot, or other supporting evidence. False otherwise."
        ),
    )
    case_status: CaseStatus = Field(
        description=(
            "Current state of the case based only on what the document says. Use "
            "Resolved only when the document confirms the issue was fixed and the "
            "customer was informed. Use Escalated whenever escalation_required is "
            "true and the case is not yet resolved, so that the two fields agree."
        ),
    )

    @field_validator(
        "customer_name",
        "email",
        "phone_number",
        "resolution_provided",
        mode="before",
    )
    @classmethod
    def _normalize_optional_text(cls, value: Any) -> Any:
        return _blank_to_none(value)

    @field_validator("email")
    @classmethod
    def _reject_non_addresses(cls, value: Optional[str]) -> Optional[str]:
        """Drop anything that is clearly not an address rather than reporting it.

        A hallucinated placeholder in the email column is worse than a blank one.
        """
        if value is None:
            return None
        if "@" not in value or "." not in value.rsplit("@", 1)[-1]:
            return None
        return value


class CustomerEmail(BaseModel):
    """Customer-facing response drafted from the extraction."""

    subject: str = Field(
        description="Email subject line, under 80 characters, referencing the issue.",
    )
    body: str = Field(
        description=(
            "The full email body, professional and empathetic. Greet the customer "
            "by name when one is known and use Dear Customer otherwise. Summarize "
            "the issue, state the resolution or current status, and close politely. "
            "Include only facts present in the extracted case data: invent no ticket "
            "numbers, dates, refund amounts, or commitments."
        ),
    )

    def render(self) -> str:
        """Plain-text form written to output/customer_emails/."""
        return f"Subject: {self.subject}\n\n{self.body}\n"


class CaseSummary(BaseModel):
    """Internal summary for management review."""

    case_overview: str = Field(
        description="One or two sentences identifying the customer and the case.",
    )
    key_issue: str = Field(
        description="The single core problem, stated in one sentence.",
    )
    action_taken: str = Field(
        description=(
            "What has already been done. State that no action is recorded if the "
            "document describes none."
        ),
    )
    current_status: str = Field(
        description="Where the case stands now, in one sentence.",
    )
    recommended_next_action: str = Field(
        description=(
            "The single next step the team should take, phrased as an instruction."
        ),
    )

    def render(self) -> str:
        """Markdown form written to output/case_summaries/."""
        return (
            f"## Case Overview\n{self.case_overview}\n\n"
            f"## Key Issue\n{self.key_issue}\n\n"
            f"## Action Taken\n{self.action_taken}\n\n"
            f"## Current Status\n{self.current_status}\n\n"
            f"## Recommended Next Action\n{self.recommended_next_action}\n"
        )


class ProcessingResult(BaseModel):
    """Everything produced for one document, successful or not.

    A failed document still becomes a ProcessingResult so that it appears in the
    final report rather than vanishing from it.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    filename: str
    file_type: str
    extraction: Optional[ComplaintExtraction] = None
    customer_email: Optional[CustomerEmail] = None
    case_summary: Optional[CaseSummary] = None
    error: Optional[str] = None

    @property
    def succeeded(self) -> bool:
        return self.error is None and self.extraction is not None

    @property
    def status(self) -> str:
        return "success" if self.succeeded else "failed"

    @classmethod
    def failure(cls, filename: str, file_type: str, error: str) -> ProcessingResult:
        return cls(filename=filename, file_type=file_type, error=error)

    @classmethod
    def from_document(cls, document: SourceDocument, **fields: Any) -> ProcessingResult:
        return cls(filename=document.filename, file_type=document.file_type, **fields)

    def to_report_row(self) -> dict[str, Any]:
        """One row of final_report.csv.

        Column order is defined here so the report stays stable as the code
        around it changes.
        """
        got = self.extraction
        return {
            "filename": self.filename,
            "file_type": self.file_type,
            "processing_status": self.status,
            "customer_name": got.customer_name if got else None,
            "email": got.email if got else None,
            "phone_number": got.phone_number if got else None,
            "complaint_category": got.complaint_category.value if got else None,
            "issue_description": got.issue_description if got else None,
            "resolution_provided": got.resolution_provided if got else None,
            "is_complaint": got.is_complaint if got else None,
            "escalation_required": got.escalation_required if got else None,
            "supporting_document_available": (
                got.supporting_document_available if got else None
            ),
            "case_status": got.case_status.value if got else None,
            "customer_email_generated": self.customer_email is not None,
            "case_summary_generated": self.case_summary is not None,
            "error": self.error,
        }


REPORT_COLUMNS: list[str] = list(
    ProcessingResult(filename="", file_type="").to_report_row().keys()
)
