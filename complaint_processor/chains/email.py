"""Task 2: extracted case data to a customer response email.

Consumes the validated extraction rather than the document, so the email can
only contain facts that survived schema validation. The largest risk here is a
warm, fluent message that quietly promises a refund or a date nobody agreed to.
"""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable

from ..logging_setup import get_logger
from ..schemas import ComplaintExtraction, CustomerEmail
from .base import ChainError, build_llm, format_case_data, with_standard_retry

logger = get_logger(__name__)

# A little warmth reads better than a flat template, without loosening facts.
EMAIL_TEMPERATURE = 0.3

SYSTEM_PROMPT = """\
You write replies to customers on behalf of a company support team.

What the reply must do:
- Open with the customer's name when one is recorded, and "Dear Customer" when
  it is not.
- Acknowledge the problem and show you understand it.
- State what has been done, or where the case stands if nothing has been done.
- Close politely and sign off as "Customer Support Team".

What you must never do:
- Invent a ticket or reference number, a date, a deadline, a refund amount,
  compensation, or a named employee.
- Promise a resolution, a callback, or a timeframe that the case data does not
  already record.
- Describe a promised or planned action as though it has been completed.
- Mention internal fields, flags, or the fact that data was extracted.

Where the case data says a field is not recorded, write around it. Saying less
is always better than inventing something. If no resolution is recorded, say
the case is being reviewed and that the team will follow up, with no date.

Where escalation is required, acknowledge the delay or seriousness directly and
say the case has been escalated for priority review.\
"""

HUMAN_PROMPT = """\
Case data extracted from the customer's document:

{case_data}

Write the reply to this customer."""


def build_email_chain(llm=None, retry: bool = True) -> Runnable:
    prompt = ChatPromptTemplate.from_messages(
        [("system", SYSTEM_PROMPT), ("human", HUMAN_PROMPT)]
    )
    model = llm if llm is not None else build_llm(temperature=EMAIL_TEMPERATURE)
    chain = prompt | model.with_structured_output(CustomerEmail, strict=True)
    return with_standard_retry(chain) if retry else chain


def generate_email(
    extraction: ComplaintExtraction,
    filename: str,
    chain: Runnable | None = None,
) -> CustomerEmail:
    """Draft the customer reply for one case."""
    chain = chain if chain is not None else build_email_chain()
    try:
        result = chain.invoke({"case_data": format_case_data(extraction)})
    except Exception as exc:
        raise ChainError(f"Email generation failed for {filename}: {exc}") from exc

    logger.info("Drafted customer email for %s", filename)
    return result
