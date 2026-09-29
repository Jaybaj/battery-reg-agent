"""Pure-Python retrieve step: no LLM call, no tool-calling.

Given a user question, decides (via simple keyword/intent detection) which
of the existing tool functions to run, runs them directly, and returns the
gathered evidence for the generate step in agent/orchestrator.py to format
as context.

Keeping tool selection here in plain Python -- rather than delegating it to
the LLM via tool-calling -- sidesteps the tool-calling reliability problems
some models hit on some providers; every model only ever needs to do one
plain chat completion over pre-gathered context.
"""

from __future__ import annotations

import logging
import math
import re
from concurrent.futures import ThreadPoolExecutor
from itertools import zip_longest
from typing import Any

from agent.tools.list_deadlines_tool import list_deadlines
from retrieval.search import hybrid_search, list_jurisdictions

logger = logging.getLogger(__name__)

TOP_K = 5

_DEADLINE_KEYWORDS = re.compile(
    r"\b(deadline|by when|timeline|phase-?in|effective date|compliance date|"
    r"when (do|does|must|is|are)|due date|come into force|enter into force|"
    r"threshold|percentage|target|requirement|minimum)\b",
    re.IGNORECASE,
)

_KEY_TERMS = (
    "battery",
    "regulation",
    "lithium",
    "transport",
    "recycling",
    "compliance",
    "passport",
    "diligence",
    "threshold",
    "certificate",
)

_MAX_TYPO_DISTANCE = 2


def _levenshtein(a: str, b: str) -> int:
    """Standard edit distance, used to catch near-miss spellings of key terms."""
    if a == b:
        return 0
    previous_row = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current_row = [i]
        for j, char_b in enumerate(b, start=1):
            insertion = current_row[j - 1] + 1
            deletion = previous_row[j] + 1
            substitution = previous_row[j - 1] + (char_a != char_b)
            current_row.append(min(insertion, deletion, substitution))
        previous_row = current_row
    return previous_row[-1]


def _autocorrect_typos(question: str) -> tuple[str, list[tuple[str, str]]]:
    """Correct near-miss spellings of key battery-regulation terms in `question`.

    Only whole words are considered, and only close matches (edit distance <=
    _MAX_TYPO_DISTANCE, and never a match against a word that's already a key
    term or an inflection of one, e.g. "thresholds") are corrected -- this keeps unrelated words untouched rather than
    forcing them toward the nearest key term. Returns the corrected question
    plus a list of (original, corrected) pairs so the caller can tell the
    user what was changed.
    """
    corrections: list[tuple[str, str]] = []

    def _fix(match: re.Match[str]) -> str:
        word = match.group(0)
        lowered = word.lower()
        if any(lowered.startswith(term) for term in _KEY_TERMS):
            return word

        best_term = None
        best_distance = _MAX_TYPO_DISTANCE + 1
        for term in _KEY_TERMS:
            distance = _levenshtein(lowered, term)
            if distance < best_distance:
                best_distance = distance
                best_term = term

        if best_term is None or best_distance > _MAX_TYPO_DISTANCE or best_distance == 0:
            return word

        corrections.append((word, best_term))
        return best_term

    corrected = re.sub(r"[A-Za-z]+", _fix, question)
    return corrected, corrections


_JURISDICTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "EU": ("eu", "european union", "europe"),
    "US-federal": ("us federal", "u.s. federal", "federal", "dot", "phmsa", "epa"),
    "US-CA": ("california",),
    "US-WA": ("washington state", "washington"),
    "US-NJ": ("new jersey",),
    "US-IL": ("illinois",),
}


def _detect_jurisdiction(question: str) -> str | None:
    """Return a single jurisdiction filter only when exactly one is unambiguously named.

    Any other case (none named, or several named for a comparison) is left
    unfiltered so retrieval covers the whole corpus rather than risking an
    over-narrow filter on a mixed-jurisdiction question.
    """
    lowered = question.lower()
    matched = [code for code, keywords in _JURISDICTION_KEYWORDS.items() if any(kw in lowered for kw in keywords)]
    return matched[0] if len(matched) == 1 else None


