from __future__ import annotations

import logging
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

    def test_removes_non_empty_old_nested_directory_without_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            old_nested = base / "PyLrcGet"
            old_nested.mkdir()
            (base / "logs").mkdir()
            (old_nested / "logs").mkdir()

            records: list[logging.LogRecord] = []

            class CaptureHandler(logging.Handler):
                def emit(self, record: logging.LogRecord) -> None:
                    records.append(record)

            handler = CaptureHandler()
            root = logging.getLogger()
            previous_level = root.level
            root.addHandler(handler)
            root.setLevel(logging.INFO)
            try:
                _migrate_old_nested_app_data(str(base))
            finally:
                root.removeHandler(handler)
                root.setLevel(previous_level)

            self.assertFalse(old_nested.exists())
            warnings = [record for record in records if record.levelno >= logging.WARNING]
            self.assertEqual(warnings, [])
