"""Loads chunks from all jurisdiction parsers into the Postgres chunks table.

Connects to the Postgres instance defined in docker-compose.yml. Each chunk's
embedding is generated via ingestion/embed.py (sentence-transformers,
all-MiniLM-L6-v2) before insert.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import psycopg
from pgvector.psycopg import register_vector

from ingestion.embed import MODEL_NAME, embed_batch
from ingestion.parsers import ecfr, eur_lex

DB_DSN = os.environ.get("DATABASE_URL", "postgresql://battery_reg:battery_reg@localhost:5432/battery_reg")

INSERT_SQL = """
    INSERT INTO chunks (
        jurisdiction, instrument, instrument_short, section_ref, section_title,
        parent_context, text, url, version_date, source_type, embedding
    ) VALUES (
        %(jurisdiction)s, %(instrument)s, %(instrument_short)s, %(section_ref)s, %(section_title)s,
        %(parent_context)s, %(text)s, %(url)s, %(version_date)s, %(source_type)s, %(embedding)s
    )
"""

PARSERS = [eur_lex, ecfr]


def collect_chunks() -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for parser in PARSERS:
        chunks.extend(parser.run())
    return chunks


def load_chunks(chunks: list[dict[str, Any]], dsn: str = DB_DSN) -> int:
    """Replace the full contents of the chunks table with `chunks`.

    Truncates first so reruns (e.g. after a parser fix) don't duplicate rows --
    there's no natural unique key to upsert on across jurisdictions/instruments.
    """
    print(f"Embedding {len(chunks)} chunks with {MODEL_NAME}...")
    embeddings = embed_batch([chunk["text"] for chunk in chunks])
    rows = [{**chunk, "embedding": embedding} for chunk, embedding in zip(chunks, embeddings)]

    with psycopg.connect(dsn) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE chunks")
            cur.executemany(INSERT_SQL, rows)
        conn.commit()
    return len(rows)


def run(dsn: str = DB_DSN) -> list[dict[str, Any]]:
    chunks = collect_chunks()
    load_chunks(chunks, dsn=dsn)
    return chunks


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    loaded_chunks = run()

    counts: dict[str, int] = {}
    for chunk in loaded_chunks:
        counts[chunk["jurisdiction"]] = counts.get(chunk["jurisdiction"], 0) + 1

    print(f"Loaded {len(loaded_chunks)} chunks total\n")
    for jurisdiction, count in sorted(counts.items()):
        print(f"  {jurisdiction}: {count} chunks")
