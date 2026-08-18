"""Main agent entry point: retrieve-then-generate, no LLM tool-calling.

1. RETRIEVE (pure Python, agent/retriever.py): keyword/intent detection picks
   which tool functions to run, and runs them directly to gather chunks.
2. GENERATE (one LLM call): the user's question plus the retrieved evidence,
   formatted as context, is sent to Groq alongside the answer-contract system
   prompt. The model only has to write the answer -- no tools parameter, so
   no dependency on a model's (often unreliable) tool-calling support.

Every failure mode in this module degrades to a plain-text fallback answer
rather than raising -- the API layer has its own catch-all too, but the
agent should never depend on that outer net to avoid a raw 500.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import time
from typing import Any

from groq import Groq, RateLimitError

from agent.retriever import retrieve
from agent.system_prompt import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

MODEL = os.environ.get("GROQ_MODEL", "qwen/qwen3.6-27b")
MAX_TOKENS = 2048
CLIENT_TIMEOUT_SECONDS = 60.0
RATE_LIMIT_RETRY_DELAY_SECONDS = 10

FALLBACK_MESSAGE = "I wasn't able to process that question. Please try rephrasing or try again in a moment."


def _format_chunk(chunk: dict[str, Any]) -> str:
    return (
        f"[{chunk['jurisdiction']}] {chunk['instrument']} {chunk['section_ref']} "
        f"-- {chunk['section_title']}\n"
        f"{chunk['parent_context']}\n"
        f"{chunk['text']}\n"
        f"Source: {chunk['url']} ({chunk['source_type']})"
    )


def _format_deadline(deadline: dict[str, Any]) -> str:
    return (
        f"[{deadline['jurisdiction']}] {deadline['instrument']} {deadline['section_ref']} "
        f"-- {deadline['topic']}\n"
        f"Deadline: {deadline['deadline_date']} -- applies to: {deadline['applies_to']}\n"
        f"{deadline['description']}"
    )


def _format_context(evidence: dict[str, Any]) -> str:
    chunks = evidence["chunks"]
    deadlines = evidence["deadlines"]

    parts = ["## Retrieved context"]

    if chunks:
        parts.append("### Corpus chunks\n\n" + "\n\n".join(_format_chunk(c) for c in chunks))
    else:
        parts.append("### Corpus chunks\n\n(No matching chunks -- the verified corpus has no coverage for this query.)")

    if deadlines:
        parts.append("### Curated deadlines\n\n" + "\n\n".join(_format_deadline(d) for d in deadlines))

    return "\n\n".join(parts)


def _complete_with_retry(client: Groq, messages: list[dict[str, Any]]):
    """One completion attempt, with a single retry after a fixed backoff on 429s.

    Groq's own SDK already retries some errors internally (max_retries=2 by
    default); this is a second, explicit layer on top because we saw 429s
    survive that internal retry under back-to-back requests in testing.
    """
    try:
        return client.chat.completions.create(model=MODEL, messages=messages, max_tokens=MAX_TOKENS)
    except RateLimitError:
        logger.warning("Groq rate limit hit; waiting %ss and retrying once", RATE_LIMIT_RETRY_DELAY_SECONDS)
        time.sleep(RATE_LIMIT_RETRY_DELAY_SECONDS)
        return client.chat.completions.create(model=MODEL, messages=messages, max_tokens=MAX_TOKENS)


def run_agent(
    user_message: str,
    conversation_history: list[dict[str, str]] | None = None,
    client: Groq | None = None,
) -> dict[str, Any]:
    """Run the retrieve-then-generate flow for one user message.

    Returns {"answer": str, "chunks": list[dict]} -- the chunks are the
    corpus chunks the retrieve step gathered for this turn, exposed so
    callers (e.g. the API layer) can report exactly what evidence grounded
    the answer without re-running retrieval themselves. On any Groq failure
    (rate limit surviving the retry, timeout, connection error, etc.) this
    returns a graceful fallback answer with no chunks instead of raising.
    """
    client = client or Groq(timeout=CLIENT_TIMEOUT_SECONDS)

    evidence = retrieve(user_message)
    context = _format_context(evidence)

    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(conversation_history or [])
    messages.append({"role": "user", "content": f"{context}\n\n## User question\n\n{user_message}"})

    try:
        response = _complete_with_retry(client, messages)
    except Exception:
        logger.exception("Groq completion failed for question %r", user_message)
        return {"answer": FALLBACK_MESSAGE, "chunks": []}

    answer = response.choices[0].message.content or FALLBACK_MESSAGE
    answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL).strip()
    if evidence.get("typo_note"):
        answer = f"{evidence['typo_note']}\n\n{answer}"

    return {"answer": answer, "chunks": evidence["chunks"]}


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    query = " ".join(sys.argv[1:]) or "What are the EU recycled content thresholds?"
    print(f"User: {query}\n")
    print(run_agent(query)["answer"])
