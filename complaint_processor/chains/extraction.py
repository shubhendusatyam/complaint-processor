"""Task 1: document text to structured case data.

The output of this chain feeds both other tasks, so accuracy here matters more
than anywhere else in the system. The prompt is deliberately restrictive: a
missing field is a correct answer, an invented one is not.
"""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable

from ..ingestion.base import SourceDocument
from ..logging_setup import get_logger
from ..schemas import ComplaintExtraction
from .base import ChainError, build_llm, truncate, with_standard_retry

logger = get_logger(__name__)

SYSTEM_PROMPT = """\
You extract case details from customer complaint documents for a support team.

Rules, in order of importance:
1. Use only information explicitly present in the document.
2. If a field is not stated, return null. A missing field is a correct answer.
3. Never infer a customer name from an email address or signature block.
4. Copy contact details exactly as written, including country codes.
5. Record only what has already happened as the resolution. A promise, a plan,
   or a scheduled visit is not a resolution that has been provided.
6. Base every true/false answer on evidence in the text, never on assumption.

Accuracy matters more than completeness. Do not fill a field to look thorough.\
"""

HUMAN_PROMPT = """\
Source file: {filename}

--- BEGIN DOCUMENT ---
{document_text}
--- END DOCUMENT ---

Extract the case details."""


def build_extraction_chain(llm=None, retry: bool = True) -> Runnable:
    """Compose the prompt, the model and the schema into one runnable.

    Pass retry=False to skip the backoff policy, which tests do so the suite
    does not spend seconds waiting between deliberate failures.
    """
    prompt = ChatPromptTemplate.from_messages(
        [("system", SYSTEM_PROMPT), ("human", HUMAN_PROMPT)]
    )
    model = llm if llm is not None else build_llm(temperature=0.0)
    structured = model.with_structured_output(ComplaintExtraction, strict=True)
    chain = prompt | structured
    return with_standard_retry(chain) if retry else chain


def extract(document: SourceDocument, chain: Runnable | None = None) -> ComplaintExtraction:
    """Run the extraction task for one document.

    Raises ChainError so the orchestrator can record the failure and move on
    rather than losing the whole batch.
    """
    chain = chain if chain is not None else build_extraction_chain()
    try:
        result = chain.invoke(
            {
                "filename": document.filename,
                "document_text": truncate(document.text),
            }
        )
    except Exception as exc:
        raise ChainError(f"Extraction failed for {document.filename}: {exc}") from exc

    logger.info(
        "Extracted %s: category=%s status=%s escalation=%s",
        document.filename,
        result.complaint_category.value,
        result.case_status.value,
        result.escalation_required,
    )
    return result
