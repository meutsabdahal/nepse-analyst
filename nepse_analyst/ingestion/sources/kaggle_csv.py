"""Company master list from the bundled Kaggle CSV."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from nepse_analyst import sectors
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

# Kaggle sector labels -> canonical sector names.
SECTOR_MAP = {
    "Commercial Banks": sectors.COMMERCIAL_BANKS,
    "Hydro Power": sectors.HYDROPOWER,
    "Life Insurance": sectors.LIFE_INSURANCE,
    "Development Bank Limited": sectors.DEVELOPMENT_BANKS,
    "Finance": sectors.FINANCE_COMPANIES,
    "Microfinance": sectors.MICROFINANCE,
    "Non-Life Insurance": sectors.NON_LIFE_INSURANCE,
    "Hotels And Tourism": sectors.HOTELS_AND_TOURISM,
    "Manufacturing And Processing": sectors.MANUFACTURING,
    "Tradings": sectors.TRADING,
    "Mutual Fund": sectors.MUTUAL_FUNDS,
    "Investment": sectors.INVESTMENT,
    "Others": sectors.OTHERS,
    "Corporate Debenture": sectors.CORPORATE_DEBENTURES,
    "Government Bond": sectors.GOVERNMENT_BONDS,
    "Capital": sectors.OTHERS,
    "Promotor Share": sectors.PROMOTER_SHARES,
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
        unmapped = sorted(set(df["sector"]) - SECTOR_MAP.keys())
        if unmapped:
            raise ValueError(f"Unmapped sector labels in {self.csv_path.name}: {unmapped}")
        df["sector"] = df["sector"].map(SECTOR_MAP)
        # A few promoter listings are filed under another label; their names say so.
        promoter = [sectors.is_promoter_share(n, s) for n, s in zip(df["name"], df["sector"])]
        df.loc[promoter, "sector"] = sectors.PROMOTER_SHARES
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
