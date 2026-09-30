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
from retrieval.search import get_section_chunks, hybrid_search, list_jurisdictions

logger = logging.getLogger(__name__)

TOP_K = 5
MARKET_ACCESS_TOP_K = 15  # coverage matters more than brevity for "what do I need to sell..."
CHUNKS_PER_OBLIGATION_AREA = 2
MAX_CHUNKS_PER_SECTION = 2  # so one long, many-chunk section can't fill every slot

# Explicit selling / market-entry phrasing.
_MARKET_ACCESS = re.compile(
    "|".join(
        [
            r"what do (i|we) need to sell",
            r"commerciali[sz]",
            r"\bplac(e[sd]?|ing)\b[^.?!]{0,80}?\bon the (\w+ )?market",
            r"\blaunch",
            r"\bexport(ing|s)? to\b",
            r"\b(sell|sells|selling|sold) (\w+ ){0,4}(in|into)\b",
            r"\bsuppl(y|ies|ying)\b[^.?!]{0,60}?\bto\b",
            r"\bshipping to\b",
            r"\bbring(ing)? (\w+ ){0,3}to (the )?market",
            r"\benter(ing)? the (\w+ )?market",
            r"\bmanufacturers? (\w+ ){0,2}selling",
            r"market (my|our) batter",
        ]
    ),
    re.IGNORECASE,
)

# A battery category plus a target market ("portable batteries for the EU
# market", "EV batteries sold in the EU and US") is market access too, even
# without a selling verb. The market has to be a *destination* ("for/into/to/
# in/across the EU", "EU market"), so lookups that merely name the regulation
# ("EV batteries under the EU Battery Regulation") don't qualify.
_BATTERY_TYPE = re.compile(
    r"\b(portable|LMT|e-?bikes?|e-?scooters?|industrial|EVs?|electric vehicles?|SLI|stationary|"
    r"energy storage|BESS|battery (packs?|cells?|modules?))\b",
    re.IGNORECASE,
)
# Waste-handling *activity*, not just a mention of end-of-life: "from
# manufacturing through end-of-life" is still a product lifecycle question.
_END_OF_LIFE = re.compile(
    r"\b(recycling (facility|plant|business|operation|company)|recyclers?|dispos(e|ing|al) of|"
    r"waste batteries|take-back|collection scheme)\b",
    re.IGNORECASE,
)
_TARGET_MARKET = re.compile(
    r"\b(for|into|to|in|across|within) (the )?(EU|European Union|Europe|US|U\.S\.|USA|United States|"
    r"California|Washington|New Jersey|Illinois)\b|\b(EU|US|European|American|global) market\b"
)

# Checklist of obligation areas for market-access questions: each is searched
# separately so an answer covers every area, not just whichever ones happen
# to rank highest for the question's wording. Queries are phrased the way
# the regulation itself words each area (tuned against the corpus -- e.g.
# plain "restrictions on substances" ranks Article 86's restriction
# *procedure* above Article 6's actual restrictions). An area with several
# queries takes the best chunk from each.
_OBLIGATION_AREAS: dict[str, tuple[str, ...]] = {
    "substance restrictions": ("batteries shall not contain substances restricted in Annex I",),
    "carbon footprint": ("carbon footprint declaration of batteries",),
    "recycled content": ("recycled content in industrial, SLI and electric vehicle batteries",),
    "performance and durability": ("electrochemical performance and durability requirements",),
    "removability and replaceability": ("removability and replaceability of portable and LMT batteries",),
    "labelling and marking": ("labelling and marking of batteries information requirements",),
    "battery passport": ("battery passport electronic record",),
    "conformity assessment and CE marking": (
        "conformity assessment procedures for batteries",
        "EU declaration of conformity CE marking",
    ),
    "due diligence": ("economic operators placing batteries on the market battery due diligence obligations",),
    "producer registration and EPR": ("producer registration extended producer responsibility",),
}
_AREA_CANDIDATES_PER_QUERY = 4

INSTRUMENT_EU = "Regulation (EU) 2023/1542"
INSTRUMENT_UWR = "40 CFR Part 273"

