"""Curated obligations checklist for the `obligations_for` tool.

Given a battery category, capacity, and target markets, returns the
applicable provisions with citations -- a curated rule table over the
verified corpus (same "verified lookup, not free retrieval" principle as
list_deadlines_tool.py), so obligations are never invented for a
jurisdiction the corpus doesn't cover.

Only the two verified instruments are covered: Regulation (EU) 2023/1542
(EU) and the US federal transport/waste-handling rules (49 CFR 173.185,
40 CFR Part 273). Markets outside that coverage (e.g. individual US states)
are reported as corpus gaps, not silently dropped or guessed at.
"""

from __future__ import annotations

import json
from typing import Any

NAME = "obligations_for"

SCHEMA = {
    "name": NAME,
    "description": (
        "Given a battery category, capacity, and target markets, return the "
        "checklist of applicable provisions with citations. This is a "
        "curated rule table over the verified corpus, not a free-text "
        "search -- use it for 'what applies to my battery' questions. "
        "Markets outside the verified corpus (e.g. individual US states, "
        "non-US/EU jurisdictions) are reported as gaps, never guessed."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "battery_category": {
                "type": "string",
                "enum": ["portable", "lmt", "industrial", "ev", "sli", "stationary"],
                "description": (
                    "portable = general-use consumer batteries (AA/AAA, phone, laptop); "
                    "lmt = light means of transport (e-bike, e-scooter); "
                    "industrial = stationary/portable industrial batteries; "
                    "ev = electric vehicle batteries; "
                    "sli = starting/lighting/ignition (e.g. car) batteries; "
                    "stationary = stationary battery energy storage systems"
                ),
            },
            "capacity_kwh": {
                "type": "number",
                "description": "Battery capacity in kWh, if known. Some EU obligations only apply above 2 kWh for industrial batteries.",
            },
            "markets": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Target markets, e.g. ['EU', 'US-federal', 'US-CA'].",
            },
        },
        "required": ["battery_category", "markets"],
    },
}

INSTRUMENT_EU = "Regulation (EU) 2023/1542"
INSTRUMENT_UWR = "40 CFR Part 273"
INSTRUMENT_DOT = "49 CFR 173.185"

BATTERY_CATEGORIES: dict[str, dict[str, Any]] = {
    "portable": {
        "label": "Portable battery (general use, e.g. AA/AAA, phone, laptop)",
        "eu_obligations": [
            ("Article 9", "Performance and durability requirements for portable batteries of general use"),
            ("Article 11", "Removability and replaceability by the end-user"),
            ("Article 13", "Labelling and marking, incl. separate collection symbol"),
            ("Article 56", "Extended Producer Responsibility"),
            ("Article 59", "Collection targets for waste portable batteries (45%/63%/73% by 2023/2027/2030)"),
        ],
        "capacity_gated": [],
    },
    "lmt": {
        "label": "LMT battery (light means of transport, e.g. e-bike/e-scooter)",
        "eu_obligations": [
            ("Article 7", "Carbon footprint declaration"),
            ("Article 8", "Recycled content documentation and thresholds"),
            ("Article 10", "Performance and durability requirements"),
            ("Article 11", "Removability and replaceability by the end-user"),
            ("Article 13", "Labelling and marking"),
            ("Article 48", "Battery due diligence policies"),
            ("Article 60", "Collection targets for waste LMT batteries (51%/61% by 2028/2031)"),
            ("Article 77", "Battery passport"),
        ],
        "capacity_gated": [],
    },
    "industrial": {
        "label": "Industrial battery (stationary/portable industrial use)",
        "eu_obligations": [
            ("Article 13", "Labelling and marking"),
            ("Article 48", "Battery due diligence policies"),
            ("Article 61", "Collection of waste industrial batteries"),
        ],
        "capacity_gated": [
            (
                2.0,
                [
                    ("Article 7", "Carbon footprint declaration (applies above 2 kWh)"),
                    ("Article 8", "Recycled content documentation and thresholds (applies above 2 kWh)"),
                    ("Article 10", "Performance and durability requirements (applies above 2 kWh)"),
                    ("Article 77", "Battery passport (applies above 2 kWh)"),
                ],
            ),
        ],
    },
    "ev": {
        "label": "Electric vehicle (EV) battery",
        "eu_obligations": [
            ("Article 7", "Carbon footprint declaration"),
            ("Article 8", "Recycled content documentation and thresholds"),
            ("Article 10", "Performance and durability requirements"),
            ("Article 13", "Labelling and marking"),
            ("Article 48", "Battery due diligence policies"),
            ("Article 61", "Collection of waste electric vehicle batteries"),
            ("Article 77", "Battery passport"),
        ],
        "capacity_gated": [],
    },
    "sli": {
        "label": "SLI battery (starting, lighting, ignition -- e.g. car battery)",
        "eu_obligations": [
            ("Article 8", "Recycled content documentation and thresholds"),
            ("Article 13", "Labelling and marking"),
            ("Article 61", "Collection of waste SLI batteries"),
        ],
        "capacity_gated": [],
    },
    "stationary": {
        "label": "Stationary battery energy storage system (BESS)",
        "eu_obligations": [
            ("Article 12", "Safety of stationary battery energy storage systems"),
            ("Article 14", "State of health and expected lifetime information (battery management system)"),
        ],
        "capacity_gated": [],
    },
}

