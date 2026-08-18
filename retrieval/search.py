"""Hybrid retrieval over the verified corpus: BM25 (tsvector) + vector search
(pgvector cosine similarity), fused with Reciprocal Rank Fusion (RRF).

Per CLAUDE.md, hybrid retrieval is first-class -- BM25 and vector search are
both primary, run side by side rather than one as a fallback for the other.
"""

from __future__ import annotations

import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import psycopg
from pgvector.psycopg import register_vector

from ingestion.embed import embed_text

DB_DSN = os.environ.get("DATABASE_URL", "postgresql://battery_reg:battery_reg@localhost:5432/battery_reg")

RRF_K = 60  # standard RRF damping constant

_CHUNK_COLUMNS = """
    id, jurisdiction, instrument, instrument_short, section_ref, section_title,
    parent_context, text, url, version_date, source_type
"""

BM25_SQL = f"""
    SELECT {_CHUNK_COLUMNS},
           ts_rank(content_tsv, to_tsquery('english', %(query)s)) AS score
    FROM chunks
    WHERE content_tsv @@ to_tsquery('english', %(query)s)
      AND (%(jurisdiction)s::text IS NULL OR jurisdiction = %(jurisdiction)s::text)
    ORDER BY score DESC
    LIMIT %(limit)s
"""

_TSQUERY_TOKEN = re.compile(r"\w+")


def _to_bm25_tsquery(query: str) -> str | None:
    """Build an OR'd tsquery from a natural-language query.

    websearch_to_tsquery ANDs every term by default, so BM25 returns zero
    rows unless a single chunk contains literally every query word -- exactly
    the case vector search exists to cover (e.g. a chunk about "recycled
    content" that never uses the word "threshold"). ORing terms instead lets
    ts_rank surface partial matches too, so BM25 keeps contributing candidates
    for RRF to fuse alongside vector search.
    """
    tokens = _TSQUERY_TOKEN.findall(query)
    return " | ".join(tokens) if tokens else None

VECTOR_SQL = f"""
    SELECT {_CHUNK_COLUMNS},
           1 - (embedding <=> %(embedding)s::vector) AS score
    FROM chunks
    WHERE embedding IS NOT NULL
      AND (%(jurisdiction)s::text IS NULL OR jurisdiction = %(jurisdiction)s::text)
    ORDER BY embedding <=> %(embedding)s::vector
    LIMIT %(limit)s
"""

# Chunks have no explicit paragraph-sequence column, so ctid (physical row
# order) is the best available proxy for original paragraph order on a
# freshly-loaded table -- see ingestion/load.py, which inserts in parser order.
GET_SECTION_SQL = f"""
    SELECT {_CHUNK_COLUMNS}
    FROM chunks
    WHERE instrument = %(instrument)s AND section_ref = %(section_ref)s
    ORDER BY ctid
"""


def _row_to_dict(cur, row) -> dict[str, Any]:
    columns = [desc[0] for desc in cur.description]
    return dict(zip(columns, row))


def _run_bm25(dsn: str, query: str, jurisdiction: str | None, limit: int) -> list[dict[str, Any]]:
    tsquery = _to_bm25_tsquery(query)
    if tsquery is None:
        return []
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(BM25_SQL, {"query": tsquery, "jurisdiction": jurisdiction, "limit": limit})
            return [_row_to_dict(cur, row) for row in cur.fetchall()]


def _run_vector(dsn: str, query_embedding: list[float], jurisdiction: str | None, limit: int) -> list[dict[str, Any]]:
    with psycopg.connect(dsn) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute(VECTOR_SQL, {"embedding": query_embedding, "jurisdiction": jurisdiction, "limit": limit})
            return [_row_to_dict(cur, row) for row in cur.fetchall()]