# Role detection: who the user is decides which obligations articles apply,
# however they phrase the question. Each role maps to the provisions written
# for that role -- Chapter VI of Regulation (EU) 2023/1542 (Articles 38-46,
# obligations of economic operators) plus the role articles in Chapter VIII
# (62 distributors, 64 end-users, 65 treatment operators), and the role
# subparts of 40 CFR Part 273 (B small / C large quantity handlers,
# E destination facilities, F imports). Those sections are fetched directly,
# not searched for, so a detected role always brings its article.
#
# Patterns take explicit mentions ("I'm an importer") and implicit signals
# ("we bring batteries in from China", "my warehouse stores and dispatches",
# "my shop sells").
_ROLES: dict[str, tuple[re.Pattern[str], tuple[tuple[str, str, str], ...]]] = {
    "manufacturer": (
        re.compile(
            r"\bmanufacturers?\b|\b(I|we) (manufacture|make|produce|build|assemble|develop|design)\b|"
            # ...but "building a battery recycling facility" is not making batteries.
            r"\b(manufacturing|producing|assembling|developing|designing|building) (\w+ ){0,4}batter(y|ies)\b"
            r"(?! (recycling|collection|treatment|charging|swap|storage (facility|site|room)))|"
            r"\b(my|our) (factory|plant|production line)\b|\bbattery (maker|producer)s?\b",
            re.IGNORECASE,
        ),
        (("EU", INSTRUMENT_EU, "Article 38"),),
    ),
    "cell or module supplier": (
        re.compile(r"\bsuppl(y|ies|ier|iers|ying)\b[^.?!]{0,30}\b(cells?|modules?)\b|\b(cell|module) suppliers?\b", re.IGNORECASE),
        (("EU", INSTRUMENT_EU, "Article 39"),),
    ),
    "authorised representative": (
        re.compile(
            r"\bauthori[sz]ed representatives?\b|\b(EU|European|Union) representatives?\b|"
            r"\brepresentatives? (in|for) the (EU|Union)\b|\bwritten mandate\b",
            re.IGNORECASE,
        ),
        (("EU", INSTRUMENT_EU, "Article 40"),),
    ),
    "importer": (
        re.compile(
            r"\bimport(s|er|ers|ing|ed)?\b|"
            r"\bbring(s|ing)?\b[^.?!]{0,40}\b(in|into)\b[^.?!]{0,30}\bfrom\b|"
            r"\b(sourc|buy|buying|purchas)\w*\b[^.?!]{0,40}\bfrom (China|Korea|Japan|Taiwan|India|Vietnam|abroad|overseas|outside the (EU|Union))\b|"
            r"\bfrom (China|Korea|Japan|Taiwan|India|Vietnam|abroad|overseas|outside the (EU|Union))\b[^.?!]{0,60}\b(sell|into|to the EU|in the EU)",
            re.IGNORECASE,
        ),
        (("EU", INSTRUMENT_EU, "Article 41"), ("US-federal", INSTRUMENT_UWR, "§ 273.70")),
    ),
    "distributor or retailer": (
        re.compile(
            r"\bdistribut(or|ors|e|es|ing)\b|\bretail(er|ers|ing)?\b|\bresell\w*|\bwholesal\w*|"
            r"\b(my|our) (shop|store|outlet)s?\b|\b(shop|store)\b[^.?!]{0,40}\bsell\w*|\bsell\w*\b[^.?!]{0,40}\b(shop|store)\b|"
            r"\bonline (shop|store|marketplace)\b",
            re.IGNORECASE,
        ),
        (("EU", INSTRUMENT_EU, "Article 42"), ("EU", INSTRUMENT_EU, "Article 62")),
    ),
    "fulfilment service provider": (
        re.compile(
            r"\bfulfil+ment\b|\bwarehous\w*|\bdispatch\w*|\b(pack|packs|packing)\b[^.?!]{0,40}\b(ship|send|deliver)\w*|"
            r"\blogistics (provider|company|service|business)\b|\b3PL\b",
            re.IGNORECASE,
        ),
        (("EU", INSTRUMENT_EU, "Article 43"),),
    ),
    "own-brand or modifying importer/distributor": (
        re.compile(
            r"\b(own|private|white)[- ](brand|label)\w*|\bown (name|trademark)\b|\brebrand\w*|"
            r"\bunder (our|my|their) (own )?(name|brand|trademark)\b|\bmodif(y|ies|ied|ying)\b[^.?!]{0,40}\b(batter|packs?|cells?)",
            re.IGNORECASE,
        ),
        (("EU", INSTRUMENT_EU, "Article 44"), ("EU", INSTRUMENT_EU, "Article 38")),
    ),
    "repurposer or remanufacturer": (
        re.compile(
            r"\brepurpos\w*|\bremanufactur\w*|\bsecond[- ]life\b|\brefurbish\w*|\bprepar\w* for re-?use\b|\bre-?us(e|ing) (used|old|waste)",
            re.IGNORECASE,
        ),
        (("EU", INSTRUMENT_EU, "Article 45"),),
    ),
    "recycler or treatment operator": (
        re.compile(
            r"\brecyclers?\b|\b(recycling|treatment) (facilit\w*|plant|operation|business|company|operators?)\b|"
            r"\b(run|operate|build|building|set up|open)\w*\b[^.?!]{0,30}\brecycling\b|\bprocess\w*\b[^.?!]{0,40}\bwaste batter",
            re.IGNORECASE,
        ),
        (("EU", INSTRUMENT_EU, "Article 65"), ("US-federal", INSTRUMENT_UWR, "§ 273.60")),
    ),
    "waste handler": (
        re.compile(
            r"\bwaste handlers?\b|\buniversal waste\b|\bhazardous waste\b|"
            r"\b(collect|collects|collecting|store|stores|storing|keep|keeps|keeping|accumulat\w*|handl\w*|hold|holding)\b[^.?!]{0,40}\b(old|used|spent|waste|dead|damaged|scrap)\b[^.?!]{0,20}\bbatter",
            re.IGNORECASE,
        ),
        (("US-federal", INSTRUMENT_UWR, "§ 273.13"), ("US-federal", INSTRUMENT_UWR, "§ 273.33")),
    ),
    "end user": (
        re.compile(
            r"\bend[- ]users?\b|\bconsumers?\b(?! (electronics|batteries|products|goods|devices))|\bhouseholds?\b|\bat home\b|"
            r"\bI (own|have|bought|use)\b[^.?!]{0,20}\b(a|an|my|some)\b",
            re.IGNORECASE,
        ),
        (("EU", INSTRUMENT_EU, "Article 64"), ("US-federal", INSTRUMENT_UWR, "§ 273.8")),
    ),
}
MAX_CHUNKS_PER_ROLE_SECTION = 2
SECTIONS_PER_ACTIVITY_QUERY = 2

