#!/usr/bin/env python3
"""
Rebuild the entire nepse.db from scratch.
Run this after downloading fresh data from Colab notebooks.
Usage: python scripts/build_db.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nepse_analyst.database import create_database

if __name__ == "__main__":
    print("Creating database schema...")
    create_database()
    print(f"Database created. Run Colab notebooks 01–04 to populate it.")
