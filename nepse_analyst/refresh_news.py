#!/usr/bin/env python3
"""Re-scrape news articles and rebuild the ChromaDB index (the loader's news step)."""

from nepse_analyst.ingestion import Loader


def main() -> None:
    Loader().run(["news"])


if __name__ == "__main__":
    main()
