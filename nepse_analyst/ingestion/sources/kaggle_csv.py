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


def _nan_to_none(value: object) -> float | None:
    return None if pd.isna(value) else float(value)


class KaggleCsvCompanySource:
    name = "kaggle-csv"

    def __init__(self, csv_path: str | Path = DEFAULT_CSV_PATH) -> None:
        self.csv_path = Path(csv_path)

    def fetch_companies(self) -> list[Company]:
        if not self.csv_path.exists():
            raise FileNotFoundError(f"Company CSV not found at {self.csv_path}")

        df = pd.read_csv(self.csv_path)
        df = df.rename(columns={c: c.strip().lower().replace(" ", "_") for c in df.columns})
        missing = [c for c in _COLUMN_MAPPING if c not in df.columns]
        if missing:
            raise ValueError(f"Missing expected CSV columns: {missing}")
        df = df[list(_COLUMN_MAPPING)].rename(columns=_COLUMN_MAPPING)

        for col in ("symbol", "name", "sector"):
            df[col] = df[col].astype(str).str.strip()
        df["symbol"] = df["symbol"].str.upper()
        df["sector"] = df["sector"].replace(SECTOR_MAP)
        df["listed_shares"] = pd.to_numeric(df["listed_shares"], errors="coerce").fillna(0).astype(int)
        df["paid_up_value"] = pd.to_numeric(df["paid_up_value"], errors="coerce")
        df["total_paid_up"] = pd.to_numeric(df["total_paid_up"], errors="coerce")
        df = df.drop_duplicates(subset=["symbol"], keep="first")

        return [
            Company(
                symbol=row.symbol,
                name=row.name,
                sector=row.sector,
                listed_shares=int(row.listed_shares),
                paid_up_value=_nan_to_none(row.paid_up_value),
                total_paid_up=_nan_to_none(row.total_paid_up),
            )
            for row in df.itertuples(index=False)
        ]