_FOLLOW_UP_REFERENCES = re.compile(
    r"\b(this|that|these|those|it|its|they|them|their|there|same)\b",
    re.IGNORECASE,
)
_FOLLOW_UP_OPENERS = re.compile(r"^\s*(what about|how about|and|also|what if|but)\b", re.IGNORECASE)
_MAX_FOLLOW_UP_WORDS = 12

_STOPWORDS = frozenset(
    """
    a an the and or but if so than then as of for to in on at by with about from into under over
    what which who whom whose when where why how do does did is are was were be been being
    can could should would will shall must may might need needs
    i me my we us our you your he she him her this that these those it its they them their there
    any all some each tell explain please know want like get have has had also same just
    """.split()
)


# Words that say what *kind* of information is wanted rather than what it's
# about. Dropped from the previous question so only its topic carries over
# ("battery passport requirements" -> "battery passport"); the follow-up
# supplies the new intent instead.
_GENERIC_INTENT_WORDS = frozenset(
    """
    requirement requirements rule rules obligation obligations regulation regulations
    deadline deadlines detail details information info overview apply applies applicable
    """.split()
)

# Verbs that carry no intent of their own in a follow-up ("does it apply to EVs?").
_NON_INTENT_WORDS = frozenset({"apply", "applies", "applicable"})

# Shorthand in follow-ups expanded to the phrasing the corpus actually uses.
_TERM_EXPANSIONS = {
    "ev": "EV batteries",
    "evs": "EV batteries",
    "lmt": "LMT batteries",
    "lmts": "LMT batteries",
}


def _is_follow_up(question: str) -> bool:
    """Short questions that lean on a pronoun or a "what about..." opener.

    Deliberately a cheap heuristic (no LLM call): a false positive swaps the
    question for a keyword query built from it plus the previous question's
    topic, which hybrid search still handles reasonably.
    """
    if len(re.findall(r"\w+", question)) > _MAX_FOLLOW_UP_WORDS:
        return False
    return bool(_FOLLOW_UP_OPENERS.search(question) or _FOLLOW_UP_REFERENCES.search(question))


def _normalize(word: str) -> str:
    """Crude singular form for de-duplication ("batteries" == "battery")."""
    lowered = word.lower()
    if lowered.endswith("ies") and len(lowered) > 4:
        return lowered[:-3] + "y"
    if lowered.endswith("s") and not lowered.endswith("ss") and len(lowered) > 3:
        return lowered[:-1]
    return lowered


def _key_terms(text: str) -> list[str]:
    """Content words of `text` in order, minus stopwords/pronouns, deduplicated."""
    terms: list[str] = []
    seen: set[str] = set()
    for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9/.\-]*[A-Za-z0-9]|[A-Za-z0-9]", text):
        normalized = _normalize(word)
        if word.lower() in _STOPWORDS or normalized in seen:
            continue
        seen.add(normalized)
        terms.append(word)
    return terms


def _rewrite_follow_up(question: str, conversation_history: list[dict[str, Any]] | None) -> str:
    """Replace a follow-up with a standalone keyword query: previous topic + new intent.

    The topic is the previous user question's key terms minus generic intent
    words; the intent is the follow-up's own key terms. e.g. after "What are
    the battery passport requirements?":
      "What about the deadlines for this?" -> "battery passport deadlines"
      "What about California?"            -> "battery passport California"
      "And for EVs?"                       -> "battery passport EV batteries"
    If the previous question was itself a follow-up, it's resolved first
    (recursively, against the history before it), so a chain of follow-ups
    keeps the original topic.
    """
    if not conversation_history or not _is_follow_up(question):
        return question

    for index in range(len(conversation_history) - 1, -1, -1):
        turn = conversation_history[index]
        if turn.get("role") == "user" and isinstance(turn.get("content"), str):
            previous = _rewrite_follow_up(turn["content"], conversation_history[:index])
            break
    else:
        return question

    topic = [term for term in _key_terms(previous) if term.lower() not in _GENERIC_INTENT_WORDS]
    if not topic:
        return question

    topic_words = {_normalize(term) for term in topic}
    intent = [
        _TERM_EXPANSIONS.get(term.lower(), term)
        for term in _key_terms(question)
        if _normalize(term) not in topic_words and term.lower() not in _NON_INTENT_WORDS
    ]
    return " ".join(topic + intent)


