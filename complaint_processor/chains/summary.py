"""Task 3: extracted case data to an internal management summary.

Written for a case manager scanning many cases, so every field is short and
the recommended action is something a person can actually do next.
"""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable

from ..logging_setup import get_logger
from ..schemas import CaseSummary, ComplaintExtraction
from .base import ChainError, build_llm, format_case_data, with_standard_retry

logger = get_logger(__name__)

SYSTEM_PROMPT = """\
You write short internal case summaries for a customer service manager who is
reviewing many cases in one sitting.

Style:
- Factual and neutral. This is not customer-facing, so no apologies and no
  reassurance.
- One or two sentences per field. Never pad.
- Use only what the case data records. Where a field is not recorded, say so
  plainly rather than guessing.

The recommended next action must be a single concrete instruction someone can
act on, such as scheduling an engineer visit or confirming closure with the
customer. When escalation is required, the next action must reflect that
priority. When the case is resolved and nothing remains, say that no further
action is needed.\
"""

HUMAN_PROMPT = """\
Case data extracted from the customer's document:

{case_data}

Write the internal case summary."""


def build_summary_chain(llm=None, retry: bool = True) -> Runnable:
    prompt = ChatPromptTemplate.from_messages(
        [("system", SYSTEM_PROMPT), ("human", HUMAN_PROMPT)]
    )
    model = llm if llm is not None else build_llm(temperature=0.0)
    chain = prompt | model.with_structured_output(CaseSummary, strict=True)
    return with_standard_retry(chain) if retry else chain


def generate_summary(
    extraction: ComplaintExtraction,
    filename: str,
    chain: Runnable | None = None,
) -> CaseSummary:
    """Write the internal summary for one case."""
    chain = chain if chain is not None else build_summary_chain()
    try:
        result = chain.invoke({"case_data": format_case_data(extraction)})
    except Exception as exc:
        raise ChainError(f"Summary generation failed for {filename}: {exc}") from exc

    logger.info("Wrote case summary for %s", filename)
    return result
