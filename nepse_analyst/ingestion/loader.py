"""Single entry point for populating nepse.db and the news vector store.

    from nepse_analyst.ingestion import Loader
    Loader().run()                      # every step, default sources
    Loader().run(["prices", "indices"])  # subset

Swap a source by passing ``Sources(...)``; the loader only depends on the
interfaces in ``sources/base.py``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from nepse_analyst.config import BASE_DIR, DB_PATH, MAX_ARTICLES, NEWS_COLLECTION, VECTOR_STORE_DIR
from nepse_analyst.database import FULL_SCHEMA_SQL
from nepse_analyst.ingestion.records import Company, NewsArticle
from nepse_analyst.ingestion.sources.base import (
    CompanySource,
    FundamentalsSource,
    IPOSource,
    NewsSource,
    PriceSource,
)

STEPS: tuple[str, ...] = ("companies", "prices", "indices", "fundamentals", "ipos", "news")

# Instrument classes without comparable company fundamentals.
FUNDAMENTALS_EXCLUDED_SECTORS = ("Govt. Bonds", "Mutual Fund", "Corp. Debentures")

PRICE_BATCH_SIZE = 500
MAX_CONSECUTIVE_PRICE_FAILURES = 25
MAX_ERROR_LOGS = 15


@dataclass
class Sources:
    companies: CompanySource
    prices: PriceSource
    fundamentals: FundamentalsSource
    ipos: IPOSource
    news: Sequence[NewsSource] = field(default_factory=list)

    def all(self) -> list[Any]:
        return [self.companies, self.prices, self.fundamentals, self.ipos, *self.news]


def default_sources() -> Sources:
    """Today's sources. The unofficial NEPSE API is the first price source."""
    from nepse_analyst.ingestion.sources.fallback import FallbackPriceSource
    from nepse_analyst.ingestion.sources.github_open_data import GitHubOpenDataSource
    from nepse_analyst.ingestion.sources.kaggle_csv import KaggleCsvCompanySource
    from nepse_analyst.ingestion.sources.merolagani import MerolaganiSource
    from nepse_analyst.ingestion.sources.nepse_api import NepseApiSource
    from nepse_analyst.ingestion.sources.nepsealpha import NepseAlphaNewsSource
    from nepse_analyst.ingestion.sources.sharesansar import (
        SharesansarIPOSource,
        SharesansarNewsSource,
    )

    return Sources(
        companies=KaggleCsvCompanySource(),
        prices=FallbackPriceSource([NepseApiSource(), GitHubOpenDataSource()]),
        fundamentals=MerolaganiSource(),
        ipos=SharesansarIPOSource(),
        news=[SharesansarNewsSource(), NepseAlphaNewsSource()],
    )


def is_equity_symbol(symbol: str) -> bool:
    """Listed equity only: skip debentures, bonds, and promoter-share variants."""
    text = symbol.strip().upper()
    return bool(text) and text.isalpha() and not text.endswith("P")


def normalize_company_name(value: str) -> str:
    text = re.sub(r"\(.*?\)", " ", (value or "").lower())
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    return re.sub(r"\s+", " ", text)


_ARTICLE_TYPES = (
    ("dividend", ("dividend", "लाभांश")),
    ("ipo", ("ipo", "public issue", "सार्वजनिक निष्काशन")),
    ("agm", ("agm", "annual general", "साधारण सभा")),
    ("earnings", ("earning", "profit", "नाफा", "quarter")),
    ("regulatory", ("sebon", "regulation", "नियामक", "policy")),
)


def classify_article(title: str) -> str:
    lower = title.lower()
    for article_type, keywords in _ARTICLE_TYPES:
        if any(k in lower for k in keywords):
            return article_type
    return "market"