# Activity-based coverage, the second signal: questions about transport,
# waste handling, second life, recycling and imports use everyday wording
# ("outside the EU", "repurpose", "leaked") that ranks recitals above the
# operative provisions ("outside the Union", "preparation for repurposing",
# "releases"). Each activity has broad triggers (synonyms and related
# concepts) and several targeted queries phrased the way the provisions
# are, tagged with the jurisdiction they target.
SITUATION_TOP_K = 15
# Role/activity coverage adds up to this many chunks on top of the base
# results (e.g. a 15-chunk market-access search) instead of displacing them.
ROLE_ACTIVITY_EXTRA_CHUNKS = 5
_SITUATIONS: dict[str, tuple[re.Pattern[str], tuple[tuple[str, str], ...]]] = {
    "transport": (
        re.compile(
            r"\b(ship|ships|shipping|shipped|transport\w*|carriers?|carriage|freight|couriers?|haul\w*|deliver\w*|"
            r"send\w* (\w+ ){0,3}(abroad|overseas)|by (road|air|sea|rail)|air cargo)\b",
            re.IGNORECASE,
        ),
        (
            ("EU", "storage or transport conditions do not jeopardise its compliance"),
            ("US-federal", "lithium cells and batteries classification packaging transport"),
            ("US-federal", "off-site shipments of universal waste"),
        ),
    ),
    "waste shipment": (
        re.compile(
            r"\b(ship\w*|export\w*|send\w*|transfer\w*)\b[^.?!]{0,60}\b(waste|old|used|spent|scrap)\b|"
            r"\b(waste|old|used|spent|scrap)\b[^.?!]{0,60}\b(outside|abroad|overseas|foreign|third countr\w*|export\w*)",
            re.IGNORECASE,
        ),
        (
            ("EU", "shipment of waste batteries outside the Union"),
            ("US-federal", "exports of universal waste to a foreign destination"),
        ),
    ),
    "second life": (
        re.compile(
            r"\b(repurpos\w*|second[- ]life|second use|re-?us(e|ed|ing)|remanufactur\w*|refurbish\w*|recondition\w*|repair\w*)\b",
            re.IGNORECASE,
        ),
        (
            ("EU", "preparation for re-use repurposing remanufacturing of batteries obligations"),
            ("EU", "repurposing waste electric vehicle batteries second life"),
        ),
    ),
    "recycling and treatment": (
        re.compile(
            # "recycled content" is a product requirement, not a recycling activity.
            r"\brecycl(e|es|ed|ing|er|ers)?\b(?! content)|\btreatment\b|\brecover\w* (of )?(materials|lithium|cobalt|nickel)|\bshredd\w*|\bblack mass\b|\bdismantl\w*",
            re.IGNORECASE,
        ),
        (
            ("EU", "obligations of operators of treatment facilities"),
            ("EU", "treatment of waste batteries removal of all fluids and acids"),
            ("EU", "treatment and recycling efficiency targets recovery of materials"),
            ("US-federal", "destination facility universal waste recycling"),
        ),
    ),
    "waste handling": (
        re.compile(
            r"\b(dispos\w*|end-of-life|spent|take-back|take back|collection|collect\w*|hazardous waste|waste batter\w*|"
            r"leak\w*|spill\w*|damaged|defective|releases?|released|accumulat\w*)\b|"
            r"\b(stor(e|es|ed|ing|age)|keep(s|ing)?|kept|export\w*)\b[^.?!]{0,40}\b(waste|old|used|spent|dead|damaged)\b|"
            r"\b(waste|old|used|spent|dead|damaged) batter\w*[^.?!]{0,40}\b(stor(e|es|ed|ing|age)|keep(s|ing)?|kept|export\w*)",
            re.IGNORECASE,
        ),
        (
            ("EU", "collection of waste batteries producers obligations"),
            ("EU", "treatment of waste batteries removal of all fluids and acids"),
            ("US-federal", "universal waste battery management containment of leaking or damaged batteries"),
            ("US-federal", "response to releases of universal waste"),
            ("US-federal", "accumulation time limits for universal waste"),
            ("US-federal", "labeling and marking of universal waste batteries"),
            ("US-federal", "off-site shipments of universal waste"),
            ("US-federal", "exports of universal waste to a foreign destination"),
        ),
    ),
    "imports": (
        re.compile(r"\bimport\w*\b", re.IGNORECASE),
        (
            ("EU", "obligations of importers"),
            ("US-federal", "imports of universal waste from a foreign country"),
        ),
    ),
}

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


