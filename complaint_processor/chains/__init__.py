"""The three LLM tasks: extraction, customer email, case summary.

Each chain owns its own prompt and structured-output binding. Shared model
construction and retry policy live in base.py.
"""

from .base import ChainError, MAX_DOCUMENT_CHARS, build_llm, truncate
from .extraction import build_extraction_chain, extract

__all__ = [
    "ChainError",
    "MAX_DOCUMENT_CHARS",
    "build_llm",
    "truncate",
    "build_extraction_chain",
    "extract",
]
