"""Tool wrapper around retrieval.search.get_section.

Exposes the `get_section` tool from CLAUDE.md's Agent tools list: exact
lookup of the full text of a specific article/section, for deep reading or
when the user asks to see the actual regulation text.
"""

from __future__ import annotations

import json
from typing import Any

from retrieval.search import get_section

NAME = "get_section"

SCHEMA = {
    "name": NAME,
    "description": (
        "Fetch the full, reassembled text of one specific article/section by "
        "exact instrument and section reference. Use this for deep reading "
        "once `search` has identified the relevant section, or whenever the "
        "user asks to see the actual regulation text. instrument and "
        "section_ref must match exactly what `search` returned -- do not "
        "guess or reformat them."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "instrument": {
                "type": "string",
                "description": (
                    "Exact instrument name, e.g. 'Regulation (EU) 2023/1542', "
                    "'40 CFR Part 273', '49 CFR 173.185'."
                ),
            },
            "section_ref": {
                "type": "string",
                "description": "Exact section reference, e.g. 'Article 7', '§ 273.13'.",
            },
        },
        "required": ["instrument", "section_ref"],
    },
}


def execute(tool_input: dict[str, Any]) -> str:
    instrument = tool_input["instrument"]
    section_ref = tool_input["section_ref"]

    section = get_section(instrument, section_ref)
    if section is None:
        return json.dumps(
            {
                "found": False,
                "note": f"No section '{section_ref}' found for instrument '{instrument}' in the verified corpus.",
            }
        )

    return json.dumps(
        {
            "found": True,
            "jurisdiction": section["jurisdiction"],
            "instrument": section["instrument"],
            "instrument_short": section["instrument_short"],
            "section_ref": section["section_ref"],
            "section_title": section["section_title"],
            "parent_context": section["parent_context"],
            "text": section["text"],
            "url": section["url"],
            "source_type": section["source_type"],
        },
        ensure_ascii=False,
    )