def enrich_article(article: NewsArticle, companies: Iterable[tuple[str, str, str]]) -> dict:
    """Tag an article with the first company it mentions and build its doc id."""
    symbol = sector = None
    text_upper = (article.title + " " + article.content[:500]).upper()
    for sym, name, sec in companies:
        if sym in text_upper or name.upper() in text_upper:
            symbol, sector = sym, sec
            break
    url_hash = hashlib.md5(article.url.encode()).hexdigest()
    date_slug = article.published_at.replace("-", "") if article.published_at else "undated"
    return {
        "id": f"{article.source}_{date_slug}_{url_hash[:8]}",
        **asdict(article),
        "symbol": symbol,
        "sector": sector,
        "article_type": classify_article(article.title),
    }


def dedupe_by_title(docs: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique = []
    for doc in docs:
        key = doc["title"].lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(doc)
    return unique


def index_news_in_chroma(docs: list[dict], vector_store_dir: str, collection_name: str) -> int:
    """Rebuild the Chroma collection from scratch. Returns the indexed count."""
    import numpy as np

    # Prevent implicit use of stale Hugging Face auth tokens.
    os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
    for var in ("HF_TOKEN", "HUGGINGFACEHUB_API_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        os.environ.pop(var, None)
    if not hasattr(np, "float_"):  # chromadb 0.5.x on NumPy 2.x
        np.float_ = np.float64

    import chromadb

    from nepse_analyst.embeddings import encode

    os.makedirs(vector_store_dir, exist_ok=True)
    client = chromadb.PersistentClient(path=vector_store_dir)
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass
    collection = client.create_collection(name=collection_name, metadata={"hnsw:space": "cosine"})

    fallback = None
    for i in range(0, len(docs), 200):
        batch = docs[i : i + 200]
        texts = [f"{d['title']}. {d['content'][:300]}" for d in batch]
        if fallback is None:
            try:
                embeddings = encode(texts, batch_size=64)
            except Exception as exc:
                print(f"Primary embedder failed; switching to hashing fallback. Reason: {exc}")
                from sklearn.feature_extraction.text import HashingVectorizer

                fallback = HashingVectorizer(n_features=384, alternate_sign=False, norm="l2")
        if fallback is not None:
            embeddings = fallback.transform(texts).toarray().astype("float32")
        collection.add(
            ids=[d["id"] for d in batch],
            embeddings=[e.tolist() for e in embeddings],
            documents=[d["content"] for d in batch],
            metadatas=[
                {
                    "source": d["source"],
                    "title": d["title"],
                    "symbol": d["symbol"] or "",
                    "sector": d["sector"] or "",
                    "language": d["language"],
                    "published_at": d["published_at"],
                    "article_type": d["article_type"],
                    "url": d["url"],
                }
                for d in batch
            ],
        )
    return collection.count()


class Loader:
    def __init__(
        self,
        sources: Sources | None = None,
        db_path: str = DB_PATH,
        vector_store_dir: str = VECTOR_STORE_DIR,
        news_collection: str = NEWS_COLLECTION,
        processed_dir: str | None = None,
        max_articles: int | None = MAX_ARTICLES,
        news_indexer: Callable[[list[dict], str, str], int] = index_news_in_chroma,
    ) -> None:
        self._sources = sources
        self.db_path = db_path
        self.vector_store_dir = vector_store_dir
        self.news_collection = news_collection
        self.processed_dir = processed_dir or os.path.dirname(db_path)
        self.max_articles = max_articles
        self.news_indexer = news_indexer

    @property
    def sources(self) -> Sources:
        if self._sources is None:
            self._sources = default_sources()
        return self._sources

    # -- orchestration ----------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        return sqlite3.connect(self.db_path)

    def create_schema(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(FULL_SCHEMA_SQL)
            conn.commit()
        finally:
            conn.close()

    def run(self, steps: Iterable[str] | None = None) -> dict[str, dict]:
        selected = list(steps) if steps is not None else list(STEPS)
        unknown = [s for s in selected if s not in STEPS]
        if unknown:
            raise ValueError(f"Unknown step(s) {unknown}; choose from {list(STEPS)}")

        self.create_schema()
        results: dict[str, dict] = {}
        try:
            for step in STEPS:  # canonical order: later steps read earlier tables
                if step in selected:
                    print(f"\n=== {step} ===")
                    results[step] = getattr(self, f"load_{step}")()
                    print(f"{step}: {results[step]}")
        finally:
            for source in self.sources.all():
                close = getattr(source, "close", None)
                if callable(close):
                    close()
        return results

    # -- steps --------------------------------------------------------------
    def load_companies(self) -> dict:
        companies = self.sources.companies.fetch_companies()
        if not companies:
            raise RuntimeError(f"{self.sources.companies.name} returned no companies")
        conn = self._connect()
        try:
            conn.execute("DELETE FROM companies")
            conn.executemany(
                "INSERT INTO companies (symbol, name, sector, listed_shares, paid_up_value, "
                "total_paid_up, is_active) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (c.symbol, c.name, c.sector, c.listed_shares, c.paid_up_value, c.total_paid_up, c.is_active)
                    for c in companies
                ],
            )
            conn.commit()
            sectors = conn.execute("SELECT COUNT(DISTINCT sector) FROM companies").fetchone()[0]
        finally:
            conn.close()
        return {"companies": len(companies), "sectors": sectors}

    def _company_rows(self, conn: sqlite3.Connection, where: str = "", params: Sequence = ()) -> list[tuple]:
        return conn.execute(
            f"SELECT symbol, name, sector FROM companies {where} ORDER BY symbol", params
        ).fetchall()

    def load_prices(self) -> dict:
        source = self.sources.prices
        conn = self._connect()
        try:
            symbols = [s for (s, _, _) in self._company_rows(conn) if is_equity_symbol(s)]
            if not symbols:
                raise RuntimeError("No equity symbols in companies table; run the companies step first.")
            if not source.available():
                raise RuntimeError(f"Price source unavailable: {source.name}")

            conn.execute("DELETE FROM price_history")
            conn.commit()

            insert_sql = (
                "INSERT INTO price_history (symbol, trade_date, open_price, high_price, low_price, "
                "close_price, volume, turnover) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            )
            pending: list[tuple] = []
            inserted = 0
            failed: list[str] = []
            consecutive_failures = 0
            aborted = False
            for i, symbol in enumerate(symbols, start=1):
                try:
                    bars = source.fetch_price_history(symbol)
                    if not bars:
                        raise RuntimeError("No history rows returned")
                except Exception as exc:
                    failed.append(symbol)
                    consecutive_failures += 1
                    if len(failed) <= MAX_ERROR_LOGS:
                        print(f"Failed {symbol}: {exc}")
                    if consecutive_failures >= MAX_CONSECUTIVE_PRICE_FAILURES:
                        print("Aborting: too many consecutive failures (likely upstream outage/rate limit).")
                        aborted = True
                        break
                    continue

                consecutive_failures = 0
                pending.extend(
                    (b.symbol, b.trade_date, b.open_price, b.high_price, b.low_price,
                     b.close_price, b.volume, b.turnover)
                    for b in bars
                )
                if len(pending) >= PRICE_BATCH_SIZE:
                    conn.executemany(insert_sql, pending)
                    conn.commit()
                    inserted += len(pending)
                    pending.clear()
                if i % 50 == 0:
                    print(f"Prices: {i}/{len(symbols)} symbols, {inserted + len(pending)} rows")

            if pending:
                conn.executemany(insert_sql, pending)
                conn.commit()
                inserted += len(pending)
        finally:
            conn.close()

        if aborted and inserted == 0:
            raise RuntimeError("Price ingestion aborted with zero rows due to persistent upstream failures.")
        result = {
            "symbols_attempted": len(symbols),
            "rows": inserted,
            "failed_symbols": len(failed),
            "aborted": aborted,
        }
        served_by = getattr(source, "served_by", None)
        if served_by:
            result["served_by"] = dict(served_by)
        return result

    def load_indices(self) -> dict:
        bars = self.sources.prices.fetch_index_history()
        seen: set[tuple[str, str]] = set()
        rows: list[tuple] = []
        for b in bars:
            key = (b.index_name, b.trade_date)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                (b.trade_date, b.index_name, b.open_value, b.close_value,
                 b.change_points, b.change_percent, b.turnover)
            )
        if not rows:
            raise RuntimeError("Index ingestion produced zero rows; every source failed.")
        rows.sort(key=lambda r: (r[0], r[1]))

        conn = self._connect()
        try:
            conn.execute("DELETE FROM indices")
            conn.executemany(
                "INSERT INTO indices (trade_date, index_name, open_value, close_value, "
                "change_points, change_percent, turnover) VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            conn.commit()
        finally:
            conn.close()

        per_index: dict[str, dict] = {}
        for trade_date, name, *_ in rows:
            info = per_index.setdefault(name, {"rows": 0, "min": trade_date, "max": trade_date})
            info["rows"] += 1
            info["min"] = min(info["min"], trade_date)
            info["max"] = max(info["max"], trade_date)
        missing = sorted({"NEPSE", "Banking", "Hydropower"} - per_index.keys())
        if missing:
            print(f"WARNING: missing index history for {missing}")
        return {"rows": len(rows), "per_index": per_index}

    def load_fundamentals(self) -> dict:
        source = self.sources.fundamentals
        conn = self._connect()
        try:
            placeholders = ",".join("?" * len(FUNDAMENTALS_EXCLUDED_SECTORS))
            symbols = [
                s for (s, _, _) in self._company_rows(
                    conn, f"WHERE sector NOT IN ({placeholders})", FUNDAMENTALS_EXCLUDED_SECTORS
                )
            ]
        finally:
            conn.close()

        fundamentals: list[tuple] = []
        dividends: list[tuple] = []
        errors: list[str] = []
        for i, symbol in enumerate(symbols, start=1):
            try:
                f_rows, d_rows = source.fetch_fundamentals(symbol)
            except Exception as exc:
                errors.append(symbol)
                print(f"[ERROR] {symbol}: {exc}")
                continue
            fundamentals.extend(
                (f.symbol, f.fiscal_year, f.eps, f.pe_ratio, f.book_value, f.roe,
                 f.net_profit, f.total_assets, f.revenue)
                for f in f_rows if f.fiscal_year
            )
            dividends.extend(
                (d.symbol, d.fiscal_year, d.cash_dividend, d.bonus_shares,
                 d.book_close_date, d.announced_date)
                for d in d_rows if d.fiscal_year
            )
            if i % 25 == 0:
                print(f"Fundamentals: {i}/{len(symbols)} symbols")

        conn = self._connect()
        try:
            conn.executescript(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS ux_fundamentals_symbol_fy
                ON fundamentals(symbol, fiscal_year);
                CREATE UNIQUE INDEX IF NOT EXISTS ux_dividends_symbol_fy
                ON dividends(symbol, fiscal_year);
                """
            )
            if symbols:
                ph = ",".join("?" * len(symbols))
                conn.execute(f"DELETE FROM fundamentals WHERE symbol IN ({ph})", symbols)
                conn.execute(f"DELETE FROM dividends WHERE symbol IN ({ph})", symbols)
            conn.executemany(
                """
                INSERT INTO fundamentals (symbol, fiscal_year, eps, pe_ratio, book_value, roe,
                    net_profit, total_assets, revenue)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, fiscal_year) DO UPDATE SET
                    eps = excluded.eps, pe_ratio = excluded.pe_ratio,
                    book_value = excluded.book_value, roe = excluded.roe,
                    net_profit = excluded.net_profit, total_assets = excluded.total_assets,
                    revenue = excluded.revenue
                """,
                fundamentals,
            )
            conn.executemany(
                """
                INSERT INTO dividends (symbol, fiscal_year, cash_dividend, bonus_shares,
                    book_close_date, announced_date)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, fiscal_year) DO UPDATE SET
                    cash_dividend = excluded.cash_dividend, bonus_shares = excluded.bonus_shares,
                    book_close_date = excluded.book_close_date,
                    announced_date = excluded.announced_date
                """,
                dividends,
            )
            conn.commit()
        finally:
            conn.close()
        return {
            "symbols": len(symbols),
            "fundamentals_rows": len(fundamentals),
            "dividend_rows": len(dividends),
            "errors": len(errors),
        }

    def load_ipos(self) -> dict:
        issues = self.sources.ipos.fetch_ipos()
        conn = self._connect()
        try:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(ipos)")}
            if "oversubscription_rate" not in cols:  # databases built before the column existed
                conn.execute("ALTER TABLE ipos ADD COLUMN oversubscription_rate REAL")

            by_name: dict[str, tuple[str, str]] = {}
            for symbol, name, sector in self._company_rows(conn):
                by_name.setdefault(normalize_company_name(name), (symbol, sector))
            # Listing date/price = first trading day in price_history.
            first_trade = {
                symbol: (trade_date, price)
                for symbol, trade_date, price in conn.execute(
                    """
                    WITH first_day AS (
                        SELECT symbol, MIN(trade_date) AS d FROM price_history
                        WHERE symbol IS NOT NULL GROUP BY symbol
                    )
                    SELECT f.symbol, f.d, COALESCE(p.open_price, p.close_price)
                    FROM first_day f
                    JOIN price_history p ON p.symbol = f.symbol AND p.trade_date = f.d
                    """
                )
            }

            rows: list[tuple] = []
            seen: set[str] = set()
            for ipo in issues:
                matched_symbol, sector = by_name.get(normalize_company_name(ipo.company_name), (None, None))
                symbol = ipo.symbol or matched_symbol
                if not symbol or symbol in seen or symbol not in first_trade:
                    continue
                first_date, listing_price = first_trade[symbol]
                if listing_price is None:
                    continue
                oversubscription = ipo.oversubscription_rate
                if ipo.total_applicants and ipo.shares_issued and ipo.allotment_per_person:
                    oversubscription = ipo.total_applicants / (ipo.shares_issued / ipo.allotment_per_person)
                seen.add(symbol)
                rows.append(
                    (symbol, ipo.company_name, sector, ipo.issue_date, ipo.listing_date or first_date,
                     ipo.issue_price, listing_price, ipo.shares_issued, ipo.total_applicants,
                     oversubscription, "listed")
                )

            conn.execute("DELETE FROM ipos")
            conn.executemany(
                "INSERT INTO ipos (symbol, company_name, sector, issue_date, listing_date, issue_price, "
                "listing_price, shares_issued, total_applicants, oversubscription_rate, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            conn.commit()
        finally:
            conn.close()
        return {"issues_fetched": len(issues), "rows": len(rows)}

    def load_news(self) -> dict:
        conn = self._connect()
        try:
            companies = self._company_rows(conn)
        finally:
            conn.close()

        docs: list[dict] = []
        per_source: dict[str, int] = {}
        for source in self.sources.news:
            articles = source.fetch_news(limit=self.max_articles)
            per_source[source.name] = len(articles)
            docs.extend(enrich_article(a, companies) for a in articles)
        docs = dedupe_by_title(docs)
        if not docs:
            raise RuntimeError("News ingestion produced zero documents; leaving the vector store untouched.")

        os.makedirs(self.processed_dir, exist_ok=True)
        with open(os.path.join(self.processed_dir, "all_docs.json"), "w", encoding="utf-8") as f:
            json.dump(docs, f, ensure_ascii=False, indent=2)

        indexed = self.news_indexer(docs, self.vector_store_dir, self.news_collection)

        backup = os.path.join(self.processed_dir, "vector_store_backup")
        if os.path.isdir(self.vector_store_dir):
            shutil.rmtree(backup, ignore_errors=True)
            shutil.copytree(self.vector_store_dir, backup)
        return {"fetched": per_source, "documents": len(docs), "indexed": indexed}
