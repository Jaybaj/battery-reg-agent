"""Parser for EU Regulation (EU) 2023/1542 (the Battery Regulation) from EUR-Lex.

Extracts recitals and articles as independent citation-grounded chunks matching
the chunk metadata schema defined in CLAUDE.md.
"""

from __future__ import annotations

import re
import sys
import warnings
from datetime import date
from typing import Any

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

# EUR-Lex's XHTML documents open with an <?xml ...?> prolog, which trips bs4's
# "did you mean to parse this as XML?" heuristic even though it's real XHTML
# served for HTML rendering.
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

SOURCE_URL = "https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:32023R1542"
JURISDICTION = "EU"
INSTRUMENT = "Regulation (EU) 2023/1542"
INSTRUMENT_SHORT = "EU Battery Reg"
SOURCE_TYPE = "verified_corpus"
MAX_CHUNK_CHARS = 1500
USER_AGENT = "Mozilla/5.0 (compatible; battery-reg-agent-ingestion/0.1)"

# Heading/title classes that must never be folded into chunk body text.
_HEADING_CLASSES = {"oj-ti-art", "oj-sti-art", "oj-ti-section-1", "oj-ti-section-2"}


def fetch_html(url: str = SOURCE_URL, timeout: int = 30) -> str:
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    response.raise_for_status()
    return response.text


def _extract_lines(el) -> list[str]:
    """Flatten a EUR-Lex content block into ordered plain-text lines.

    Lettered/numbered sub-items render as two-column tables (marker cell +
    content cell) rather than inline text, so they're rejoined here into a
    single "(a) ..." line per row.
    """
    lines: list[str] = []
    for child in el.children:
        name = getattr(child, "name", None)
        if name is None:
            continue
        classes = set(child.get("class") or [])
        if name == "p" and classes & _HEADING_CLASSES:
            continue
        if name == "div" and "eli-title" in classes:
            continue
        if name == "table":
            for row in child.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) == 2:
                    marker = cells[0].get_text(" ", strip=True)
                    content = cells[1].get_text(" ", strip=True)
                    line = f"{marker} {content}".strip()
                else:
                    line = row.get_text(" ", strip=True)
                if line:
                    lines.append(line)
        elif name == "p":
            text = child.get_text(" ", strip=True)
            if text:
                lines.append(text)
        elif name in ("div", "span"):
            lines.extend(_extract_lines(child))
        else:
            text = child.get_text(" ", strip=True)
            if text:
                lines.append(text)
    return lines


def _paragraph_units(article_div) -> list[str]:
    """Render each direct child of an article div (a numbered clause, or a
    bare paragraph) as one flat text block, so a clause's own nested lettered
    sub-items stay attached to it instead of becoming separate split points.
    """
    units: list[str] = []
    for child in article_div.children:
        name = getattr(child, "name", None)
        if name is None:
            continue
        classes = set(child.get("class") or [])
        if name == "p" and classes & _HEADING_CLASSES:
            continue
        if name == "div" and "eli-title" in classes:
            continue
        text = child.get_text(" ", strip=True) if name == "p" else "\n".join(_extract_lines(child))
        if text:
            units.append(text)
    return units


def _deep_link(anchor: str) -> str:
    return f"{SOURCE_URL}#{anchor}"


def _base_chunk(section_ref: str, section_title: str, parent_context: str, url: str, version_date: date) -> dict[str, Any]:
    return {
        "jurisdiction": JURISDICTION,
        "instrument": INSTRUMENT,
        "instrument_short": INSTRUMENT_SHORT,
        "section_ref": section_ref,
        "section_title": section_title,
        "parent_context": parent_context,
        "url": url,
        "version_date": version_date,
        "source_type": SOURCE_TYPE,
    }


def parse_recitals(soup: BeautifulSoup, version_date: date) -> list[dict[str, Any]]:
    chunks = []
    for div in soup.find_all("div", id=re.compile(r"^rct_\d+$")):
        num = re.match(r"rct_(\d+)", div["id"]).group(1)
        text = "\n".join(_extract_lines(div))
        text = re.sub(rf"^\(\s*{num}\s*\)\s*", "", text).strip()
        chunk = _base_chunk(
            section_ref=f"Recital {num}",
            section_title="",
            parent_context="Recitals",
            url=_deep_link(f"rct_{num}"),
            version_date=version_date,
        )
        chunk["text"] = text
        chunks.append(chunk)
    return chunks


def parse_articles(soup: BeautifulSoup, version_date: date) -> list[dict[str, Any]]:
    chunks = []
    chapter_divs = soup.find_all("div", id=re.compile(r"^cpt_[IVXLCDM]+$"))

    for chapter_div in chapter_divs:
        chapter_num_el = chapter_div.find("p", class_="oj-ti-section-1")
        chapter_title_el = chapter_div.find("p", class_="oj-ti-section-2")
        chapter_num_text = chapter_num_el.get_text(" ", strip=True) if chapter_num_el else ""
        chapter_title = chapter_title_el.get_text(" ", strip=True) if chapter_title_el else ""

        roman_match = re.search(r"CHAPTER\s+([IVXLCDM]+)", chapter_num_text, re.IGNORECASE)
        chapter_roman = roman_match.group(1) if roman_match else chapter_num_text
        parent_context = f"Chapter {chapter_roman} – {chapter_title}".strip(" –")

        for article_div in chapter_div.find_all("div", id=re.compile(r"^art_\d+$")):
            num_el = article_div.find("p", class_="oj-ti-art")
            title_el = article_div.find("p", class_="oj-sti-art")
            num_match = re.search(r"\d+", num_el.get_text(strip=True)) if num_el else None
            article_num = num_match.group() if num_match else ""
            article_title = title_el.get_text(" ", strip=True) if title_el else ""

            paragraphs = _paragraph_units(article_div)
            full_text = "\n\n".join(paragraphs)
            header = f"Chapter {chapter_roman} – {chapter_title}\nArticle {article_num} – {article_title}\n\n"

            base = _base_chunk(
                section_ref=f"Article {article_num}",
                section_title=article_title,
                parent_context=parent_context,
                url=_deep_link(f"art_{article_num}"),
                version_date=version_date,
            )

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


def parse(html: str, version_date: date | None = None) -> list[dict[str, Any]]:
    version_date = version_date or date.today()
    soup = BeautifulSoup(html, "lxml")
    return parse_recitals(soup, version_date) + parse_articles(soup, version_date)


def run(url: str = SOURCE_URL) -> list[dict[str, Any]]:
    return parse(fetch_html(url))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    chunks = run()

    article_chunks = [c for c in chunks if c["section_ref"].startswith("Article")]
    recital_chunks = [c for c in chunks if c["section_ref"].startswith("Recital")]
    distinct_articles = {c["section_ref"] for c in article_chunks}

    print(f"Total chunks:   {len(chunks)}")
    print(f"Total articles: {len(distinct_articles)} ({len(article_chunks)} chunks, incl. splits)")
    print(f"Total recitals: {len(recital_chunks)}")

    print("\nSample chunks:\n")
    for target in ("Article 7", "Article 48", "Article 77"):
        matches = [c for c in article_chunks if c["section_ref"] == target]
        if not matches:
            print(f"--- {target}: NOT FOUND ---\n")
            continue
        first = matches[0]
        print(f"--- {target}: {first['section_title']} ({len(matches)} chunk(s)) ---")
        print(f"parent_context: {first['parent_context']}")
        print(f"url:            {first['url']}")
        print(f"text ({len(first['text'])} chars):")
        preview = first["text"][:500]
        print(preview + ("..." if len(first["text"]) > 500 else ""))
        print()
