"""Data ingestion: pluggable sources behind one Loader."""

from nepse_analyst.ingestion.loader import STEPS, Loader, Sources, default_sources

__all__ = ["STEPS", "Loader", "Sources", "default_sources"]