def _reciprocal_rank_fusion(result_lists: list[list[dict[str, Any]]], k: int = RRF_K) -> list[dict[str, Any]]:
    """Merge multiple ranked result lists into one, scored by sum of 1/(k + rank).

    A chunk found by both BM25 and vector search accumulates a score from
    each list, so it naturally outranks a chunk found by only one method.
    """
    chunks_by_id: dict[Any, dict[str, Any]] = {}
    rrf_scores: dict[Any, float] = {}

    for results in result_lists:
        for rank, row in enumerate(results, start=1):
            chunk_id = row["id"]
            chunks_by_id.setdefault(chunk_id, row)
            rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0.0) + 1.0 / (k + rank)

    ranked_ids = sorted(rrf_scores, key=lambda cid: rrf_scores[cid], reverse=True)
    ranked = []
    for chunk_id in ranked_ids:
        row = dict(chunks_by_id[chunk_id])
        row["rrf_score"] = rrf_scores[chunk_id]
        ranked.append(row)
    return ranked


def hybrid_search(
    query: str,
    jurisdiction: str | None = None,
    top_k: int = 10,
    dsn: str = DB_DSN,
) -> list[dict[str, Any]]:
    """Hybrid BM25 + vector search over the verified corpus, fused with RRF.

    Both searches run concurrently (separate connections/threads) since
    they're independent, network-bound queries.
    """
    query_embedding = embed_text(query)
    candidate_limit = max(top_k * 4, 20)  # widen the pool so RRF has enough signal to fuse

    with ThreadPoolExecutor(max_workers=2) as executor:
        bm25_future = executor.submit(_run_bm25, dsn, query, jurisdiction, candidate_limit)
        vector_future = executor.submit(_run_vector, dsn, query_embedding, jurisdiction, candidate_limit)
        bm25_results = bm25_future.result()
        vector_results = vector_future.result()

    fused = _reciprocal_rank_fusion([bm25_results, vector_results])
    return fused[:top_k]


def list_jurisdictions(dsn: str = DB_DSN) -> list[str]:
    """Distinct jurisdictions currently present in the corpus.

    Used to fan a jurisdiction-less query out across every jurisdiction that
    actually exists, rather than hardcoding "EU" and "US" -- a new
    jurisdiction's chunks start showing up in general-question results as
    soon as they're ingested, no code change required.
    """
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT jurisdiction FROM chunks ORDER BY jurisdiction")
            return [row[0] for row in cur.fetchall()]


def get_section(instrument: str, section_ref: str, dsn: str = DB_DSN) -> dict[str, Any] | None:
    """Exact lookup for the full text of a specific article/section.

    Long articles/sections are split into multiple chunks at ingestion time,
    each carrying a repeated header (chapter/article or part/section line).
    This reassembles them into one flowing text with the header kept once.
    """
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(GET_SECTION_SQL, {"instrument": instrument, "section_ref": section_ref})
            rows = [_row_to_dict(cur, row) for row in cur.fetchall()]

    if not rows:
        return None

    body_parts = []
    for i, row in enumerate(rows):
        text = row["text"]
        if i > 0 and "\n\n" in text:
            text = text.split("\n\n", 1)[1]  # drop the repeated header on continuation chunks
        body_parts.append(text)

    section = dict(rows[0])
    section["text"] = "\n\n".join(body_parts)
    section["chunk_count"] = len(rows)
    return section


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    test_queries = [
        "carbon footprint declaration requirements",
        "battery passport",
        "universal waste batteries",
        "lithium battery transport packaging",
        "recycled content thresholds",
    ]

    for query in test_queries:
        print(f"=== Query: {query!r} ===")
        results = hybrid_search(query, top_k=5)
        if not results:
            print("  (no results)")
        for rank, row in enumerate(results, start=1):
            preview = row["text"].replace("\n", " ").strip()[:100]
            print(
                f"{rank}. [{row['jurisdiction']}] {row['instrument']} {row['section_ref']} "
                f"- {row['section_title']!r} (rrf={row['rrf_score']:.4f})"
            )
            print(f"   {preview}...")
        print()
