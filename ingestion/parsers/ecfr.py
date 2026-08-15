"""Parser for US federal battery-related regulations from the eCFR API.

Covers the two instruments listed in CLAUDE.md's Sources of truth:
  - 40 CFR Part 273 (Universal Waste Rule)               -- every section
  - 49 CFR 173.185 (DOT/PHMSA lithium battery transport)  -- a single section

Matches the chunk metadata schema defined in CLAUDE.md.
"""

from __future__ import annotations

import json
import re
import string
import sys
from datetime import date
from typing import Any

import requests
from bs4 import BeautifulSoup

API_BASE = "https://www.ecfr.gov/api/versioner/v1"
JURISDICTION = "US-federal"
SOURCE_TYPE = "verified_corpus"
MAX_CHUNK_CHARS = 1500
USER_AGENT = "Mozilla/5.0 (compatible; battery-reg-agent-ingestion/0.1)"

# Each target is a (title, part) to fetch in full; `sections=None` keeps every
# section in the part, otherwise only the given section numbers are kept.
TARGETS: list[dict[str, Any]] = [
    {
        "title": 40,
        "part": "273",
        "instrument": "40 CFR Part 273",
        "instrument_short": "Universal Waste Rule",
        "sections": None,
    },
    {
        "title": 49,
        "part": "173",
        "instrument": "49 CFR 173.185",
        "instrument_short": "DOT Lithium Battery Transport",
        "sections": {"173.185"},
    },
]

_TOP_LEVEL_MARKER = re.compile(r"^\(([a-z])\)\s")


def fetch_current_date(title: int, timeout: int = 30) -> str:
    """The versioner API has no 'current' alias; look up the as-of date first."""
    response = requests.get(f"{API_BASE}/titles.json", headers={"User-Agent": USER_AGENT}, timeout=timeout)
    response.raise_for_status()
    for entry in response.json()["titles"]:
        if entry["number"] == title:
            return entry["up_to_date_as_of"]
    raise ValueError(f"Title {title} not found in eCFR titles list")


