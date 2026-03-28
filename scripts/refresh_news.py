#!/usr/bin/env python3
"""Wrapper command for news refresh workflow."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nepse_analyst.refresh_news import main


if __name__ == "__main__":
    main()
