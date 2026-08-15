"""FastAPI app: routes wiring agent/ and retrieval/ to HTTP.

Per CLAUDE.md's folder structure: routes, request/response schemas, and the
admin upload portal endpoints belong here; the actual agent and retrieval
logic stay in agent/ and retrieval/.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent.orchestrator import FALLBACK_MESSAGE, run_agent
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

    chunks_used = [
        ChunkUsed(
            section_ref=chunk["section_ref"],
            instrument=chunk["instrument"],
            instrument_short=chunk["instrument_short"],
            jurisdiction=chunk["jurisdiction"],
            url=chunk["url"],
        )
        for chunk in result["chunks"]
    ]
    return ChatResponse(answer=result["answer"], chunks_used=chunks_used)


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
