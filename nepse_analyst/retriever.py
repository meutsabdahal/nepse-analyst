import numpy as np

# ChromaDB 0.5.x expects np.float_ at import time, which was removed in NumPy 2.x.
if not hasattr(np, "float_"):
    np.float_ = np.float64

import chromadb
from nepse_analyst.config import VECTOR_STORE_DIR, NEWS_COLLECTION, TOP_K_RAG
from nepse_analyst.embeddings import encode_query

_client = None
_collection = None


def _get_collection():
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path=VECTOR_STORE_DIR)
        _collection = _client.get_collection(NEWS_COLLECTION)
    return _collection


def search(
    query: str,
    top_k: int = TOP_K_RAG,
    symbol_filter: str = None,
    sector_filter: str = None,
    language_filter: str = None,
    article_type_filter: str = None,
) -> list[dict]:
    collection = _get_collection()
    query_embedding = encode_query(query).tolist()

    # Build ChromaDB metadata filter (where clause)
    where = {}
    if symbol_filter:
        where["symbol"] = symbol_filter
    if sector_filter:
        where["sector"] = sector_filter
    if language_filter:
        where["language"] = language_filter
    if article_type_filter:
        where["article_type"] = article_type_filter

    query_kwargs = {
        "query_embeddings": [query_embedding],
        "n_results": top_k,
        "include": ["documents", "metadatas", "distances"],
    }
    if where:
        query_kwargs["where"] = where

    results = collection.query(**query_kwargs)

    passages = []
    if not results["ids"] or not results["ids"][0]:
        return passages

    for i, doc_id in enumerate(results["ids"][0]):
        metadata = results["metadatas"][0][i]
        distance = results["distances"][0][i]
        # ChromaDB cosine distance: 0 = identical, 2 = opposite
        # Convert to similarity score 0–1
        relevance_score = 1 - (distance / 2)

        passages.append(
            {
                "title": metadata.get("title", ""),
                "content": results["documents"][0][i],
                "source": metadata.get("source", ""),
                "symbol": metadata.get("symbol", ""),
                "sector": metadata.get("sector", ""),
                "language": metadata.get("language", "en"),
                "published_at": metadata.get("published_at", ""),
                "article_type": metadata.get("article_type", ""),
                "url": metadata.get("url", ""),
                "relevance_score": round(relevance_score, 4),
            }
        )

    # Sort by relevance descending (ChromaDB already does this, but be explicit)
    passages.sort(key=lambda x: x["relevance_score"], reverse=True)
    return passages


def search_by_symbol(symbol: str, top_k: int = TOP_K_RAG) -> list[dict]:

    return search("", top_k=top_k, symbol_filter=symbol)


def get_corpus_stats() -> dict:
    """Return basic stats about the indexed corpus — useful for the UI freshness indicator."""
    collection = _get_collection()
    count = collection.count()
    # Get date range by querying a sample
    sample = collection.query(
        query_embeddings=[encode_query("NEPSE market news").tolist()],
        n_results=min(100, count),
        include=["metadatas"],
    )
    dates = [
        m.get("published_at", "")
        for m in sample["metadatas"][0]
        if m.get("published_at")
    ]
    return {
        "total_documents": count,
        "earliest_date": min(dates) if dates else "unknown",
        "latest_date": max(dates) if dates else "unknown",
    }
