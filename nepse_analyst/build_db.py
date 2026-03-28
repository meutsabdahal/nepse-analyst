#!/usr/bin/env python3
"""Rebuild the SQLite schema for data/processed/nepse.db.

Run this after downloading fresh data artifacts from ingestion notebooks.
Usage: python -m nepse_analyst.build_db
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nepse_analyst.database import create_database

if __name__ == "__main__":
    print("Creating database schema...")
    create_database()
    print(f"Database created. Run Colab notebooks 01–04 to populate it.")