def _interleave(result_lists: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Round-robin merge: one result from each list, then a second from each, etc.

    Keeps a query balanced across jurisdictions regardless of which
    jurisdiction's list happens to come first or be longest.
    """
    interleaved: list[dict[str, Any]] = []
    for group in zip_longest(*result_lists, fillvalue=None):
        interleaved.extend(item for item in group if item is not None)
    return interleaved


def _balanced_search(question: str, top_k: int) -> list[dict[str, Any]]:
    """Search every jurisdiction present in the corpus and interleave the results.

    A plain unfiltered hybrid_search would let whichever jurisdiction has the
    most/densest chunks dominate a general question's results. Querying each
    jurisdiction separately and interleaving means a jurisdiction-less
    question always surfaces a representative slice from every jurisdiction
    that exists -- including ones added after this code was written.
    """
    jurisdictions = list_jurisdictions()
    if not jurisdictions:
        return hybrid_search(question, top_k=top_k)

    per_jurisdiction_k = max(1, math.ceil(top_k / len(jurisdictions)))
    with ThreadPoolExecutor(max_workers=len(jurisdictions)) as executor:
        futures = [executor.submit(hybrid_search, question, j, per_jurisdiction_k) for j in jurisdictions]
        by_jurisdiction = [future.result() for future in futures]

    return _interleave(by_jurisdiction)[:top_k]


def retrieve(question: str, conversation_history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Gather evidence for `question`: ranked chunks, plus curated deadlines.

    Follow-up questions ("what about the deadlines for this?") are rewritten
    into standalone search queries using the previous user question from
    `conversation_history` -- see _rewrite_follow_up.

    list_deadlines runs on every call, same as the chunk search -- deadlines
    and numeric thresholds are exactly the facts this domain hallucinates
    most, so the curated table is always consulted rather than gated behind
    a guess about whether the question "looks" deadline-related. When the
    question does match deadline/threshold-ish language, the topic filter is
    dropped entirely (None) so the curated table's full relevant set comes
    back rather than only whatever narrower overlap the topic filter would
    have kept.

    Retrieval failures (e.g. the database is unreachable) are caught here so
    a corpus/infra problem degrades to "no chunks found" instead of crashing
    the whole request -- the system prompt is written to handle an empty
    retrieved context gracefully.
    """
    corrected_question, typo_corrections = _autocorrect_typos(question)
    search_question = _rewrite_follow_up(corrected_question, conversation_history)
    if search_question != corrected_question:
        logger.info("Rewrote follow-up %r as %r", corrected_question, search_question)

    # A jurisdiction named in the follow-up itself ("what about California?")
    # wins over one carried over from the previous question.
    jurisdiction = _detect_jurisdiction(corrected_question) or _detect_jurisdiction(search_question)

    try:
        if jurisdiction:
            chunks = hybrid_search(search_question, jurisdiction=jurisdiction, top_k=TOP_K)
        else:
            chunks = _balanced_search(search_question, TOP_K)
    except Exception:
        logger.exception("Retrieval failed for question %r; returning no chunks", search_question)
        chunks = []

    deadline_topic = None if _DEADLINE_KEYWORDS.search(search_question) else search_question
    deadlines = list_deadlines(topic=deadline_topic, jurisdiction=jurisdiction)

    typo_note = None
    if typo_corrections:
        interpreted = "; ".join(f"interpreted '{original}' as '{fixed}'" for original, fixed in typo_corrections)
        typo_note = f"I {interpreted}."

    return {
        "search_query": search_question,
        "jurisdiction_filter": jurisdiction,
        "chunks": chunks,
        "deadlines": deadlines,
        "typo_note": typo_note,
    }
