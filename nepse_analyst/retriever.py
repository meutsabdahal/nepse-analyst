import numpy as np
import time

# ChromaDB 0.5.x expects np.float_ at import time, which was removed in NumPy 2.x.
if not hasattr(np, "float_"):
    np.float_ = np.float64

import chromadb
from nepse_analyst.config import (
    VECTOR_STORE_DIR,
    NEWS_COLLECTION,
    TOP_K_RAG,
    CORPUS_STATS_TTL_SEC,
    RAG_CANDIDATE_MULTIPLIER,
    RAG_SECTOR_BOOST,
    RAG_SYMBOL_BOOST,
)
from nepse_analyst import corpus_stats
from nepse_analyst.embeddings import encode_query
from nepse_analyst.news_tags import sector_key, split_tags, symbol_key

_client = None
_collection = None
_corpus_stats_cache: dict | None = None


def _get_collection():
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path=VECTOR_STORE_DIR)
        _collection = _client.get_collection(NEWS_COLLECTION)
    return _collection


def _and(clauses: list[dict]) -> dict | None:
    """Chroma expects a single top-level operator when composing predicates."""
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _strict_clauses(language_filter: str | None, article_type_filter: str | None) -> list[dict]:
    clauses = []
    if language_filter:
        clauses.append({"language": {"$eq": language_filter}})
    if article_type_filter:
        clauses.append({"article_type": {"$eq": article_type_filter}})
    return clauses


def _query(collection, embedding: list[float], n_results: int, where: dict | None) -> list[tuple]:
    kwargs = {
        "query_embeddings": [embedding],
        "n_results": n_results,
        "include": ["documents", "metadatas", "distances"],
    }
    if where is not None:
        kwargs["where"] = where
    res = collection.query(**kwargs)
    if not res["ids"] or not res["ids"][0]:
        return []
    return list(zip(res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0]))


def search(
    query: str,
    top_k: int = TOP_K_RAG,
    boost_symbol: str | None = None,
    boost_sector: str | None = None,
    language_filter: str | None = None,
    article_type_filter: str | None = None,
) -> list[dict]:
    """Semantic search over the news corpus.

    ``boost_symbol``/``boost_sector`` rank articles tagged with that company
    or sector higher; they do not exclude untagged articles, because tags
    are incomplete (an article can discuss a company without naming it the
    way the tagger expects). ``language_filter`` and ``article_type_filter``
    are strict filters.
    """
    collection = _get_collection()
    embedding = encode_query(query).tolist()
    strict = _strict_clauses(language_filter, article_type_filter)
    pool = max(top_k * RAG_CANDIDATE_MULTIPLIER, top_k)

    boosts: list[tuple[str, float]] = []
    if boost_symbol:
        boosts.append((symbol_key(boost_symbol), RAG_SYMBOL_BOOST))
    if boost_sector:
        boosts.append((sector_key(boost_sector), RAG_SECTOR_BOOST))

    # Untagged semantic candidates, plus the best tagged ones so a tagged
    # article is considered even if it falls outside the untagged pool.
    candidates: dict[str, tuple] = {}
    for where in [_and(strict)] + [_and(strict + [{key: True}]) for key, _ in boosts]:
        for row in _query(collection, embedding, pool, where):
            candidates.setdefault(row[0], row)

    passages = []
    for _id, document, metadata, distance in candidates.values():
        # ChromaDB cosine distance: 0 = identical, 2 = opposite -> similarity 0..1
        relevance_score = 1 - (distance / 2)
        matched = [key for key, _ in boosts if metadata.get(key) is True]
        rank_score = relevance_score + sum(b for key, b in boosts if key in matched)
        passages.append(
            {
                "title": metadata.get("title", ""),
                "content": document,
                "source": metadata.get("source", ""),
                "symbol": metadata.get("symbol", ""),
                "sector": metadata.get("sector", ""),
                "symbols": split_tags(metadata.get("symbols")) or split_tags(metadata.get("symbol")),
                "sectors": split_tags(metadata.get("sectors")) or split_tags(metadata.get("sector")),
                "language": metadata.get("language", "en"),
                "published_at": metadata.get("published_at", ""),
                "article_type": metadata.get("article_type", ""),
                "url": metadata.get("url", ""),
                "relevance_score": round(relevance_score, 4),
                "rank_score": round(rank_score, 4),
                "tag_match": bool(matched),
            }
        )

    passages.sort(key=lambda x: x["rank_score"], reverse=True)
    return passages[:top_k]


def get_corpus_stats() -> dict:
    """Stats about the indexed news corpus, for the freshness line and staleness warning.

    Read from the collection metadata recorded when the index was built
    (``corpus_stats``). For an index built before stats were recorded, or one
    whose document count no longer matches them, they are computed from every
    document's ``published_at``. Cached for CORPUS_STATS_TTL_SEC.
    """
    global _corpus_stats_cache

    now = time.time()
    if (
        CORPUS_STATS_TTL_SEC > 0
        and _corpus_stats_cache is not None
        and now < _corpus_stats_cache["expires_at"]
    ):
        return _corpus_stats_cache["value"]

    collection = _get_collection()
    count = collection.count()
    value = corpus_stats.from_collection_metadata(collection.metadata)
    if value is None or value["total_documents"] != count:
        metadatas = collection.get(include=["metadatas"])["metadatas"] if count else []
        value = corpus_stats.summarize(
            (m or {}).get("published_at") for m in metadatas
        ) | {"built_at": (value or {}).get("built_at", "unknown")}

    if CORPUS_STATS_TTL_SEC > 0:
        _corpus_stats_cache = {"value": value, "expires_at": now + CORPUS_STATS_TTL_SEC}
    return value
