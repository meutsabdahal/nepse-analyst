from sentence_transformers import SentenceTransformer
from nepse_analyst.config import EMBEDDING_MODEL

_model = None  # module-level singleton

def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        print(f"Loading embedding model: {EMBEDDING_MODEL} (first call only)...")
        model_candidates = [EMBEDDING_MODEL]
        if "/" not in EMBEDDING_MODEL:
            model_candidates.append(f"sentence-transformers/{EMBEDDING_MODEL}")

        last_error = None
        for candidate in model_candidates:
            try:
                _model = SentenceTransformer(candidate)
                break
            except Exception as e:
                last_error = e

        if _model is None:
            raise RuntimeError(
                "Unable to load embedding model for RAG. "
                f"Tried: {', '.join(model_candidates)}. "
                "Ensure internet/Hugging Face access is available, or pre-download the model "
                "to a local path and set EMBEDDING_MODEL accordingly. "
                f"Original error: {last_error}"
            )
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