def fetch_part_xml(title: int, part: str, as_of_date: str, timeout: int = 60) -> str:
    url = f"{API_BASE}/full/{as_of_date}/title-{title}.xml"
    response = requests.get(url, params={"part": part}, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    response.raise_for_status()
    return response.text


def _paragraph_units(section_div) -> list[str]:
    """Group a section's flat <P> tags by CFR's fixed (a)(1)(i)(A) nesting
    convention: each top-level (a)/(b)/(c)... marker starts a new unit, and
    every deeper-nested <P> until the next one stays attached to it.

    A single lowercase letter is ambiguous on its own -- "(i)" is both the
    9th top-level letter and the lowercase-roman-numeral "1" one level down
    -- so a marker only starts a new unit if it matches the *next expected*
    top-level letter in sequence, not just any single-letter marker.
    """
    units: list[str] = []
    current: list[str] = []
    expected_idx = 0
    for p in section_div.find_all("P"):
        text = p.get_text(" ", strip=True)
        if not text:
            continue
        match = _TOP_LEVEL_MARKER.match(text)
        is_next_top_level = (
            match is not None
            and expected_idx < len(string.ascii_lowercase)
            and match.group(1) == string.ascii_lowercase[expected_idx]
        )
        if is_next_top_level:
            if current:
                units.append("\n".join(current))
            current = [text]
            expected_idx += 1
        else:
            current.append(text)
    if current:
        units.append("\n".join(current))
    return units


def _deep_link(section_div, as_of_date: str) -> str:
    meta = section_div.get("hierarchy_metadata")
    if meta:
        path = json.loads(meta)["path"].replace("_SUBSTITUTE_DATE_", as_of_date)
        return f"https://www.ecfr.gov{path}"
    return f"https://www.ecfr.gov/on/{as_of_date}"


def parse_part(xml: str, target: dict[str, Any], as_of_date: str, version_date: date) -> list[dict[str, Any]]:
    soup = BeautifulSoup(xml, "xml")

    part_div = soup.find("DIV5", attrs={"TYPE": "PART"})
    part_num = part_div["N"] if part_div is not None else target["part"]
    part_head_el = part_div.find("HEAD", recursive=False) if part_div is not None else None
    part_head_text = part_head_el.get_text(" ", strip=True) if part_head_el is not None else ""
    part_title = re.sub(rf"^PART\s+{re.escape(part_num)}\s*[—-]\s*", "", part_head_text, flags=re.IGNORECASE).strip()
    parent_context = f"Part {part_num} – {part_title}".strip(" –")

    allowed_sections = target["sections"]
    chunks: list[dict[str, Any]] = []

    for section_div in soup.find_all("DIV8", attrs={"TYPE": "SECTION"}):
        section_num = section_div["N"]
        if allowed_sections and section_num not in allowed_sections:
            continue

        head_el = section_div.find("HEAD", recursive=False)
        head_text = head_el.get_text(" ", strip=True) if head_el is not None else f"§ {section_num}"
        section_title = re.sub(rf"^§\s*{re.escape(section_num)}\s*", "", head_text).strip().rstrip(".")

        paragraphs = _paragraph_units(section_div)
        full_text = "\n\n".join(paragraphs)
        header = f"{parent_context}\n§ {section_num} – {section_title}\n\n"
        url = _deep_link(section_div, as_of_date)

        base = {
            "jurisdiction": JURISDICTION,
            "instrument": target["instrument"],
            "instrument_short": target["instrument_short"],
            "section_ref": f"§ {section_num}",
            "section_title": section_title,
            "parent_context": parent_context,
            "url": url,
            "version_date": version_date,
            "source_type": SOURCE_TYPE,
        }

        if len(full_text) <= MAX_CHUNK_CHARS or len(paragraphs) <= 1:
            chunk = dict(base)
            chunk["text"] = header + full_text
            chunks.append(chunk)
        else:
            for para in paragraphs:
                chunk = dict(base)
                chunk["text"] = header + para
                chunks.append(chunk)

    return chunks


def run(targets: list[dict[str, Any]] = TARGETS, version_date: date | None = None) -> list[dict[str, Any]]:
    version_date = version_date or date.today()
    date_cache: dict[int, str] = {}
    chunks: list[dict[str, Any]] = []

    for target in targets:
        title = target["title"]
        if title not in date_cache:
            date_cache[title] = fetch_current_date(title)
        as_of_date = date_cache[title]

        xml = fetch_part_xml(title, target["part"], as_of_date)
        chunks.extend(parse_part(xml, target, as_of_date, version_date))

    return chunks


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    chunks = run()

    print(f"Total chunks: {len(chunks)}\n")
    for target in TARGETS:
        instrument_chunks = [c for c in chunks if c["instrument"] == target["instrument"]]
        distinct_sections = {c["section_ref"] for c in instrument_chunks}
        print(f"{target['instrument']}: {len(distinct_sections)} section(s), {len(instrument_chunks)} chunk(s)")
    print()

    print("Sample chunks:\n")
    samples = [
        ("40 CFR Part 273", "§ 273.1"),
        ("40 CFR Part 273", "§ 273.33"),
        ("49 CFR 173.185", "§ 173.185"),
    ]
    for instrument, section_ref in samples:
        matches = [c for c in chunks if c["instrument"] == instrument and c["section_ref"] == section_ref]
        if not matches:
            print(f"--- {instrument} {section_ref}: NOT FOUND ---\n")
            continue
        first = matches[0]
        print(f"--- {instrument} {section_ref}: {first['section_title']} ({len(matches)} chunk(s)) ---")
        print(f"parent_context: {first['parent_context']}")
        print(f"url:            {first['url']}")
        print(f"text ({len(first['text'])} chars):")
        preview = first["text"][:500]
        print(preview + ("..." if len(first["text"]) > 500 else ""))
        print()
