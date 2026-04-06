"""
Compatibility re-exports.

Keep existing imports (from db.database import ...) working while the DB module is split
into migrations + queries.
"""

from __future__ import annotations

# Public DB version (single source of truth for the app)
CURRENT_DB_VERSION = 7

from db.migrations import initialize_database, upgrade_database_if_needed
from db.queries import *  # noqa: F403
