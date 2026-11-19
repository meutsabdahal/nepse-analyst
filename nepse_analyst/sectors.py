"""Canonical sector names stored in companies.sector.

Sources map their own labels to these names; everything that filters by
sector imports them from here so a label cannot drift between modules.
"""

import re

COMMERCIAL_BANKS = "Commercial Banks"
DEVELOPMENT_BANKS = "Development Banks"
FINANCE_COMPANIES = "Finance Companies"
MICROFINANCE = "Microfinance"
HYDROPOWER = "Hydropower"
LIFE_INSURANCE = "Life Insurance"
NON_LIFE_INSURANCE = "Non-Life Insurance"
HOTELS_AND_TOURISM = "Hotels & Tourism"
MANUFACTURING = "Manufacturing"
TRADING = "Trading"
INVESTMENT = "Investment"
MUTUAL_FUNDS = "Mutual Funds"
CORPORATE_DEBENTURES = "Corp. Debentures"
GOVERNMENT_BONDS = "Govt. Bonds"
PROMOTER_SHARES = "Promoter Shares"
OTHERS = "Others"

ALL_SECTORS: tuple[str, ...] = (
    COMMERCIAL_BANKS,
    DEVELOPMENT_BANKS,
    FINANCE_COMPANIES,
    MICROFINANCE,
    HYDROPOWER,
    LIFE_INSURANCE,
    NON_LIFE_INSURANCE,
    HOTELS_AND_TOURISM,
    MANUFACTURING,
    TRADING,
    INVESTMENT,
    MUTUAL_FUNDS,
    CORPORATE_DEBENTURES,
    GOVERNMENT_BONDS,
    PROMOTER_SHARES,
    OTHERS,
)

# Both spellings occur in listing names ("Promoter Share", "Promotor Share").
_PROMOTER_NAME = re.compile(r"\bpromot[eo]r\b", re.IGNORECASE)


def is_promoter_share(name: str | None, sector: str | None) -> bool:
    """Promoter (locked-in founder) shares, by sector or by listing name.

    Not by symbol: promoter symbols end in "P" or "PO", but so can ordinary
    listings (NADEP is a microfinance company).
    """
    return sector == PROMOTER_SHARES or bool(_PROMOTER_NAME.search(name or ""))


# Sector labels on Merolagani's company list. The bundled Kaggle CSV is a
# snapshot of that page and uses the same labels.
LISTING_SECTOR_LABELS: dict[str, str] = {
    "Commercial Banks": COMMERCIAL_BANKS,
    "Hydro Power": HYDROPOWER,
    "Life Insurance": LIFE_INSURANCE,
    "Development Bank Limited": DEVELOPMENT_BANKS,
    "Finance": FINANCE_COMPANIES,
    "Microfinance": MICROFINANCE,
    "Non-Life Insurance": NON_LIFE_INSURANCE,
    "Hotels And Tourism": HOTELS_AND_TOURISM,
    "Manufacturing And Processing": MANUFACTURING,
    "Tradings": TRADING,
    "Mutual Fund": MUTUAL_FUNDS,
    "Investment": INVESTMENT,
    "Others": OTHERS,
    "Corporate Debenture": CORPORATE_DEBENTURES,
    "Government Bond": GOVERNMENT_BONDS,
    "Capital": OTHERS,
    "Promotor Share": PROMOTER_SHARES,
}


def sector_from_listing(label: str, name: str | None) -> str | None:
    """Canonical sector for a listing label, or None if the label is unknown.

    A few promoter listings are filed under another label; their names say so.
    """
    sector = LISTING_SECTOR_LABELS.get(label.strip())
    if sector is None:
        return None
    return PROMOTER_SHARES if is_promoter_share(name, sector) else sector


# Instrument classes without comparable company fundamentals.
FUNDAMENTALS_EXCLUDED_SECTORS: tuple[str, ...] = (GOVERNMENT_BONDS, MUTUAL_FUNDS, CORPORATE_DEBENTURES)
