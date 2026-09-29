"""FastAPI app: routes wiring agent/ and retrieval/ to HTTP.

Per CLAUDE.md's folder structure: routes, request/response schemas, and the
admin upload portal endpoints belong here; the actual agent and retrieval
logic stay in agent/ and retrieval/.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.orchestrator import FALLBACK_MESSAGE, run_agent, stream_agent
from agent.tools.list_deadlines_tool import list_deadlines
from retrieval.search import get_section

logger = logging.getLogger(__name__)

app = FastAPI(title="battery-reg-agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    conversation_history: list[dict] = []


class ChunkUsed(BaseModel):
    section_ref: str
    instrument: str
    instrument_short: str
    jurisdiction: str
    url: str


class ChatResponse(BaseModel):
    answer: str
    chunks_used: list[ChunkUsed]


def _to_chunks_used(chunks: list[dict]) -> list[ChunkUsed]:
    return [
        ChunkUsed(
            section_ref=chunk["section_ref"],
            instrument=chunk["instrument"],
            instrument_short=chunk["instrument_short"],
            jurisdiction=chunk["jurisdiction"],
            url=chunk["url"],
        )
        for chunk in chunks
    ]


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    # Catches anything run_agent doesn't already handle itself (it has its own
    # internal fallback for Groq/retrieval failures) -- this is the last line
    # of defense so the API always returns 200 with valid JSON, never a raw 500.
    try:
        result = run_agent(request.message, conversation_history=request.conversation_history)
    except Exception:
        logger.exception("Unhandled error in /chat for message %r", request.message)
        return ChatResponse(answer=FALLBACK_MESSAGE, chunks_used=[])

    return ChatResponse(answer=result["answer"], chunks_used=_to_chunks_used(result["chunks"]))


def _sse(payload: object) -> str:
    # JSON-encode every payload: raw model text contains newlines, and a
    # blank line inside `data:` would terminate the SSE event early.
    return f"data: {json.dumps(payload)}\n\n"


_SSE_DONE = "data: [DONE]\n\n"
_INTERRUPTED_NOTE = "\n\n_(The response was interrupted. Please try again.)_"


@app.post("/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    """SSE version of /chat.

    Event sequence: one {"chunks_used": [...]} event (sent before generation
    starts, so citation cards can render immediately), then one {"token": str}
    event per piece of answer text, then a literal `data: [DONE]`. Like /chat,
    failures never surface as an HTTP error: they degrade to the fallback
    answer inside the stream.
    """

    def events() -> Iterator[str]:
        try:
            chunks, tokens = stream_agent(request.message, conversation_history=request.conversation_history)
        except Exception:
            logger.exception("Unhandled error in /chat/stream for message %r", request.message)
            yield _sse({"chunks_used": []})
            yield _sse({"token": FALLBACK_MESSAGE})
            yield _SSE_DONE
            return

        yield _sse({"chunks_used": [chunk.model_dump() for chunk in _to_chunks_used(chunks)]})
        try:
            for token in tokens:
                yield _sse({"token": token})
        except Exception:
            logger.exception("Unhandled error mid-stream in /chat/stream for message %r", request.message)
            yield _sse({"token": _INTERRUPTED_NOTE})
        yield _SSE_DONE

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        # Stop proxies (Railway's edge included) from buffering the stream.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/section/{instrument:path}/{section_ref}")
def section(instrument: str, section_ref: str) -> dict:
    result = get_section(instrument, section_ref)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No section '{section_ref}' found for instrument '{instrument}' in the verified corpus.",
        )
    return result


@app.get("/deadlines")
def deadlines() -> list[dict]:
    return list_deadlines()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
