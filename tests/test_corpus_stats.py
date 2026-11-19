import tempfile
import unittest
from unittest.mock import patch

import chromadb
import numpy as np

from nepse_analyst import corpus_stats, retriever  # retriever applies the NumPy shim chromadb needs
from nepse_analyst.ingestion.loader import index_news_in_chroma


def _doc(i: int, published_at: str) -> dict:
    return {
        "id": f"doc{i}", "title": f"Article {i}", "content": f"Body of article {i}", "source": "test",
        "language": "en", "published_at": published_at, "article_type": "general", "url": f"https://x/{i}",
        "symbols": [], "sectors": [],
    }


def _fake_encode(texts, batch_size=64):
    rng = np.random.default_rng(len(texts))
    return rng.random((len(texts), 8)).astype("float32")


class SummarizeTests(unittest.TestCase):
    def test_uses_every_dated_article(self) -> None:
        stats = corpus_stats.summarize(["2026-11-01", "", None, "2026-11-18", "not a date", "2025-01-05"])
        self.assertEqual(
            {k: stats[k] for k in ("total_documents", "dated_documents", "earliest_date", "latest_date")},
            {"total_documents": 6, "dated_documents": 3, "earliest_date": "2025-01-05", "latest_date": "2026-11-18"},
        )

    def test_empty_corpus(self) -> None:
        stats = corpus_stats.summarize([])
        self.assertEqual((stats["total_documents"], stats["latest_date"]), (0, "unknown"))

    def test_metadata_round_trip(self) -> None:
        stats = corpus_stats.summarize(["2026-11-18"], built_at="2026-11-19T10:00:00+00:00")
        meta = {"hnsw:space": "cosine", **corpus_stats.to_collection_metadata(stats)}
        self.assertEqual(corpus_stats.from_collection_metadata(meta), stats)
        self.assertIsNone(corpus_stats.from_collection_metadata({"hnsw:space": "cosine"}))


class IndexStatsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        retriever._corpus_stats_cache = None
        self.addCleanup(setattr, retriever, "_corpus_stats_cache", None)
        original = retriever._collection
        self.addCleanup(setattr, retriever, "_collection", original)

    def _use(self, collection) -> None:
        retriever._collection = collection
        retriever._corpus_stats_cache = None

    def test_build_records_stats_that_the_retriever_reads_back(self) -> None:
        # 150 articles: more than the old 100-article sample, newest one in the middle.
        dates = [f"2025-{(i % 12) + 1:02d}-10" for i in range(150)]
        dates[77] = "2026-11-18"
        dates[3] = ""
        docs = [_doc(i, d) for i, d in enumerate(dates)]
        with patch("nepse_analyst.embeddings.encode", side_effect=_fake_encode):
            self.assertEqual(index_news_in_chroma(docs, self.tmp.name, "news"), 150)

        collection = chromadb.PersistentClient(path=self.tmp.name).get_collection("news")
        recorded = corpus_stats.from_collection_metadata(collection.metadata)
        self.assertEqual((recorded["total_documents"], recorded["dated_documents"]), (150, 149))
        self.assertEqual(recorded["latest_date"], "2026-11-18")

        self._use(collection)
        with patch.object(type(collection), "get", side_effect=AssertionError("should not scan")), patch.object(
            retriever, "encode_query", side_effect=AssertionError("should not embed")
        ):
            stats = retriever.get_corpus_stats()
        self.assertEqual((stats["latest_date"], stats["earliest_date"]), ("2026-11-18", "2025-01-10"))
        self.assertEqual(stats["total_documents"], 150)

    def test_index_without_recorded_stats_is_scanned_exactly(self) -> None:
        client = chromadb.PersistentClient(path=self.tmp.name)
        collection = client.create_collection("old", metadata={"hnsw:space": "cosine"})
        dates = ["2024-05-01"] * 120 + ["2026-11-18"] + ["2023-02-02"]
        collection.add(
            ids=[f"d{i}" for i in range(len(dates))],
            embeddings=_fake_encode(dates).tolist(),
            documents=["x"] * len(dates),
            metadatas=[{"published_at": d} for d in dates],
        )
        self._use(collection)
        with patch.object(retriever, "encode_query", side_effect=AssertionError("should not embed")):
            stats = retriever.get_corpus_stats()
        self.assertEqual(
            (stats["total_documents"], stats["earliest_date"], stats["latest_date"], stats["built_at"]),
            (122, "2023-02-02", "2026-11-18", "unknown"),
        )


if __name__ == "__main__":
    unittest.main()
