"""Phase 4: the extraction chain.

These tests use a stub model rather than the API, so the suite costs nothing
and runs offline. Live behaviour is checked separately against real documents.
"""

from __future__ import annotations

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from complaint_processor.chains.base import (
    MAX_DOCUMENT_CHARS,
    ChainError,
    truncate,
)
from complaint_processor.chains.extraction import (
    HUMAN_PROMPT,
    SYSTEM_PROMPT,
    build_extraction_chain,
    extract,
)
from complaint_processor.ingestion.base import SourceDocument
from complaint_processor.schemas import CaseStatus, ComplaintCategory, ComplaintExtraction

EXTRACTED = ComplaintExtraction(
    customer_name="Anita Deshpande",
    email="anita.deshpande@example.com",
    phone_number=None,
    complaint_category=ComplaintCategory.PRODUCT_DEFECT,
    issue_description="The purifier stopped dispensing water.",
    resolution_provided="Replacement unit shipped.",
    is_complaint=True,
    escalation_required=False,
    supporting_document_available=True,
    case_status=CaseStatus.RESOLVED,
)


@pytest.fixture
def document():
    return SourceDocument(
        filename="complaint_001.txt",
        path="C:/fake/complaint_001.txt",
        file_type="txt",
        text="Customer Name: Anita Deshpande\nComplaint: no water.",
    )


class StubModel(FakeMessagesListChatModel):
    """Stands in for ChatOpenAI, returning a fixed structured result."""

    def with_structured_output(self, schema, **kwargs):
        return RunnableLambda(lambda _: EXTRACTED)


class FailingModel(FakeMessagesListChatModel):
    def with_structured_output(self, schema, **kwargs):
        def boom(_):
            raise RuntimeError("upstream refused the request")

        return RunnableLambda(boom)


class TestExtract:
    def test_returns_a_validated_model(self, document):
        chain = build_extraction_chain(llm=StubModel(responses=[AIMessage(content="")]))
        got = extract(document, chain=chain)
        assert isinstance(got, ComplaintExtraction)
        assert got.customer_name == "Anita Deshpande"
        assert got.case_status is CaseStatus.RESOLVED

    def test_failure_is_wrapped_with_the_filename(self, document):
        """The orchestrator needs to know which document failed."""
        chain = build_extraction_chain(
            llm=FailingModel(responses=[AIMessage(content="")]), retry=False
        )
        with pytest.raises(ChainError, match="complaint_001.txt"):
            extract(document, chain=chain)


class TestPromptContract:
    """The prompt is the main lever on accuracy, so its rules are pinned here."""

    def test_forbids_inventing_absent_fields(self):
        assert "return null" in SYSTEM_PROMPT.lower()
        assert "never infer a customer name" in SYSTEM_PROMPT.lower()

    def test_separates_promised_actions_from_completed_ones(self):
        assert "promise" in SYSTEM_PROMPT.lower()

    def test_human_prompt_carries_the_document_and_filename(self):
        assert "{document_text}" in HUMAN_PROMPT
        assert "{filename}" in HUMAN_PROMPT


class TestTruncation:
    def test_short_text_is_untouched(self):
        assert truncate("short") == "short"

    def test_long_text_is_cut_and_marked(self):
        got = truncate("x" * (MAX_DOCUMENT_CHARS + 500))
        assert got.endswith("[document truncated]")
        assert len(got) < MAX_DOCUMENT_CHARS + 100


class TestTruncationIsInsideTheChain:
    """The orchestrator invokes the chain directly, bypassing extract().

    The length guard therefore has to live in the chain itself, or it is dead
    in the path that actually runs.
    """

    def test_oversized_input_is_trimmed_before_the_prompt(self):
        captured = {}

        class Recorder(FakeMessagesListChatModel):
            def with_structured_output(self, schema, **kwargs):
                def record(prompt_value):
                    captured["text"] = prompt_value.to_string()
                    return EXTRACTED

                return RunnableLambda(record)

        chain = build_extraction_chain(
            llm=Recorder(responses=[AIMessage(content="")]), retry=False
        )
        chain.invoke(
            {"filename": "huge.txt", "document_text": "x" * (MAX_DOCUMENT_CHARS + 5_000)}
        )

        assert "[document truncated]" in captured["text"]
        assert len(captured["text"]) < MAX_DOCUMENT_CHARS + 2_000
