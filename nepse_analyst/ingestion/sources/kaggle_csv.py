"""Company master list from the bundled Kaggle CSV."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from nepse_analyst.config import BASE_DIR
from nepse_analyst.ingestion.records import Company

DEFAULT_CSV_PATH = Path(BASE_DIR) / "data" / "raw" / "nepse_companies_kaggle.csv"

# The Kaggle file has a typo (company_nmae) and uses "name" for the sector.
_COLUMN_MAPPING = {
    "name": "sector",
    "company_nmae": "name",
    "symbol": "symbol",
    "listed_shares": "listed_shares",
    "paidup_value": "paid_up_value",
    "total_paidup": "total_paid_up",
}

# Kaggle sector labels -> PRD sector names.
SECTOR_MAP = {
    "Commercial Banks": "Commercial Banks",
    "Hydro Power": "Hydropower",
    "Life Insurance": "Life Insurance",
    "Development Bank Limited": "Development Banks",
    "Finance": "Finance Companies",
    "Microfinance": "Microfinance",
    "Non-Life Insurance": "Non-Life Insurance",
    "Hotels And Tourism": "Hotels & Tourism",
    "Manufacturing And Processing": "Manufacturing",
    "Tradings": "Trading",
    "Mutual Fund": "Mutual Funds",
    "Investment": "Investment",
    "Others": "Others",
    "Corporate Debenture": "Corp. Debentures",
    "Government Bond": "Govt. Bonds",
    "Capital": "Others",
    "Promotor Share": "Others",
}


def _positive_or_none(value: object) -> float | None:
    # The CSV writes 0 where a figure is unknown (e.g. new or capital-market listings).
    return None if pd.isna(value) or value <= 0 else float(value)


def _count_or_none(value: object) -> int | None:
    number = _positive_or_none(value)
    return None if number is None else int(number)


class KaggleCsvCompanySource:
    name = "kaggle-csv"

    def __init__(self, csv_path: str | Path = DEFAULT_CSV_PATH) -> None:
        self.csv_path = Path(csv_path)

    def fetch_companies(self) -> list[Company]:
        if not self.csv_path.exists():
            raise FileNotFoundError(f"Company CSV not found at {self.csv_path}")

        # Share counts and paid-up totals use thousands separators ("134,516,741").
        df = pd.read_csv(self.csv_path, thousands=",")
        df = df.rename(columns={c: c.strip().lower().replace(" ", "_") for c in df.columns})
        missing = [c for c in _COLUMN_MAPPING if c not in df.columns]
        if missing:
            raise ValueError(f"Missing expected CSV columns: {missing}")
        df = df[list(_COLUMN_MAPPING)].rename(columns=_COLUMN_MAPPING)

        for col in ("symbol", "name", "sector"):
            df[col] = df[col].astype(str).str.strip()
        df["symbol"] = df["symbol"].str.upper()
        df["sector"] = df["sector"].replace(SECTOR_MAP)
        for col in ("listed_shares", "paid_up_value", "total_paid_up"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.drop_duplicates(subset=["symbol"], keep="first")

        return [
            Company(
                symbol=row.symbol,
                name=row.name,
                sector=row.sector,
                listed_shares=_count_or_none(row.listed_shares),
                paid_up_value=_positive_or_none(row.paid_up_value),
                total_paid_up=_positive_or_none(row.total_paid_up),
            )
            for row in df.itertuples(index=False)
        ]
