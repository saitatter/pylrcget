from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from main import _migrate_old_nested_app_data


class AppDataMigrationTests(unittest.TestCase):
    def test_removes_empty_old_nested_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            old_nested = base / "PyLrcGet"
            old_nested.mkdir()

            _migrate_old_nested_app_data(str(base))

            self.assertFalse(old_nested.exists())

    def test_keeps_non_empty_old_nested_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            old_nested = base / "PyLrcGet"
            old_nested.mkdir()
            # "logs" exists in both locations — can't migrate, stays behind
            (base / "logs").mkdir()
            (old_nested / "logs").mkdir()

            _migrate_old_nested_app_data(str(base))

            # Old dir kept because it still contains un-migrated items
            self.assertTrue(old_nested.exists())
            self.assertTrue((old_nested / "logs").exists())
