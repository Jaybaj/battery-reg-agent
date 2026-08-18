"""Main agent entry point: retrieve-then-generate, no LLM tool-calling.

1. RETRIEVE (pure Python, agent/retriever.py): keyword/intent detection picks
   which tool functions to run, and runs them directly to gather chunks.
2. GENERATE (one LLM call): the user's question plus the retrieved evidence,
   formatted as context, is sent to the model alongside the answer-contract
   system prompt. The model only has to write the answer -- no tools
   parameter, so no dependency on a model's (often unreliable) tool-calling
   support.

Generation walks a fallback chain of (provider, model) pairs -- OpenRouter's
free Nemotron tiers first, then Groq's Qwen -- trying each in order until one
succeeds.

Every failure mode in this module degrades to a plain-text fallback answer
rather than raising -- the API layer has its own catch-all too, but the
agent should never depend on that outer net to avoid a raw 500.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from typing import Any

from groq import Groq
from openai import OpenAI

from agent.retriever import retrieve
from agent.system_prompt import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://battery-reg-agent.vercel.app",
    "X-Title": "Battery Regulation Navigator",
}

# (provider, model) pairs tried in order; the first one to return a response wins.
MODEL_CHAIN = [
    ("openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free"),
    ("openrouter", "nvidia/nemotron-3-super-120b-a12b:free"),
    ("groq", os.environ.get("GROQ_MODEL", "qwen/qwen3.6-27b")),
]

MAX_TOKENS = 2048
CLIENT_TIMEOUT_SECONDS = 60.0

FALLBACK_MESSAGE = "I wasn't able to process that question. Please try rephrasing or try again in a moment."


def _build_clients() -> dict[str, Any]:
    return {
        "openrouter": OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ.get("OPENROUTER_API_KEY"),
            default_headers=OPENROUTER_HEADERS,
            timeout=CLIENT_TIMEOUT_SECONDS,
        ),
        "groq": Groq(timeout=CLIENT_TIMEOUT_SECONDS),
    }


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


def run_agent(
    user_message: str,
    conversation_history: list[dict[str, str]] | None = None,
    clients: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the retrieve-then-generate flow for one user message.

    Returns {"answer": str, "chunks": list[dict]} -- the chunks are the
    corpus chunks the retrieve step gathered for this turn, exposed so
    callers (e.g. the API layer) can report exactly what evidence grounded
    the answer without re-running retrieval themselves. Generation walks
    MODEL_CHAIN in order, trying the next (provider, model) pair on any
    failure. If every pair fails, this returns a graceful fallback answer
    with no chunks instead of raising.
    """
    clients = clients or _build_clients()

    evidence = retrieve(user_message)
    context = _format_context(evidence)

    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(conversation_history or [])
    messages.append({"role": "user", "content": f"{context}\n\n## User question\n\n{user_message}"})

    answer = None
    for provider, model in MODEL_CHAIN:
        try:
            response = clients[provider].chat.completions.create(
                model=model, messages=messages, max_tokens=MAX_TOKENS
            )
            answer = response.choices[0].message.content or FALLBACK_MESSAGE
            logger.info("Answered question %r using %s/%s", user_message, provider, model)
            break
        except Exception:
            logger.warning("Model %s/%s failed, trying next in fallback chain", provider, model, exc_info=True)

    if answer is None:
        logger.error("All models in fallback chain failed for question %r", user_message)
        return {"answer": FALLBACK_MESSAGE, "chunks": []}

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