# Whole-word patterns: plain substring matching found "epa" in "separate",
# "dot" in "anecdote" and "eu" in "neutral". Acronyms that collide with
# ordinary words ("US" vs "us", "DOT", "EPA") are matched case-sensitively;
# everything else ignores case.
_JURISDICTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "EU": re.compile(r"(?i:\bEU\b|\beuropean union\b|\beurope(an)?\b)"),
    "US-federal": re.compile(
        r"\bUS\b|\bU\.S\.|\bUSA\b|\bDOT\b|\bEPA\b|\bPHMSA\b|(?i:\bunited states\b|\bfederal\b)"
    ),
    "US-CA": re.compile(r"(?i:\bcalifornia\b)"),
    "US-WA": re.compile(r"(?i:\bwashington\b)"),
    "US-NJ": re.compile(r"(?i:\bnew jersey\b)"),
    "US-IL": re.compile(r"(?i:\billinois\b)"),
}


def _detect_jurisdiction(question: str) -> str | None:
    """Return a single jurisdiction filter only when exactly one is unambiguously named.

    Any other case (none named, or several named, e.g. "selling in the EU
    and US") is left unfiltered so retrieval covers the whole corpus rather
    than risking an over-narrow filter on a mixed-jurisdiction question.
    """
    matched = [code for code, pattern in _JURISDICTION_PATTERNS.items() if pattern.search(question)]
    return matched[0] if len(matched) == 1 else None


