from sentence_transformers import SentenceTransformer
from nepse_analyst.config import EMBEDDING_MODEL

_model = None  # module-level singleton

def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        print(f"Loading embedding model: {EMBEDDING_MODEL} (first call only)...")
        _model = SentenceTransformer(EMBEDDING_MODEL)
        print("Embedding model loaded.")
    return _model

def encode(texts: list[str] | str, batch_size: int = 64) -> list:
    model = _get_model()
    if isinstance(texts, str):
        texts = [texts]
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=len(texts) > 100,
        convert_to_numpy=True,
        normalize_embeddings=True   # cosine similarity works better with normalised vectors
    )
    return embeddings

def encode_query(query: str) -> list:
    """Encode a single query string. Convenience wrapper."""
    return encode([query])[0]