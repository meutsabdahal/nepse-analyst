#!/usr/bin/env python3
"""Wrapper command for building the NEPSE Analyst database. See nepse_analyst/build_db.py."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nepse_analyst.build_db import main


if __name__ == "__main__":
    main()
