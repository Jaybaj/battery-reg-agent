CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    jurisdiction    TEXT NOT NULL,
    instrument      TEXT NOT NULL,
    instrument_short TEXT NOT NULL,
    section_ref     TEXT NOT NULL,
    section_title   TEXT NOT NULL,
    parent_context  TEXT NOT NULL,
    text            TEXT NOT NULL,
    url             TEXT NOT NULL,
    version_date    DATE NOT NULL,
    source_type     TEXT NOT NULL CHECK (source_type IN ('verified_corpus', 'web_search')),
    embedding       vector(384),
    content_tsv     tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
);

CREATE INDEX idx_chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_chunks_content_tsv ON chunks USING gin (content_tsv);
CREATE INDEX idx_chunks_jurisdiction ON chunks USING btree (jurisdiction);
CREATE INDEX idx_chunks_instrument ON chunks USING btree (instrument);
