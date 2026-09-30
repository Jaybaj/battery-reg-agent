"""Eval runner for the golden set (evals/golden_set.jsonl).

Runs each question through the agent and scores it on four criteria:

  citation       -- retrieval: recall of expected_sections among the chunks
                    the answer was grounded on (pass = all retrieved), plus
                    precision (share of distinct retrieved sections that
                    were expected; informational, since retrieval is meant
                    to over-fetch related provisions).
  content        -- share of expected_answer_contains strings found in the
                    answer (case- and whitespace-insensitive substring).
  hallucination  -- every Article / § cited in the answer text must exist in
                    the corpus. References to other instruments ("Article 3
                    of Directive 2008/98/EC") and annexes are excluded.
                    Also reports "ungrounded" refs: real, but not in the
                    reference material the model was given.
  contract       -- the answer contract (regulations, guidance, deadlines,
                    caveats, disclaimer) plus the tone rules (no restating
                    opener, no meta-labels, no retrieval talk, no URLs, no
                    em/en dashes).

If generation fails (e.g. no LLM API key), citation is still scored from the
retrieval step -- the same deterministic retrieve() call run_agent makes --
and the three answer-based criteria are recorded as skipped, not failed.

Usage:
    python -m evals.run_evals                  # all questions
    python -m evals.run_evals --sample 5       # 5 questions, fixed random sample
    python -m evals.run_evals --retrieval-only # citation scoring only, no LLM calls
    python -m evals.run_evals --dataset holdout  # held-out set (never used for tuning)
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg

from agent.orchestrator import FALLBACK_MESSAGE, run_agent
from agent.retriever import retrieve
from retrieval.search import DB_DSN

EVALS_DIR = Path(__file__).resolve().parent
GOLDEN_SET = EVALS_DIR / "golden_set.jsonl"
# The holdout set is for measuring generalisation: retrieval is tuned
# against the golden set, never against these questions.
DATASETS = {"golden": GOLDEN_SET, "holdout": EVALS_DIR / "holdout_set.jsonl"}

CITATION_RECALL_PASS = 1.0  # every expected section must be retrieved
CONTENT_PASS = 0.75  # share of expected strings that must appear
WORST_N = 5

CRITERIA = ("citation", "content", "hallucination", "contract")


# --------------------------------------------------------------------------- helpers


def _normalize_ref(ref: str) -> str:
    return " ".join(ref.replace("§", "§").split())


def _normalize_text(text: str) -> str:
    # Curly quotes/apostrophes and odd spaces shouldn't decide a substring match.
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return " ".join(text.lower().split())


def load_golden_set(path: Path = GOLDEN_SET) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_corpus_refs(dsn: str = DB_DSN) -> dict[str, set[str]]:
    """Distinct section_refs per jurisdiction group ("EU", "US") in the corpus."""
    refs: dict[str, set[str]] = {"EU": set(), "US": set()}
    with psycopg.connect(dsn) as conn:
        for jurisdiction, section_ref in conn.execute("SELECT DISTINCT jurisdiction, section_ref FROM chunks"):
            group = "US" if jurisdiction.startswith("US") else "EU"
            refs[group].add(_normalize_ref(section_ref))
    return refs


# --------------------------------------------------------------------------- scoring


def score_citation(expected: list[str], chunks: list[dict[str, Any]]) -> dict[str, Any]:
    expected_refs = {_normalize_ref(ref) for ref in expected}
    retrieved = list(dict.fromkeys(_normalize_ref(chunk["section_ref"]) for chunk in chunks))
    hits = sorted(expected_refs & set(retrieved))
    recall = len(hits) / len(expected_refs) if expected_refs else 1.0
    precision = len([ref for ref in retrieved if ref in expected_refs]) / len(retrieved) if retrieved else 0.0
    return {
        "score": recall,
        "passed": recall >= CITATION_RECALL_PASS,
        "recall": round(recall, 3),
        "precision": round(precision, 3),
        "missing": sorted(expected_refs - set(retrieved)),
        "retrieved": retrieved,
    }


def score_content(expected: list[str], answer: str) -> dict[str, Any]:
    haystack = _normalize_text(answer)
    found = [s for s in expected if _normalize_text(s) in haystack]
    fraction = len(found) / len(expected) if expected else 1.0
    return {
        "score": fraction,
        "passed": fraction >= CONTENT_PASS,
        "found": found,
        "missing": [s for s in expected if s not in found],
    }


# "Article 7", "Article 7(1)(a)", "Articles 7 and 8", "Articles 47-53", "Articles 47 to 53"
_ARTICLE_LIST = re.compile(
    r"\bArticles?\s+(\d+[a-z]?(?:\s*\([^)]*\))*(?:\s*(?:,|and|or|to|through|-|–|—)\s*\d+[a-z]?(?:\s*\([^)]*\))*)*)",
)
_NUMBER_OR_RANGE = re.compile(r"(\d+)[a-z]?(?:\s*\([^)]*\))*(?:\s*(?:to|through|-|–|—)\s*(\d+))?")
# "§ 273.13", "§§ 273.13 and 273.33", "40 CFR 273.13", "49 CFR 173.185"
_SECTION_SIGN = re.compile(r"§§?\s*(\d+\.\d+(?:\s*(?:,|and|or)\s*\d+\.\d+)*)")
_CFR_SECTION = re.compile(r"\b\d+\s+CFR\s+(?:§\s*)?(\d+\.\d+)")
# A reference that belongs to another instrument, e.g. "Article 3 of Directive 2008/98/EC".
_OTHER_INSTRUMENT = re.compile(
    r"^\s*(?:\([^)]*\)\s*)*(?:of|in|under)\s+(?:the\s+)?(?:Directive|Decision|Regulation\s+\((?:EC|EEC)\)|"
    r"Regulation\s+(?!\(EU\)\s*2023/1542)\(EU\)|Commission|Council|Treaty|TFEU)",
    re.IGNORECASE,
)


def extract_cited_refs(answer: str) -> tuple[list[str], list[str]]:
    """(refs to check against the corpus, refs belonging to other instruments)."""
    refs: list[str] = []
    external: list[str] = []

    for match in _ARTICLE_LIST.finditer(answer):
        numbers: list[str] = []
        for number in _NUMBER_OR_RANGE.finditer(match.group(1)):
            start, end = int(number.group(1)), number.group(2)
            if end and int(end) > start and int(end) - start <= 50:
                numbers.extend(str(n) for n in range(start, int(end) + 1))
            else:
                numbers.append(str(start))
        target = external if _OTHER_INSTRUMENT.match(answer[match.end() : match.end() + 60]) else refs
        target.extend(f"Article {n}" for n in numbers)

    for match in _SECTION_SIGN.finditer(answer):
        refs.extend(f"§ {n}" for n in re.findall(r"\d+\.\d+", match.group(1)))
    for match in _CFR_SECTION.finditer(answer):
        refs.append(f"§ {match.group(1)}")

    return list(dict.fromkeys(refs)), list(dict.fromkeys(external))


def score_hallucination(answer: str, corpus_refs: dict[str, set[str]], chunks: list[dict[str, Any]]) -> dict[str, Any]:
    cited, external = extract_cited_refs(answer)
    all_refs = corpus_refs["EU"] | corpus_refs["US"]
    fabricated = [ref for ref in cited if ref not in all_refs]
    grounded_refs = {_normalize_ref(chunk["section_ref"]) for chunk in chunks}
    ungrounded = [ref for ref in cited if ref in all_refs and ref not in grounded_refs]
    return {
        "score": 0.0 if fabricated else 1.0,
        "passed": not fabricated,
        "cited": cited,
        "fabricated": fabricated,
        "ungrounded": ungrounded,
        "other_instruments": external,
    }


_CONTRACT_PARTS = {
    "regulations": re.compile(r"regulations? (that )?appl|applicable regulations?|what applies|which rules apply", re.I),
    "guidance": re.compile(r"what you need to do|what to do|steps?\b|how to comply|guidance|action", re.I),
    "deadlines": re.compile(r"deadlines?|timeline|key dates|in force|from \d{1,2} \w+ \d{4}", re.I),
    "caveats": re.compile(r"watch out|caveats?|keep in mind|be aware|not covered|verified (details|information)", re.I),
    "disclaimer": re.compile(r"not legal advice", re.I),
}
_TONE_RULES = {
    "restating_opener": re.compile(r"^\W*(you('| a)re asking|you want to know|you('| a)re looking into|you asked)", re.I),
    "meta_label_opener": re.compile(r"^\W*(short answer|in short|to summarize|tl;?dr)\b", re.I),
    "mentions_retrieval": re.compile(r"retrieved (context|chunks?)|reference material|what came back|chunks?\b", re.I),
    "contains_url": re.compile(r"https?://", re.I),
    "contains_dash": re.compile(r"[–—]|^\s*-{3,}\s*$", re.M),
}


def score_contract(answer: str) -> dict[str, Any]:
    missing = [part for part, pattern in _CONTRACT_PARTS.items() if not pattern.search(answer)]
    violations = [rule for rule, pattern in _TONE_RULES.items() if pattern.search(answer)]
    present = len(_CONTRACT_PARTS) - len(missing)
    return {
        "score": present / len(_CONTRACT_PARTS),
        "passed": not missing and not violations,
        "missing_parts": missing,
        "tone_violations": violations,
    }


def _skipped(reason: str) -> dict[str, Any]:
    return {"score": None, "passed": None, "skipped": reason}


# --------------------------------------------------------------------------- running


def evaluate_question(item: dict[str, Any], corpus_refs: dict[str, set[str]], retrieval_only: bool) -> dict[str, Any]:
    question = item["question"]
    started = time.monotonic()
    answer: str | None = None
    chunks: list[dict[str, Any]] = []
    generation_error: str | None = None

    if retrieval_only:
        generation_error = "retrieval-only run"
    else:
        # run_agent prints which model it's trying; keep that out of the report output.
        with contextlib.redirect_stdout(io.StringIO()):
            result = run_agent(question)
        if result["answer"] == FALLBACK_MESSAGE:
            generation_error = "generation failed (fallback answer) -- check LLM API keys"
        else:
            answer, chunks = result["answer"], result["chunks"]

    if answer is None:
        # run_agent drops chunks when generation fails; retrieve() is the same
        # deterministic step, so citation can still be scored.
        chunks = retrieve(question)["chunks"]

    scores = {"citation": score_citation(item["expected_sections"], chunks)}
    if answer is None:
        for criterion in ("content", "hallucination", "contract"):
            scores[criterion] = _skipped(generation_error or "no answer")
    else:
        scores["content"] = score_content(item["expected_answer_contains"], answer)
        scores["hallucination"] = score_hallucination(answer, corpus_refs, chunks)
        scores["contract"] = score_contract(answer)

    available = [s["score"] for s in scores.values() if s["score"] is not None]
    return {
        "question": question,
        "expected_mode": item.get("expected_mode"),
        "expected_sections": item["expected_sections"],
        "answer": answer,
        "generation_error": generation_error,
        "chunks_used": [
            {"jurisdiction": c["jurisdiction"], "instrument": c["instrument"], "section_ref": c["section_ref"]}
            for c in chunks
        ],
        "scores": scores,
        "overall": round(sum(available) / len(available), 3) if available else 0.0,
        "seconds": round(time.monotonic() - started, 1),
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for criterion in CRITERIA:
        scored = [r["scores"][criterion] for r in results if r["scores"][criterion]["passed"] is not None]
        summary[criterion] = {
            "scored": len(scored),
            "skipped": len(results) - len(scored),
            "pass_rate": round(sum(s["passed"] for s in scored) / len(scored), 3) if scored else None,
            "mean_score": round(sum(s["score"] for s in scored) / len(scored), 3) if scored else None,
        }
    citation = [r["scores"]["citation"] for r in results]
    summary["citation"]["mean_recall"] = round(sum(c["recall"] for c in citation) / len(citation), 3)
    summary["citation"]["mean_precision"] = round(sum(c["precision"] for c in citation) / len(citation), 3)
    summary["overall"] = round(sum(r["overall"] for r in results) / len(results), 3) if results else None
    return summary


def _problems(result: dict[str, Any]) -> list[str]:
    s = result["scores"]
    problems = []
    if s["citation"]["missing"]:
        problems.append(f"not retrieved: {', '.join(s['citation']['missing'])}")
    if s["content"].get("missing"):
        problems.append(f"answer lacks: {'; '.join(repr(m) for m in s['content']['missing'])}")
    if s["hallucination"].get("fabricated"):
        problems.append(f"fabricated refs: {', '.join(s['hallucination']['fabricated'])}")
    if s["contract"].get("missing_parts"):
        problems.append(f"contract missing: {', '.join(s['contract']['missing_parts'])}")
    if s["contract"].get("tone_violations"):
        problems.append(f"tone: {', '.join(s['contract']['tone_violations'])}")
    if result["generation_error"]:
        problems.append(result["generation_error"])
    return problems


def _fmt_rate(value: float | None) -> str:
    return "  n/a" if value is None else f"{value * 100:5.1f}%"


def print_report(results: list[dict[str, Any]], summary: dict[str, Any], out_path: Path) -> None:
    print()
    print(f"{'criterion':<15}{'pass rate':>10}{'mean':>9}{'scored':>8}{'skipped':>9}")
    print("-" * 51)
    for criterion in CRITERIA:
        row = summary[criterion]
        mean = "  n/a" if row["mean_score"] is None else f"{row['mean_score']:.2f}"
        print(f"{criterion:<15}{_fmt_rate(row['pass_rate']):>10}{mean:>9}{row['scored']:>8}{row['skipped']:>9}")
    print("-" * 51)
    print(
        f"{'overall':<15}{'':>10}{summary['overall']:>9.2f}"
        f"   (citation recall {summary['citation']['mean_recall']:.2f}, precision {summary['citation']['mean_precision']:.2f})"
    )

    worst = sorted(results, key=lambda r: r["overall"])[:WORST_N]
    print(f"\nWorst {len(worst)} questions:")
    for rank, result in enumerate(worst, start=1):
        print(f"\n{rank}. [{result['overall']:.2f}] {result['question']}")
        for problem in _problems(result) or ["(no issues flagged)"]:
            print(f"     - {problem}")

    print(f"\nDetailed report: {out_path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the golden-set evals.")
    parser.add_argument("--sample", type=int, metavar="N", help="run only N questions (fixed random sample)")
    parser.add_argument("--seed", type=int, default=0, help="seed for --sample (default 0, so runs are comparable)")
    parser.add_argument("--retrieval-only", action="store_true", help="score citation only; skip LLM calls")
    parser.add_argument(
        "--dataset",
        default="golden",
        help="'golden' (default), 'holdout', or a path to a .jsonl file in the same format",
    )
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    dataset_path = DATASETS.get(args.dataset, Path(args.dataset))
    golden = load_golden_set(dataset_path)
    indices = list(range(len(golden)))
    if args.sample and args.sample < len(golden):
        indices = sorted(random.Random(args.seed).sample(indices, args.sample))
    corpus_refs = load_corpus_refs()

    results = []
    for n, index in enumerate(indices, start=1):
        item = golden[index]
        print(f"[{n}/{len(indices)}] #{index + 1} {item['question'][:80]}", flush=True)
        result = evaluate_question(item, corpus_refs, args.retrieval_only)
        result["index"] = index + 1
        results.append(result)

    summary = summarize(results)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = EVALS_DIR / f"results_{dataset_path.stem}_{timestamp}.json"
    report = {
        "timestamp": timestamp,
        "args": vars(args),
        "thresholds": {"citation_recall": CITATION_RECALL_PASS, "content": CONTENT_PASS},
        "summary": summary,
        "results": results,
    }
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print_report(results, summary, out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
