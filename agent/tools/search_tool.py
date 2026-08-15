"""Tool wrapper around retrieval.search.hybrid_search.

Exposes the `search` tool from CLAUDE.md's Agent tools list: hybrid
(BM25 + vector) retrieval over the verified corpus, optionally filtered by
jurisdiction.
"""

from __future__ import annotations

import json
from typing import Any

from retrieval.search import hybrid_search

NAME = "search"

SCHEMA = {
    "name": NAME,
    "description": (
        "Hybrid (BM25 + vector) search over the verified regulatory corpus. "
        "Use this to find articles/sections relevant to a topic or situation. "
        "Returns ranked chunks with jurisdiction, instrument, section reference, "
        "title, and text -- always cite the section_ref field in your answer, "
        "never just the instrument as a whole. If no results are returned, the "
        "corpus has no coverage for this topic -- say so, do not guess."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural-language search query.",
            },
            "jurisdiction": {
                "type": "string",
                "description": (
                    "Optional jurisdiction filter, e.g. 'EU', 'US-federal', 'US-CA'. "
                    "Omit to search across all jurisdictions."
                ),
            },
            "top_k": {
                "type": "integer",
                "description": "Number of results to return (default 10).",
            },
        },
        "required": ["query"],
    },
}


def _format_result(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "jurisdiction": row["jurisdiction"],
        "instrument": row["instrument"],
        "instrument_short": row["instrument_short"],
        "section_ref": row["section_ref"],
        "section_title": row["section_title"],
        "parent_context": row["parent_context"],
        "text": row["text"],
        "url": row["url"],
        "source_type": row["source_type"],
    }


def execute(tool_input: dict[str, Any]) -> str:
    query = tool_input["query"]
    jurisdiction = tool_input.get("jurisdiction")
    top_k = tool_input.get("top_k", 10)

    results = hybrid_search(query, jurisdiction=jurisdiction, top_k=top_k)
    if not results:
        return json.dumps({"results": [], "note": "No matches in the verified corpus for this query."})

    return json.dumps({"results": [_format_result(r) for r in results]}, ensure_ascii=False)
