from __future__ import annotations

import unittest
from pathlib import Path


class ModuleLayoutTests(unittest.TestCase):
    def test_root_package_only_keeps_package_files(self) -> None:
        root = Path(__file__).resolve().parents[1] / "src"
        names = sorted(path.name for path in root.glob("*.py"))
        self.assertEqual(names, ["__init__.py", "__main__.py"])
