"""The three LLM tasks: extraction, customer email, case summary.

Each chain owns its own prompt and structured-output binding. Shared model
construction, retry policy and input formatting live in base.py.
"""

from .base import (
    MAX_DOCUMENT_CHARS,
    ChainError,
    build_llm,
    format_case_data,
    truncate,
)
from .email import build_email_chain, generate_email
from .extraction import build_extraction_chain, extract
from .summary import build_summary_chain, generate_summary

__all__ = [
    "MAX_DOCUMENT_CHARS",
    "ChainError",
    "build_llm",
    "format_case_data",
    "truncate",
    "build_email_chain",
    "generate_email",
    "build_extraction_chain",
    "extract",
    "build_summary_chain",
    "generate_summary",
]
