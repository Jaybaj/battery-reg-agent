"""Curated deadline lookup table for the `list_deadlines` tool.

Per CLAUDE.md: "deadlines are the most-asked and most-hallucinated thing, so
these are a verified lookup table, not retrieval." Every date and percentage
below was read directly out of the ingested article text (see
retrieval.search.get_section), not recalled from memory -- e.g. the battery
due diligence deadline is verified as 18 August 2025 (Article 48(1)), not the
18 August 2027 sometimes assumed; collection targets differ by battery
category (portable vs. LMT) and must not be conflated.

Adding a new jurisdiction's deadlines means appending curated, verified
entries here -- never inferring a date from retrieval results.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

NAME = "list_deadlines"

SCHEMA = {
    "name": NAME,
    "description": (
        "Curated, verified lookup of regulatory deadlines -- NOT retrieval. "
        "Use this instead of `search` whenever the user asks about a "
        "deadline, effective date, phase-in date, or compliance timeline. "
        "Deadlines are the most commonly hallucinated fact in this domain, "
        "so always prefer this tool over recalling a date from memory or "
        "inferring one from a `search` result."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": (
                    "Topic keywords to filter by, e.g. 'carbon footprint', "
                    "'battery passport', 'due diligence', 'recycled content', "
                    "'collection targets', 'labelling', 'state of health'. "
                    "Omit to list all curated deadlines."
                ),
            },
            "jurisdiction": {
                "type": "string",
                "description": "Optional jurisdiction filter, e.g. 'EU'. Omit to search all jurisdictions.",
            },
        },
        "required": [],
    },
}

DEADLINES: list[dict[str, Any]] = [
    {
        "topic": "Carbon footprint declaration",
        "keywords": ["carbon footprint", "co2", "emissions", "declaration"],
        "jurisdiction": "EU",
        "instrument": "Regulation (EU) 2023/1542",
        "section_ref": "Article 7(1)(a)",
        "deadline_date": date(2025, 2, 18),
        "applies_to": "Electric vehicle batteries",
        "description": "Carbon footprint declaration required from this date (or 12 months after the implementing/delegated acts enter into force, whichever is latest).",
    },
    {
        "topic": "Carbon footprint declaration",
        "keywords": ["carbon footprint", "co2", "emissions", "declaration"],
        "jurisdiction": "EU",
        "instrument": "Regulation (EU) 2023/1542",
        "section_ref": "Article 7(1)(b)",
        "deadline_date": date(2026, 2, 18),
        "applies_to": "Rechargeable industrial batteries (>2 kWh, excl. exclusively external storage)",
        "description": "Carbon footprint declaration required from this date (or 18 months after the implementing/delegated acts enter into force, whichever is latest).",
    },
    {
        "topic": "Carbon footprint declaration",
        "keywords": ["carbon footprint", "co2", "emissions", "declaration", "lmt", "e-bike"],
        "jurisdiction": "EU",
        "instrument": "Regulation (EU) 2023/1542",
        "section_ref": "Article 7(1)(c)",
        "deadline_date": date(2028, 8, 18),
        "applies_to": "LMT batteries (e.g. e-bikes, e-scooters)",
        "description": "Carbon footprint declaration required from this date (or 18 months after the implementing/delegated acts enter into force, whichever is latest).",
    },
    {
        "topic": "Carbon footprint declaration",
        "keywords": ["carbon footprint", "co2", "emissions", "declaration"],
        "jurisdiction": "EU",
        "instrument": "Regulation (EU) 2023/1542",
        "section_ref": "Article 7(1)(d)",
        "deadline_date": date(2030, 8, 18),
        "applies_to": "Rechargeable industrial batteries with external storage",
        "description": "Carbon footprint declaration required from this date (or 18 months after the implementing/delegated acts enter into force, whichever is latest).",
    },
    {
        "topic": "Battery passport",
        "keywords": ["passport", "digital passport", "electronic record"],
        "jurisdiction": "EU",
        "instrument": "Regulation (EU) 2023/1542",
        "section_ref": "Article 77(1)",
        "deadline_date": date(2027, 2, 18),
        "applies_to": "LMT batteries, industrial batteries >2 kWh, and electric vehicle batteries",
        "description": "Each battery placed on the market or put into service must have an electronic battery passport from this date.",
    },
    {
        "topic": "Battery due diligence policies",
        "keywords": ["due diligence"],
        "jurisdiction": "EU",
        "instrument": "Regulation (EU) 2023/1542",
        "section_ref": "Article 48(1)",
        "deadline_date": date(2025, 8, 18),
        "applies_to": "All economic operators placing batteries on the market or putting them into service",
        "description": "Due diligence obligations (policy set-up, third-party verification, documentation) apply from this date. Verified against Article 48(1) text -- commonly misremembered as August 2027, which is incorrect.",
    },
    {
        "topic": "Recycled content documentation",
        "keywords": ["recycled content", "cobalt", "lithium recovery", "lead", "nickel"],
        "jurisdiction": "EU",
        "instrument": "Regulation (EU) 2023/1542",
        "section_ref": "Article 8(1), first subparagraph",
        "deadline_date": date(2028, 8, 18),
        "applies_to": "Industrial batteries >2 kWh, electric vehicle batteries, and SLI batteries containing cobalt, lead, lithium or nickel",
        "description": "Documentation on the percentage share of recovered cobalt/lithium/nickel/lead required from this date (or 24 months after the relevant delegated act, whichever is latest).",
    },
    {
        "topic": "Recycled content documentation",
        "keywords": ["recycled content", "cobalt", "lithium recovery", "lmt", "e-bike"],
        "jurisdiction": "EU",
        "instrument": "Regulation (EU) 2023/1542",
        "section_ref": "Article 8(1), second subparagraph",
        "deadline_date": date(2033, 8, 18),
        "applies_to": "LMT batteries containing cobalt, lead, lithium or nickel",
        "description": "Same recycled-content documentation requirement as above, extended to LMT batteries from this date.",
    },
    {
        "topic": "Recycled content minimum thresholds",
        "keywords": ["recycled content", "minimum threshold", "cobalt", "lithium", "nickel", "lead"],
        "jurisdiction": "EU",
        "instrument": "Regulation (EU) 2023/1542",
        "section_ref": "Article 8(2)",
        "deadline_date": date(2031, 8, 18),
        "applies_to": "Industrial batteries >2 kWh, electric vehicle batteries, and SLI batteries",
        "description": "Minimum recovered-content thresholds apply from this date: 16% cobalt, 85% lead, 6% lithium, 6% nickel.",
    },
    {
        "topic": "Recycled content minimum thresholds",
        "keywords": ["recycled content", "minimum threshold", "cobalt", "lithium", "nickel", "lead"],
        "jurisdiction": "EU",
        "instrument": "Regulation (EU) 2023/1542",
        "section_ref": "Article 8(3)",
        "deadline_date": date(2036, 8, 18),
        "applies_to": "Industrial batteries >2 kWh, electric vehicle batteries, LMT batteries, and SLI batteries",
        "description": "Higher minimum recovered-content thresholds apply from this date: 26% cobalt, 85% lead, 12% lithium, 15% nickel.",
    },
    {
        "topic": "Collection targets -- portable batteries",
        "keywords": ["collection target", "portable battery"],
        "jurisdiction": "EU",
        "instrument": "Regulation (EU) 2023/1542",
        "section_ref": "Article 59(3)(a)",
        "deadline_date": date(2023, 12, 31),
        "applies_to": "Waste portable batteries",
        "description": "Producers/PROs must attain and durably maintain a 45% collection rate for waste portable batteries by this date.",
    },
    {
        "topic": "Collection targets -- portable batteries",
        "keywords": ["collection target", "portable battery"],
        "jurisdiction": "EU",
        "instrument": "Regulation (EU) 2023/1542",
        "section_ref": "Article 59(3)(b)",
        "deadline_date": date(2027, 12, 31),
        "applies_to": "Waste portable batteries",
        "description": "Collection rate target rises to 63% by this date.",
    },
    {
        "topic": "Collection targets -- portable batteries",
        "keywords": ["collection target", "portable battery"],
        "jurisdiction": "EU",
        "instrument": "Regulation (EU) 2023/1542",
        "section_ref": "Article 59(3)(c)",
        "deadline_date": date(2030, 12, 31),
        "applies_to": "Waste portable batteries",
        "description": "Collection rate target rises to 73% by this date.",
    },
    {
        "topic": "Collection targets -- LMT batteries",
        "keywords": ["collection target", "lmt battery", "e-bike"],
        "jurisdiction": "EU",
        "instrument": "Regulation (EU) 2023/1542",
        "section_ref": "Article 60(3)(a)",
        "deadline_date": date(2028, 12, 31),
        "applies_to": "Waste LMT batteries (e.g. e-bikes, e-scooters)",
        "description": "Producers/PROs must attain and durably maintain a 51% collection rate for waste LMT batteries by this date. Note: distinct from the portable-battery targets above -- do not conflate the two categories.",
    },
    {
        "topic": "Collection targets -- LMT batteries",
        "keywords": ["collection target", "lmt battery", "e-bike"],
        "jurisdiction": "EU",
        "instrument": "Regulation (EU) 2023/1542",
        "section_ref": "Article 60(3)(b)",
        "deadline_date": date(2031, 12, 31),
        "applies_to": "Waste LMT batteries (e.g. e-bikes, e-scooters)",
        "description": "Collection rate target rises to 61% by this date.",
    },
    {
        "topic": "Labelling -- separate collection symbol",
        "keywords": ["labelling", "label", "separate collection symbol", "marking"],
        "jurisdiction": "EU",
        "instrument": "Regulation (EU) 2023/1542",
        "section_ref": "Article 13(4)",
        "deadline_date": date(2025, 8, 18),
        "applies_to": "All batteries",
        "description": "All batteries must be marked with the separate collection symbol from this date.",
    },
    {
        "topic": "Labelling -- general and capacity information",
        "keywords": ["labelling", "label", "capacity", "marking"],
        "jurisdiction": "EU",
        "instrument": "Regulation (EU) 2023/1542",
        "section_ref": "Article 13(1)-(2)",
        "deadline_date": date(2026, 8, 18),
        "applies_to": "All batteries; rechargeable portable, LMT, and SLI batteries (capacity label)",
        "description": "General label and, for rechargeable portable/LMT/SLI batteries, capacity information required from this date (or 18 months after the relevant implementing act, whichever is latest).",
    },
    {
        "topic": "State of health / battery management system data",
        "keywords": ["state of health", "battery management system", "bms"],
        "jurisdiction": "EU",
        "instrument": "Regulation (EU) 2023/1542",
        "section_ref": "Article 14(1)",
        "deadline_date": date(2024, 8, 18),
        "applies_to": "Stationary battery energy storage systems, LMT batteries, and electric vehicle batteries",
        "description": "Battery management systems must contain up-to-date state-of-health and expected-lifetime data from this date.",
    },
]

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text.lower()))


def list_deadlines(topic: str | None = None, jurisdiction: str | None = None) -> list[dict[str, Any]]:
    matches = DEADLINES
    if jurisdiction:
        matches = [d for d in matches if d["jurisdiction"] == jurisdiction]
    if topic:
        query_tokens = _tokens(topic)
        matches = [
            d
            for d in matches
            if query_tokens & _tokens(d["topic"]) or query_tokens & _tokens(" ".join(d["keywords"]))
        ]
    return matches


def execute(tool_input: dict[str, Any]) -> str:
    topic = tool_input.get("topic")
    jurisdiction = tool_input.get("jurisdiction")

    matches = list_deadlines(topic=topic, jurisdiction=jurisdiction)
    if not matches:
        return json.dumps(
            {
                "deadlines": [],
                "note": "No curated deadlines match this query. This may be a genuine corpus gap -- say so, do not estimate a date.",
            }
        )

    rows = [{**d, "deadline_date": d["deadline_date"].isoformat()} for d in matches]
    return json.dumps({"deadlines": rows}, ensure_ascii=False)
