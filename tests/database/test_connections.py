"""Connection configuration failures close incomplete connections."""

from __future__ import annotations

import sqlite3
import unittest
from unittest.mock import Mock, patch

from src import database


class DatabaseFailureTests(unittest.TestCase):
    """Verify connection setup cleans up failures before any database is used."""

    def test_disabled_foreign_keys_close_connection_and_raise(self):
        """Close connections that cannot enforce foreign keys instead of returning them."""
        connection = Mock()
        connection.execute.return_value.fetchone.return_value = (0,)
        with patch("src.database.sqlite3.connect", return_value=connection):
            with self.assertRaisesRegex(RuntimeError, "foreign-key"):
                database.connect_database("synthetic-unused")
        connection.close.assert_called_once()

    def test_connection_configuration_failure_is_closed_and_propagated(self):
        """Close partially configured connections and preserve their original error."""
        connection = Mock()
        connection.execute.side_effect = sqlite3.DatabaseError("Synthetic setup failure")
        with patch("src.database.sqlite3.connect", return_value=connection):
            with self.assertRaisesRegex(sqlite3.DatabaseError, "Synthetic setup failure"):
                database.connect_database("synthetic-unused")
        connection.close.assert_called_once()
