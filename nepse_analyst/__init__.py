"""NEPSE Analyst.

``__version__`` is read from pyproject.toml, the only place the version is
written. The project runs from a checkout rather than an installed package,
so there is no package metadata to read it from.
"""

import tomllib
from pathlib import Path


def _read_version() -> str:
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    try:
        return tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "0+unknown"


__version__ = _read_version()
