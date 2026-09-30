"""Compliance checklist for the /checker page: verified obligations + verified deadlines.

Built only from the two curated tables -- obligations_for (which provisions
apply to a battery) and list_deadlines (when each applies) -- never from
generated text, so every article reference, date and status shown on a
checklist card is traceable to the verified corpus. Narrative guidance comes
separately from the agent.

Each obligation is matched to the curated deadlines for the same article
whose "applies to" covers the battery category, then grouped by urgency:
  in_force -- a matched deadline has passed (or it's current US federal
              law, which has no phase-in date)
  upcoming -- matched deadlines, none passed yet; soonest first
  undated  -- applies, but the verified deadline table has no date for it
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from agent.tools.list_deadlines_tool import list_deadlines
from agent.tools.obligations_for_tool import obligations_for

# Matched against a curated deadline's "applies_to" text. Stationary energy
# storage systems are industrial batteries under Regulation (EU) 2023/1542.
_CATEGORY_PATTERNS: dict[str, re.Pattern[str]] = {
    "portable": re.compile(r"portable", re.IGNORECASE),
    "lmt": re.compile(r"\bLMT\b"),
    "industrial": re.compile(r"industrial|stationary battery energy storage", re.IGNORECASE),
    "ev": re.compile(r"electric vehicle", re.IGNORECASE),
    "sli": re.compile(r"\bSLI\b"),
    "stationary": re.compile(r"industrial|stationary battery energy storage", re.IGNORECASE),
}
# "All batteries", "All economic operators", "All lithium cells and batteries",
# "All small quantity handlers..." -- not specific to one battery category.
_APPLIES_TO_ALL = re.compile(r"^all\b", re.IGNORECASE)
_BASE_REF = re.compile(r"^(Article \d+[a-z]?|§\s*[\d.]+)")


def _base_ref(section_ref: str) -> str:
    match = _BASE_REF.match(section_ref)
    return match.group(1) if match else section_ref


def _ref_order(section_ref: str) -> tuple[int, ...]:
    """Document order for a reference: "§ 273.2" < "§ 273.13" (not decimals), "Article 8" < "Article 10"."""
    return tuple(int(part) for part in re.findall(r"\d+", section_ref)) or (10**9,)


def _deadline_applies(deadline: dict[str, Any], category: str) -> bool:
    applies_to = deadline["applies_to"]
    return bool(_APPLIES_TO_ALL.search(applies_to) or _CATEGORY_PATTERNS[category].search(applies_to))


def build_checklist(
    battery_category: str,
    markets: list[str],
    capacity_kwh: float | None = None,
    chemistry: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    category = battery_category.strip().lower()
    base = obligations_for(category, markets, capacity_kwh=capacity_kwh, chemistry=chemistry)
    if "error" in base:
        return base

    deadlines = list_deadlines(today=today)
    items: list[dict[str, Any]] = []

    for obligation in base["obligations"]:
        matched = [
            {**d, "deadline_date": d["deadline_date"] and d["deadline_date"].isoformat()}
            for d in deadlines
            if d["jurisdiction"] == obligation["jurisdiction"]
            and _base_ref(d["section_ref"]) == obligation["section_ref"]
            and _deadline_applies(d, category)
        ]

        if matched:
            in_force = [d for d in matched if d["status"] == "in force"]
            upcoming = [d for d in matched if d["status"] == "upcoming"]
            urgency = "in_force" if in_force else "upcoming"
            # list_deadlines puts undated (current-law) entries first, then by date.
            sort_date = (in_force or upcoming)[0]["deadline_date"] or ""
            timing_note = None
        elif obligation["jurisdiction"].startswith("US"):
            urgency, sort_date = "in_force", ""
            timing_note = "Current federal regulation; no phase-in date."
        else:
            urgency, sort_date = "undated", ""
            timing_note = "No date in the verified deadline table. Check the article for when it applies."

        item = {
            **obligation,
            "id": f"{obligation['jurisdiction']}|{obligation['section_ref']}",
            "urgency": urgency,
            "deadlines": matched,
            "timing_note": timing_note,
        }
        items.append(((sort_date, _ref_order(obligation["section_ref"])), item))

    groups: dict[str, list[dict[str, Any]]] = {"in_force": [], "upcoming": [], "undated": []}
    for _, item in sorted(items, key=lambda pair: pair[0]):
        groups[item["urgency"]].append(item)

    return {
        "battery_category": base["battery_category"],
        "capacity_kwh": capacity_kwh,
        "chemistry": chemistry,
        "covered_markets": base["covered_markets"],
        "no_corpus_coverage": base["no_corpus_coverage"],
        "coverage_notes": base["coverage_notes"],
        "groups": groups,
    }
