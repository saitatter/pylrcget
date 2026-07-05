from __future__ import annotations

import logging
import unittest

from tests import test_support as _test_support  # noqa: F401
from ui.services.logging_preferences import apply_logging_verbosity


class LoggingPreferencesTests(unittest.TestCase):
    def test_apply_logging_verbosity_updates_root_and_handlers(self):
        root = logging.getLogger()
        old_level = root.level
        handler = logging.StreamHandler()
        old_handler_level = handler.level
        root.addHandler(handler)
        try:
            level = apply_logging_verbosity("debug")
            self.assertEqual(level, logging.DEBUG)
            self.assertEqual(root.level, logging.DEBUG)
            self.assertEqual(handler.level, logging.DEBUG)
        finally:
            root.removeHandler(handler)
            root.setLevel(old_level)
            handler.setLevel(old_handler_level)
