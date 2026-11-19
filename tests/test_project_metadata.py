import ast
import importlib.metadata
import re
import sys
import tomllib
import unittest
from pathlib import Path

import app
import nepse_analyst

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
LOCAL = {"nepse_analyst", "app", "tests"}


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _imported_top_level_modules() -> set[str]:
    modules = set()
    paths = [ROOT / "app.py", *(ROOT / "nepse_analyst").rglob("*.py"), *(ROOT / "scripts").rglob("*.py")]
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules.add(node.module.split(".")[0])
    return {m for m in modules if m not in sys.stdlib_module_names and m not in LOCAL}


class ProjectMetadataTests(unittest.TestCase):
    def test_one_version_number(self) -> None:
        version = PYPROJECT["project"]["version"]
        self.assertEqual(nepse_analyst.__version__, version)
        self.assertEqual(app.app.version, version)

    def test_every_imported_package_is_declared(self) -> None:
        declared = {
            _normalize(re.split(r"[\s\[<>=!~;]", requirement, maxsplit=1)[0])
            for requirement in PYPROJECT["project"]["dependencies"]
        }
        providers = importlib.metadata.packages_distributions()
        undeclared = {}
        for module in sorted(_imported_top_level_modules()):
            distributions = {_normalize(d) for d in providers.get(module, [module])}
            if not distributions & declared:
                undeclared[module] = sorted(distributions)
        self.assertEqual(undeclared, {})


if __name__ == "__main__":
    unittest.main()
