"""Tool for cross-jurisdiction comparison searches.

Exposes the `compare_jurisdictions` tool from CLAUDE.md's Agent tools list:
runs the same topic search in parallel across multiple jurisdictions so the
model can synthesize a comparison. This tool only gathers grouped, cited
results -- the actual comparative synthesis happens in the model's answer.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from retrieval.search import hybrid_search

NAME = "compare_jurisdictions"

SCHEMA = {
    "name": NAME,
    "description": (
        "Run the same topic search across multiple jurisdictions in parallel "
        "and return grouped, cited results for each. Use this when the user "
        "wants a side-by-side comparison of how different jurisdictions treat "
        "the same topic (e.g. recycled content thresholds in the EU vs. "
        "collection requirements in the US). Jurisdictions with no verified "
        "corpus coverage are reported as gaps, not silently skipped."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "The topic to compare, e.g. 'collection targets for waste batteries'.",
            },
            "jurisdictions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Jurisdictions to compare, e.g. ['EU', 'US-federal', 'US-CA'].",
            },
            "top_k": {
                "type": "integer",
                "description": "Results to return per jurisdiction (default 5).",
            },
        },
        "required": ["topic", "jurisdictions"],
    },
}


def _format_result(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "instrument": row["instrument"],
        "section_ref": row["section_ref"],
        "section_title": row["section_title"],
        "text": row["text"],
        "url": row["url"],
        "source_type": row["source_type"],
    }


def _search_one(topic: str, jurisdiction: str, top_k: int) -> list[dict[str, Any]]:
    results = hybrid_search(topic, jurisdiction=jurisdiction, top_k=top_k)
    return [_format_result(r) for r in results]


def execute(tool_input: dict[str, Any]) -> str:
    topic = tool_input["topic"]
    jurisdictions = tool_input["jurisdictions"]
    top_k = tool_input.get("top_k", 5)

    with ThreadPoolExecutor(max_workers=max(len(jurisdictions), 1)) as executor:
        futures = {j: executor.submit(_search_one, topic, j, top_k) for j in jurisdictions}
        by_jurisdiction = {j: future.result() for j, future in futures.items()}

    no_coverage = [j for j, results in by_jurisdiction.items() if not results]

    return json.dumps(
        {
            "topic": topic,
            "by_jurisdiction": by_jurisdiction,
            "no_coverage": no_coverage,
        },
        ensure_ascii=False,
    )