US_FEDERAL_TRANSPORT = [
    ("§ 173.185", "DOT/PHMSA classification, packaging, and marking for lithium cells and batteries"),
]
US_FEDERAL_WASTE = [
    ("§ 273.2", "Applicability of the Universal Waste Rule to batteries"),
    ("§ 273.13", "Universal waste battery handling/storage requirements (small quantity handler)"),
    ("§ 273.18", "Off-site shipment requirements for universal waste"),
]


def obligations_for(battery_category: str, markets: list[str], capacity_kwh: float | None = None) -> dict[str, Any]:
    category_key = battery_category.strip().lower()
    category = BATTERY_CATEGORIES.get(category_key)
    if category is None:
        return {
            "error": f"Unknown battery_category '{battery_category}'.",
            "known_categories": sorted(BATTERY_CATEGORIES),
        }

    obligations: list[dict[str, Any]] = []
    covered_markets: list[str] = []
    no_corpus_coverage: list[str] = []

    if any(m == "EU" or m.startswith("EU-") for m in markets):
        covered_markets.append("EU")
        for section_ref, note in category["eu_obligations"]:
            obligations.append(
                {"jurisdiction": "EU", "instrument": INSTRUMENT_EU, "section_ref": section_ref, "note": note}
            )
        if capacity_kwh is not None:
            for threshold, gated in category["capacity_gated"]:
                if capacity_kwh > threshold:
                    for section_ref, note in gated:
                        obligations.append(
                            {
                                "jurisdiction": "EU",
                                "instrument": INSTRUMENT_EU,
                                "section_ref": section_ref,
                                "note": note,
                            }
                        )

    us_markets = [m for m in markets if m == "US-federal" or m.startswith("US-")]
    if us_markets:
        covered_markets.append("US-federal")
        for section_ref, note in US_FEDERAL_TRANSPORT:
            obligations.append(
                {"jurisdiction": "US-federal", "instrument": INSTRUMENT_DOT, "section_ref": section_ref, "note": note}
            )
        for section_ref, note in US_FEDERAL_WASTE:
            obligations.append(
                {"jurisdiction": "US-federal", "instrument": INSTRUMENT_UWR, "section_ref": section_ref, "note": note}
            )
        state_markets = sorted({m for m in us_markets if m != "US-federal"})
        no_corpus_coverage.extend(state_markets)

    other_markets = [
        m for m in markets if not (m == "EU" or m.startswith("EU-") or m == "US-federal" or m.startswith("US-"))
    ]
    no_corpus_coverage.extend(other_markets)

    return {
        "battery_category": category["label"],
        "capacity_kwh": capacity_kwh,
        "obligations": obligations,
        "covered_markets": covered_markets,
        "no_corpus_coverage": sorted(set(no_corpus_coverage)),
    }


def execute(tool_input: dict[str, Any]) -> str:
    result = obligations_for(
        battery_category=tool_input["battery_category"],
        markets=tool_input["markets"],
        capacity_kwh=tool_input.get("capacity_kwh"),
    )
    return json.dumps(result, ensure_ascii=False)