def _searchable_jurisdiction(jurisdiction: str | None) -> str | None:
    """Map a detected jurisdiction onto one the corpus actually has chunks for.

    US states have no ingested laws yet, so filtering to "US-CA" would return
    nothing at all; searching US federal instead still surfaces the federal
    rules that apply in every state. Anything else unknown is left unfiltered.
    """
    if jurisdiction is None:
        return None
    available = set(list_jurisdictions())
    if jurisdiction in available:
        return jurisdiction
    if jurisdiction.startswith("US-") and "US-federal" in available:
        return "US-federal"
    return None


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
        return _diverse_search(question, None, top_k)

    per_jurisdiction_k = max(1, math.ceil(top_k / len(jurisdictions)))
    with ThreadPoolExecutor(max_workers=len(jurisdictions)) as executor:
        futures = [executor.submit(_diverse_search, question, j, per_jurisdiction_k) for j in jurisdictions]
        by_jurisdiction = [future.result() for future in futures]

    return _interleave(by_jurisdiction)[:top_k]


def _diverse_search(question: str, jurisdiction: str | None, top_k: int) -> list[dict[str, Any]]:
    """hybrid_search, capped at MAX_CHUNKS_PER_SECTION chunks per section.

    Long sections are split into many chunks (§ 173.185 has 9), and without
    a cap they can fill every slot -- a US lifecycle question came back as
    five pieces of § 173.185 and nothing from Part 273. Over-fetching and
    capping keeps the best chunks while leaving room for other sections.
    """
    candidates = hybrid_search(question, jurisdiction=jurisdiction, top_k=top_k * 3)
    per_section: dict[tuple[str, str], int] = {}
    selected: list[dict[str, Any]] = []
    for chunk in candidates:
        key = (chunk["instrument"], chunk["section_ref"])
        if per_section.get(key, 0) >= MAX_CHUNKS_PER_SECTION:
            continue
        per_section[key] = per_section.get(key, 0) + 1
        selected.append(chunk)
        if len(selected) == top_k:
            break
    return selected


def _is_market_access(question: str) -> bool:
    if _MARKET_ACCESS.search(question):
        return True
    # A battery type + market that's about waste handling ("recycling facility
    # for EV batteries in the EU") needs end-of-life provisions, not the
    # product-placement checklist.
    if _END_OF_LIFE.search(question):
        return False
    return bool(_BATTERY_TYPE.search(question) and _TARGET_MARKET.search(question))


