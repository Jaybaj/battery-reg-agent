"""Main agent entry point: retrieve-then-generate, no LLM tool-calling.

1. RETRIEVE (pure Python, agent/retriever.py): keyword/intent detection picks
   which tool functions to run, and runs them directly to gather chunks.
2. GENERATE (one LLM call): the user's question plus the retrieved evidence,
   formatted as context, is sent to the model alongside the answer-contract
   system prompt. The model only has to write the answer -- no tools
   parameter, so no dependency on a model's (often unreliable) tool-calling
   support.

Generation walks a fallback chain of OpenRouter's free Nemotron models,
trying each in order until one succeeds.

Every failure mode in this module degrades to a plain-text fallback answer
rather than raising -- the API layer has its own catch-all too, but the
agent should never depend on that outer net to avoid a raw 500.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from collections.abc import Iterable, Iterator
from typing import Any

from openai import OpenAI

from agent.retriever import retrieve
from agent.system_prompt import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://battery-reg-agent.vercel.app",
    "X-Title": "Battery Regulation Navigator",
}

# OpenRouter models tried in order; the first one to return a response wins.
MODEL_CHAIN = [
    "nvidia/nemotron-3-super-120b-a12b:free",  # faster
    "nvidia/nemotron-3-ultra-550b-a55b:free",  # higher quality fallback
    "nvidia/nemotron-3.5-lightning:free",  # fastest fallback
]

MAX_TOKENS = 2048
CLIENT_TIMEOUT_SECONDS = 15.0  # per model attempt

FALLBACK_MESSAGE = "I wasn't able to process that question. Please try rephrasing or try again in a moment."


def _build_client() -> OpenAI | None:
    openrouter_api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not openrouter_api_key:
        logger.warning("OPENROUTER_API_KEY not set; no model available")
        return None
    return OpenAI(
        api_key=openrouter_api_key,
        base_url="https://openrouter.ai/api/v1",
        default_headers=OPENROUTER_HEADERS,
        timeout=CLIENT_TIMEOUT_SECONDS,
    )


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


def _build_messages(
    user_message: str,
    conversation_history: list[dict[str, str]] | None,
    evidence: dict[str, Any],
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(conversation_history or [])
    messages.append({"role": "user", "content": f"{_format_context(evidence)}\n\n## User question\n\n{user_message}"})
    return messages


def run_agent(
    user_message: str,
    conversation_history: list[dict[str, str]] | None = None,
    client: OpenAI | None = None,
) -> dict[str, Any]:
    """Run the retrieve-then-generate flow for one user message.

    Returns {"answer": str, "chunks": list[dict]} -- the chunks are the
    corpus chunks the retrieve step gathered for this turn, exposed so
    callers (e.g. the API layer) can report exactly what evidence grounded
    the answer without re-running retrieval themselves. Generation walks
    MODEL_CHAIN in order, trying the next model on any failure. If every
    model fails, this returns a graceful fallback answer
    with no chunks instead of raising.
    """
    client = client or _build_client()

    evidence = retrieve(user_message)
    messages = _build_messages(user_message, conversation_history, evidence)

    answer = None
    for model in MODEL_CHAIN if client else []:
        print(f"Trying openrouter/{model}...")
        try:
            response = client.chat.completions.create(model=model, messages=messages, max_tokens=MAX_TOKENS)
            answer = response.choices[0].message.content or FALLBACK_MESSAGE
            logger.info("Answered question %r using openrouter/%s", user_message, model)
            break
        except Exception:
            logger.warning("Model openrouter/%s failed, trying next in fallback chain", model, exc_info=True)

    if answer is None:
        logger.error("All models in fallback chain failed for question %r", user_message)
        return {"answer": FALLBACK_MESSAGE, "chunks": []}

    answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL).strip()
    if evidence.get("typo_note"):
        answer = f"{evidence['typo_note']}\n\n{answer}"

    return {"answer": answer, "chunks": evidence["chunks"]}


_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"


def _partial_tag_suffix(text: str, tag: str) -> int:
    """Length of the longest suffix of `text` that is a proper prefix of `tag`."""
    for length in range(min(len(tag) - 1, len(text)), 0, -1):
        if text.endswith(tag[:length]):
            return length
    return 0


def _strip_think_stream(tokens: Iterable[str]) -> Iterator[str]:
    """Streaming equivalent of run_agent's <think>...</think> removal + strip().

    Tags can be split across token boundaries, so text that might be the
    start of a tag is held back until the next token disambiguates it.
    Leading whitespace is dropped until the first real content, matching the
    non-streaming path's strip().
    """
    buffer = ""
    inside_think = False
    started = False

    def emit(text: str) -> Iterator[str]:
        nonlocal started
        if not started:
            text = text.lstrip()
            started = bool(text)
        if text:
            yield text

    for token in tokens:
        buffer += token
        while True:
            if inside_think:
                end = buffer.find(_THINK_CLOSE)
                if end == -1:
                    buffer = buffer[len(buffer) - _partial_tag_suffix(buffer, _THINK_CLOSE) :]
                    break
                buffer = buffer[end + len(_THINK_CLOSE) :]
                inside_think = False
            else:
                start = buffer.find(_THINK_OPEN)
                if start == -1:
                    held = _partial_tag_suffix(buffer, _THINK_OPEN)
                    yield from emit(buffer[: len(buffer) - held])
                    buffer = buffer[len(buffer) - held :]
                    break
                yield from emit(buffer[:start])
                buffer = buffer[start + len(_THINK_OPEN) :]
                inside_think = True

    if not inside_think:
        yield from emit(buffer)


def _stream_model(client: OpenAI, model: str, messages: list[dict[str, Any]]) -> Iterator[str]:
    stream = client.chat.completions.create(model=model, messages=messages, max_tokens=MAX_TOKENS, stream=True)
    for event in stream:
        # OpenRouter interleaves keep-alive/usage events that carry no choices.
        if event.choices and event.choices[0].delta.content:
            yield event.choices[0].delta.content


def stream_agent(
    user_message: str,
    conversation_history: list[dict[str, str]] | None = None,
    client: OpenAI | None = None,
) -> tuple[list[dict[str, Any]], Iterator[str]]:
    """Streaming variant of run_agent.

    Retrieval runs eagerly, so the returned chunks are available before any
    generation happens (letting the API send citations up front). The
    returned iterator yields answer text as it arrives from the model.

    Fallback works as in run_agent, but only until a model has produced
    output: once text has reached the client it can't be retracted, so a
    mid-stream failure ends the answer with a short note instead of
    restarting on the next model. If no model produces anything, the
    iterator yields FALLBACK_MESSAGE.
    """
    client = client or _build_client()

    evidence = retrieve(user_message)
    messages = _build_messages(user_message, conversation_history, evidence)

    def tokens() -> Iterator[str]:
        if evidence.get("typo_note"):
            yield f"{evidence['typo_note']}\n\n"

        for model in MODEL_CHAIN if client else []:
            print(f"Trying openrouter/{model}...")
            produced_output = False
            try:
                for text in _strip_think_stream(_stream_model(client, model, messages)):
                    produced_output = True
                    yield text
                if produced_output:
                    logger.info("Streamed answer to %r using openrouter/%s", user_message, model)
                    return
                logger.warning("Model openrouter/%s returned no content, trying next in fallback chain", model)
            except Exception:
                if produced_output:
                    logger.exception("Model openrouter/%s failed mid-stream for %r", model, user_message)
                    yield "\n\n_(The response was interrupted. Please try again.)_"
                    return
                logger.warning("Model openrouter/%s failed, trying next in fallback chain", model, exc_info=True)

        logger.error("All models in fallback chain failed for question %r", user_message)
        yield FALLBACK_MESSAGE

    return evidence["chunks"], tokens()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    query = " ".join(sys.argv[1:]) or "What are the EU recycled content thresholds?"
    print(f"User: {query}\n")
    print(run_agent(query)["answer"])
