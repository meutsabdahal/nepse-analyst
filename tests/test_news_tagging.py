import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from nepse_analyst import retriever
from nepse_analyst.ingestion.loader import CompanyMatcher, enrich_article
from nepse_analyst.ingestion.records import NewsArticle
from nepse_analyst.news_tags import sector_key, split_tags, symbol_key, tag_metadata

COMPANIES = [
    ("MEN", "Mountain Energy Nepal Limited", "Hydropower"),
    ("LEC", "Liberty Energy Company Limited", "Hydropower"),
    ("API", "Api Power Company Ltd.", "Hydropower"),
    ("SEBON", "Securities Board of Nepal", "Trading"),
    ("NABIL", "Nabil Bank Limited", "Commercial Banks"),
    ("NABILP", "Nabil Bank Limited Promoter Share", "Others"),
    ("EBLPO", "Everest Bank Limited Promoter Share", "Promoter Shares"),
    ("NADEP", "Nadep Laghubitta Bittiya Sanstha Ltd.", "Microfinance"),
    ("NIC", "Nic Old Symbol Limited", "Others"),
    ("NICA", "NIC Asia Bank Ltd.", "Commercial Banks"),
    ("NHDL", "Nepal Hydro Developers Ltd.", "Hydropower"),
    ("NICL", "Nepal Insurance Company Limited", "Non-Life Insurance"),
]


def article(title, content="", url="https://x/1"):
    return NewsArticle(url, "test", title, content, "2026-11-18", "en")


class CompanyMatcherTests(unittest.TestCase):
    def setUp(self):
        self.m = CompanyMatcher(COMPANIES)

    def test_symbols_inside_other_words_do_not_match(self):
        # Each of these was tagged by the old substring matcher.
        for text in (
            "Watch the Nepal Investment Summit",  # MEN in INVESTMENT
            "NEPAL INVESTMENT SUMMIT",
            "Central bank to collect 200 billion",  # LEC in COLLECT
            "Capital plan of commercial banks",  # API in CAPITAL
            "Women and men in the workforce",  # lower-case word "men"
        ):
            with self.subTest(text=text):
                self.assertEqual(self.m.match(text), [])

    def test_symbol_as_whole_word(self):
        self.assertEqual(self.m.match("MEN to distribute bonus shares"), ["MEN"])
        self.assertEqual(self.m.match("(LEC) announced AGM"), ["LEC"])

    def test_longer_symbol_wins_at_same_position(self):
        self.assertEqual(self.m.match("NICA shares rose"), ["NICA"])

    def test_company_name_without_legal_suffix(self):
        self.assertEqual(self.m.match("What recent news is there about Nabil Bank?"), ["NABIL"])
        self.assertEqual(self.m.match("Nepal Hydro Developer Limited proposes bonus"), ["NHDL"])

    def test_several_companies_in_mention_order(self):
        self.assertEqual(
            self.m.match("NIC Asia Bank and Nabil Bank sign merger MoU"), ["NICA", "NABIL"]
        )

    def test_generic_short_name_needs_full_legal_name(self):
        self.assertEqual(self.m.match("Nepal Insurance Authority issues directive"), [])
        self.assertEqual(self.m.match("Nepal Insurance Company Limited calls AGM"), ["NICL"])

    def test_promoter_shares_are_not_tagged(self):
        self.assertEqual(self.m.match("NABILP auction announced"), [])
        self.assertEqual(self.m.match("EBLPO auction announced"), [])

    def test_ambiguous_symbols_need_name_or_market_context(self):
        untagged = [
            "SEBON issues new directive for brokers",
            "Securities Board of Nepal approves three IPOs",
            "NEPSE API outage halts online trading",
        ]
        for text in untagged:
            with self.subTest(text=text):
                self.assertEqual(self.m.match(text), [])
        self.assertEqual(self.m.match("Api Power reports higher profit"), ["API"])
        self.assertEqual(self.m.match("API shares hit the upper circuit"), ["API"])
        self.assertEqual(self.m.match("Investors bought shares of API today"), ["API"])
        self.assertEqual(self.m.match("SEBON shares to be auctioned"), ["SEBON"])

    def test_symbol_ending_in_p_is_tagged_when_not_a_promoter_share(self):
        self.assertEqual(self.m.match("NADEP declares dividend"), ["NADEP"])


class EnrichArticleTests(unittest.TestCase):
    def test_all_companies_and_deduped_sectors(self):
        doc = enrich_article(
            article("Nabil Bank and NIC Asia Bank merge; MEN and LEC report profits"),
            CompanyMatcher(COMPANIES),
        )
        self.assertEqual(doc["symbols"], ["NABIL", "NICA", "MEN", "LEC"])
        self.assertEqual(doc["sectors"], ["Commercial Banks", "Hydropower"])
        self.assertEqual((doc["symbol"], doc["sector"]), ("NABIL", "Commercial Banks"))

    def test_untagged_article(self):
        doc = enrich_article(article("Gold price falls", "Gold fell by Rs. 1900 per tola."), COMPANIES)
        self.assertEqual((doc["symbols"], doc["sectors"], doc["symbol"], doc["sector"]), ([], [], None, None))