def _obligation_area_search(question: str, jurisdiction: str | None) -> list[dict[str, Any]]:
    """Targeted retrieval across every obligation area, merged with the question's own search.

    Each area keeps its top CHUNKS_PER_OBLIGATION_AREA chunks, preferring
    articles/sections over recitals (recitals are interpretive context, not
    obligations). Order of priority when filling MARKET_ACCESS_TOP_K: the
    best chunk from each area (so every area is represented), then the
    question's own article/section hits (whatever is specific to its
    wording), then each area's second chunk, then the question's recital
    hits. Duplicates are dropped by id.
    """
    with ThreadPoolExecutor(max_workers=8) as executor:
        area_futures = {
            area: [executor.submit(hybrid_search, query, jurisdiction, _AREA_CANDIDATES_PER_QUERY) for query in queries]
            for area, queries in _OBLIGATION_AREAS.items()
        }
        if jurisdiction:
            question_future = executor.submit(_diverse_search, question, jurisdiction, TOP_K)
        else:
            question_future = executor.submit(_balanced_search, question, TOP_K)

        by_area: list[list[dict[str, Any]]] = []
        for area, futures in area_futures.items():
            try:
                candidates = _interleave([future.result() for future in futures])
            except Exception:
                # One failing area shouldn't cost the answer its other areas.
                logger.exception("Obligation-area search failed for %r", area)
                candidates = []
            candidates.sort(key=_is_recital)  # stable: articles first
            unique = list({chunk["id"]: chunk for chunk in reversed(candidates)}.values())[::-1]
            by_area.append(unique[:CHUNKS_PER_OBLIGATION_AREA])
        question_hits = question_future.result()

    firsts = [chunks[0] for chunks in by_area if chunks]
    rest = [chunk for chunks in by_area for chunk in chunks[1:]]
    question_provisions = [c for c in question_hits if not _is_recital(c)]
    question_recitals = [c for c in question_hits if _is_recital(c)]
    return _merge_unique([*firsts, *question_provisions, *rest, *question_recitals], MARKET_ACCESS_TOP_K)


def _is_recital(chunk: dict[str, Any]) -> bool:
    return chunk["section_ref"].startswith("Recital")


def _merge_unique(chunks: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """First occurrence of each chunk id, in the given priority order, up to `limit`."""
    merged: list[dict[str, Any]] = []
    seen_ids: set[Any] = set()
    for chunk in chunks:
        if chunk["id"] in seen_ids:
            continue
        seen_ids.add(chunk["id"])
        merged.append(chunk)
    return merged[:limit]


def _roles_for(question: str) -> list[str]:
    return [name for name, (pattern, _) in _ROLES.items() if pattern.search(question)]


def _role_search(roles: list[str], question: str, jurisdiction: str | None) -> list[dict[str, Any]]:
    """The obligations provisions for each detected role, fetched directly.

    Long articles (Article 38 has 11 chunks) keep the MAX_CHUNKS_PER_ROLE_SECTION
    chunks sharing the most terms with the question, so the part of the
    article that answers it comes along rather than just its opening.
    """
    targets = list(
        dict.fromkeys(
            (instrument, section_ref)
            for role in roles
            for target_jurisdiction, instrument, section_ref in _ROLES[role][1]
            if jurisdiction is None or jurisdiction == target_jurisdiction
        )
    )
    if not targets:
        return []

    question_terms = {_normalize(term) for term in _key_terms(question)}

    def overlap(chunk: dict[str, Any]) -> int:
        chunk_terms = {_normalize(word) for word in re.findall(r"[A-Za-z]{3,}", chunk["text"])}
        return len(question_terms & chunk_terms)

    selected: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(8, len(targets))) as executor:
        futures = [executor.submit(get_section_chunks, instrument, section_ref) for instrument, section_ref in targets]
        for (_, section_ref), future in zip(targets, futures):
            try:
                chunks = future.result()
            except Exception:
                logger.exception("Role section lookup failed for %r", section_ref)
                continue
            ranked = sorted(chunks, key=overlap, reverse=True)  # stable: ties keep document order
            selected.extend(ranked[:MAX_CHUNKS_PER_ROLE_SECTION])
    return selected


def _situations_for(question: str) -> list[str]:
    return [name for name, (pattern, _) in _SITUATIONS.items() if pattern.search(question)]


