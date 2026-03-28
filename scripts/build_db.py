#!/usr/bin/env python3
"""Rebuild the SQLite database schema for NEPSE Analyst."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nepse_analyst.database import create_database


if __name__ == "__main__":
    print("Creating database schema...")
    create_database()
    print("Database schema created at data/processed/nepse.db")
