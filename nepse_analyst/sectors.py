"""Canonical sector names stored in companies.sector.

Sources map their own labels to these names; everything that filters by
sector imports them from here so a label cannot drift between modules.
"""

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
    OTHERS,
)

# Instrument classes without comparable company fundamentals.
FUNDAMENTALS_EXCLUDED_SECTORS: tuple[str, ...] = (GOVERNMENT_BONDS, MUTUAL_FUNDS, CORPORATE_DEBENTURES)
