"""Embedding generation for chunk text.

v1 uses sentence-transformers' all-MiniLM-L6-v2 (384 dimensions) -- a small,
free, local model that keeps costs at zero and needs no API key. The
`embedding` column in db/init/001_schema.sql is sized to match (vector(384)).

Swapping providers later (e.g. voyage-law, text-embedding-3-large) means
changing MODEL_NAME/EMBEDDING_DIM here (or replacing the sentence-transformers
call with an API call) and updating the schema's vector() dimension to match.
"""

from __future__ import annotations

MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed_text(text: str) -> list[float]:
    """Return a 384-dim embedding vector for a single chunk of text."""
    return _get_model().encode(text, convert_to_numpy=True).tolist()


def embed_batch(texts: list[str], show_progress: bool = True) -> list[list[float]]:
    """Batch-embed many chunks of text in one pass, much faster than embed_text in a loop."""
    embeddings = _get_model().encode(texts, convert_to_numpy=True, show_progress_bar=show_progress)
    return embeddings.tolist()