class TagMetadataTests(unittest.TestCase):
    def test_round_trip(self):
        meta = tag_metadata(["NABIL", "NICA"], ["Commercial Banks", "Hotels & Tourism"])
        self.assertEqual(meta["symbol"], "NABIL")
        self.assertTrue(meta[symbol_key("NICA")])
        self.assertTrue(meta[sector_key("Hotels & Tourism")])
        self.assertEqual(sector_key("Hotels & Tourism"), "sec_hotels_tourism")
        self.assertEqual(split_tags(meta["symbols"]), ["NABIL", "NICA"])
        self.assertEqual(split_tags(meta["sectors"]), ["Commercial Banks", "Hotels & Tourism"])


def _unit(*xs):
    v = np.array(xs, dtype=float)
    return (v / np.linalg.norm(v)).tolist()


class BoostedSearchTests(unittest.TestCase):
    """search() against a real Chroma collection with hand-made embeddings."""

    QUERY = _unit(1, 0, 0)

    def setUp(self):
        import chromadb

        self.tmp = tempfile.TemporaryDirectory()
        client = chromadb.PersistentClient(path=self.tmp.name)
        self.collection = client.create_collection("news_test", metadata={"hnsw:space": "cosine"})

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, doc_id, embedding, symbols=(), sectors=(), language="en", legacy_symbol=None):
        meta = {"title": doc_id, "language": language, "published_at": "2026-11-18",
                "source": "t", "article_type": "market", "url": doc_id}
        if legacy_symbol is not None:  # index built before multi-tag metadata
            meta.update({"symbol": legacy_symbol, "sector": ""})
        else:
            meta.update(tag_metadata(list(symbols), list(sectors)))
        self.collection.add(ids=[doc_id], embeddings=[embedding], documents=[doc_id], metadatas=[meta])

    def search(self, **kwargs):
        with patch.object(retriever, "_get_collection", return_value=self.collection), \
             patch.object(retriever, "encode_query", return_value=np.array(self.QUERY)):
            return retriever.search("q", **kwargs)

    def ids(self, passages):
        return [p["title"] for p in passages]

    def test_untagged_articles_are_not_filtered_out(self):
        # The old behaviour: a symbol filter with no tagged article returned nothing.
        self.add("untagged", _unit(1, 0.1, 0))
        self.assertEqual(self.ids(self.search(top_k=3, boost_symbol="NABIL")), ["untagged"])

    def test_tagged_article_ranks_above_slightly_closer_untagged(self):
        self.add("untagged-closer", _unit(1, 0.30, 0))
        self.add("nabil", _unit(1, 0.45, 0), symbols=["NABIL"], sectors=["Commercial Banks"])
        self.assertEqual(self.ids(self.search(top_k=2)), ["untagged-closer", "nabil"])
        out = self.search(top_k=2, boost_symbol="NABIL")
        self.assertEqual(self.ids(out), ["nabil", "untagged-closer"])
        self.assertTrue(out[0]["tag_match"])
        self.assertGreater(out[0]["rank_score"], out[0]["relevance_score"])

    def test_boost_does_not_beat_a_much_better_match(self):
        self.add("on-topic", _unit(1, 0, 0))
        self.add("nabil-off-topic", _unit(0, 1, 0), symbols=["NABIL"])
        self.assertEqual(self.ids(self.search(top_k=1, boost_symbol="NABIL")), ["on-topic"])

    def test_tagged_article_outside_untagged_pool_is_considered(self):
        for i in range(30):
            self.add(f"close-{i}", _unit(1, 0.01 * i, 0))
        self.add("nabil", _unit(1, 0.35, 0), symbols=["NABIL"])
        out = self.search(top_k=1, boost_symbol="NABIL")  # untagged pool is only 4 wide
        self.assertEqual(self.ids(out), ["nabil"])

    def test_multi_company_article_matches_any_of_its_tags(self):
        self.add("merger", _unit(1, 0.45, 0), symbols=["NICA", "NABIL"], sectors=["Commercial Banks"])
        self.add("other", _unit(1, 0.30, 0))
        out = self.search(top_k=1, boost_symbol="NABIL")
        self.assertEqual(self.ids(out), ["merger"])
        self.assertEqual(out[0]["symbols"], ["NICA", "NABIL"])

    def test_sector_boost(self):
        self.add("bank", _unit(1, 0.38, 0), sectors=["Commercial Banks"])
        self.add("other", _unit(1, 0.30, 0))
        self.assertEqual(self.ids(self.search(top_k=1, boost_sector="Commercial Banks")), ["bank"])

    def test_language_filter_stays_strict(self):
        self.add("ne", _unit(1, 0, 0), language="ne")
        self.add("en", _unit(0, 1, 0), language="en")
        self.assertEqual(self.ids(self.search(top_k=5, language_filter="en")), ["en"])

    def test_legacy_index_without_tag_keys(self):
        self.add("legacy", _unit(1, 0.1, 0), legacy_symbol="MEN")
        out = self.search(top_k=3, boost_symbol="NABIL")
        self.assertEqual(self.ids(out), ["legacy"])
        self.assertEqual(out[0]["symbols"], ["MEN"])
        self.assertFalse(out[0]["tag_match"])


if __name__ == "__main__":
    unittest.main()
