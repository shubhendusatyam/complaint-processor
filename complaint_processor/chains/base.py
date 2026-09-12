"""Shared pieces for the three chains: the model factory and retry policy.

Every chain builds on the same LLM instance and the same failure handling, so
that behaviour is consistent and there is one place to change the model.
"""

from __future__ import annotations

from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI

from ..config import Settings, settings

# Guard against a pathological input blowing the context window. Complaint
# documents are short; anything past this is almost certainly a bad extraction
# from a malformed file rather than genuine case detail.
MAX_DOCUMENT_CHARS = 24_000

# Transient API failures and the rare schema violation are both worth one or
# two more attempts before the document is recorded as failed.
RETRY_ATTEMPTS = 3


class ChainError(RuntimeError):
    """An AI task failed for one document."""


def build_llm(config: Settings | None = None, temperature: float | None = None) -> ChatOpenAI:
    """Construct the chat model.

    Temperature is overridable so the email chain can be given a little warmth
    without loosening extraction, which must stay deterministic.
    """
    config = config or settings
    return ChatOpenAI(
        model=config.openai_model,
        temperature=config.openai_temperature if temperature is None else temperature,
        api_key=config.openai_api_key,
        timeout=60,
        max_retries=0,  # retries are handled by with_retry below, not silently here
    )


def with_standard_retry(chain: Runnable) -> Runnable:
    return chain.with_retry(
        stop_after_attempt=RETRY_ATTEMPTS,
        wait_exponential_jitter=True,
    )


def truncate(text: str, limit: int = MAX_DOCUMENT_CHARS) -> str:
    """Trim over-long input, marking the cut so it is visible in the prompt."""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[document truncated]"


def format_case_data(extraction) -> str:
    """Render an extraction as a readable block for the downstream prompts.

    The email and summary tasks consume the validated extraction rather than
    the raw document, so this is the only view of the case they get. Absent
    fields are labelled explicitly, so the model is told what it does not know
    instead of being left to guess.
    """
    def show(value: object) -> str:
        return "not recorded" if value is None else str(value)

    return "\n".join(
        [
            f"Customer name: {show(extraction.customer_name)}",
            f"Email: {show(extraction.email)}",
            f"Phone: {show(extraction.phone_number)}",
            f"Complaint category: {extraction.complaint_category.value}",
            f"Is a complaint: {extraction.is_complaint}",
            f"Issue description: {extraction.issue_description}",
            f"Resolution already provided: {show(extraction.resolution_provided)}",
            f"Escalation required: {extraction.escalation_required}",
            f"Supporting evidence supplied: {extraction.supporting_document_available}",
            f"Case status: {extraction.case_status.value}",
        ]
    )
