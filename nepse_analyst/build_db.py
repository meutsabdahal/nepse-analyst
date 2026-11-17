#!/usr/bin/env python3
"""Build data/processed/nepse.db (and the news vector store) from configured sources.

Usage:
    python -m nepse_analyst.build_db                        # schema + every step
    python -m nepse_analyst.build_db --steps prices,indices
    python -m nepse_analyst.build_db --schema-only
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nepse_analyst.ingestion import STEPS, Loader


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--steps",
        default=",".join(STEPS),
        help=f"Comma-separated subset of: {', '.join(STEPS)} (default: all, in that order)",
    )
    parser.add_argument("--schema-only", action="store_true", help="Create tables and indexes only")
    args = parser.parse_args(argv)

    loader = Loader()
    if args.schema_only:
        loader.create_schema()
        print(f"Schema created at {loader.db_path}")
        return

    steps = [s.strip() for s in args.steps.split(",") if s.strip()]
    loader.run(steps)
    print(f"\nDone. Database: {loader.db_path}")


if __name__ == "__main__":
    main()