def _situation_search(situations: list[str], jurisdiction: str | None) -> list[list[dict[str, Any]]]:
    """One ranked stream of chunks per matched activity, for round-robin merging.

    Each targeted query contributes its top SECTIONS_PER_ACTIVITY_QUERY
    distinct sections (articles/sections before recitals, as in the
    obligation-area search): the operative provision often ranks second
    behind a related one, e.g. Article 70 (treatment) behind Article 74
    (information on waste management). A query only runs when its
    jurisdiction fits the question's -- an EU-only question skips the US
    queries and vice versa.
    """
    per_activity = [
        [
            (query_jurisdiction, query)
            for query_jurisdiction, query in _SITUATIONS[name][1]
            if jurisdiction is None or jurisdiction == query_jurisdiction
        ]
        for name in situations
    ]
    queries = list(dict.fromkeys(q for activity in per_activity for q in activity))
    if not queries:
        return []

    top_sections: dict[tuple[str, str], list[dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=min(8, len(queries))) as executor:
        futures = {q: executor.submit(hybrid_search, q[1], q[0], _AREA_CANDIDATES_PER_QUERY) for q in queries}
        for q, future in futures.items():
            try:
                ranked = sorted(future.result(), key=_is_recital)  # stable: articles first
            except Exception:
                logger.exception("Situation search failed for %r", q[1])
                ranked = []
            by_section: dict[str, dict[str, Any]] = {}
            for chunk in ranked:
                by_section.setdefault(chunk["section_ref"], chunk)
            top_sections[q] = list(by_section.values())[:SECTIONS_PER_ACTIVITY_QUERY]

    return [[chunk for q in activity for chunk in top_sections[q]] for activity in per_activity]


def retrieve(question: str, conversation_history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Gather evidence for `question`: ranked chunks, plus curated deadlines.

    Follow-up questions ("what about the deadlines for this?") are rewritten
    into standalone search queries using the previous user question from
    `conversation_history` -- see _rewrite_follow_up.

    Market-access questions ("what do I need to sell X in the EU?") search
    each obligation area separately and return up to MARKET_ACCESS_TOP_K
    chunks -- see _obligation_area_search.

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

    market_access = _is_market_access(search_question)

    try:
        jurisdiction = _searchable_jurisdiction(jurisdiction)
        # The obligation-area checklist mirrors the EU Battery Regulation's
        # structure; searching it under a US filter would return near-miss
        # matches, so other jurisdictions get a wider plain search instead.
        if market_access and jurisdiction in (None, "EU"):
            chunks = _obligation_area_search(search_question, jurisdiction)
        elif market_access:
            chunks = _diverse_search(search_question, jurisdiction, MARKET_ACCESS_TOP_K)
        elif jurisdiction:
            chunks = _diverse_search(search_question, jurisdiction, TOP_K)
        else:
            chunks = _balanced_search(search_question, TOP_K)
    except Exception:
        logger.exception("Retrieval failed for question %r; returning no chunks", search_question)
        chunks = []

    # Role and activity coverage go on top of whichever search ran: the
    # detected roles' own obligations provisions first (the most specific
    # signal), then the activity streams and the existing results merged
    # round-robin.
    roles = _roles_for(search_question)
    situations = _situations_for(search_question)
    if roles or situations:
        try:
            role_chunks = _role_search(roles, search_question, jurisdiction) if roles else []
            activity_streams = _situation_search(situations, jurisdiction) if situations else []
            # Round-robin across activities, with the base results as one more
            # stream, so a broad activity (many queries) can't crowd out the
            # others or the question's own search.
            chunks = _merge_unique(
                [*role_chunks, *_interleave([*activity_streams, chunks])],
                max(SITUATION_TOP_K, len(chunks) + ROLE_ACTIVITY_EXTRA_CHUNKS),
            )
        except Exception:
            logger.exception("Role/situation search failed for question %r; keeping base results", search_question)

    # Market-access questions get the full deadline table (sorted by urgency):
    # the answer is a roadmap across every obligation area, not one topic.
    deadline_topic = None if market_access or _DEADLINE_KEYWORDS.search(search_question) else search_question
    deadlines = list_deadlines(topic=deadline_topic, jurisdiction=jurisdiction)

    typo_note = None
    if typo_corrections:
        interpreted = "; ".join(f"interpreted '{original}' as '{fixed}'" for original, fixed in typo_corrections)
        typo_note = f"I {interpreted}."

    return {
        "search_query": search_question,
        "market_access": market_access,
        "roles": roles,
        "situations": situations,
        "jurisdiction_filter": jurisdiction,
        "chunks": chunks,
        "deadlines": deadlines,
        "typo_note": typo_note,
    }
