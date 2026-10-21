"""Tests for transactions database table creation, schema constraints, and indexes."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from src.database import create_transactions_table
from src.importer import TRANSACTION_COLUMNS

MINIMAL_INSERT = (
    "INSERT INTO transactions (source_bank, booking_date, amount, currency) "
    "VALUES (?, ?, ?, ?)"
)


class CreateTransactionsTableTests(unittest.TestCase):
    """Test suite for verifying the transactions table schema and constraints."""

    def setUp(self):
        """Set up an isolated temporary database with the transactions schema."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db_path = Path(tmp.name) / "banking.db"
        create_transactions_table(self.db_path)

    def fetch(self, sql, params=()):
        """Execute a SQL query against the test database and fetch all rows.

        Args:
            sql: SQL statement to execute.
            params: Parameters for SQL query placeholders. Defaults to ().

        Returns:
            List of row tuples returned by the query.
        """
        with closing(sqlite3.connect(self.db_path)) as connection:
            return connection.execute(sql, params).fetchall()

    def insert(self, *values):
        """Insert a row using MINIMAL_INSERT into the test database.

        Args:
            *values: Values for source_bank, booking_date, amount, and currency.
        """
        with closing(sqlite3.connect(self.db_path)) as connection:
            with connection:
                connection.execute(MINIMAL_INSERT, values)

    def column_names(self):
        """Retrieve the column names of the transactions table.

        Returns:
            List of column name strings from PRAGMA table_info.
        """
        return [row[1] for row in self.fetch("PRAGMA table_info(transactions)")]

    def test_creates_table_and_indexes(self):
        """Verify that the transactions table and its indexes are created."""
        tables = {row[0] for row in self.fetch("SELECT name FROM sqlite_master WHERE type = 'table'")}
        indexes = {row[0] for row in self.fetch("SELECT name FROM sqlite_master WHERE type = 'index'")}
        self.assertIn("transactions", tables)
        self.assertIn("idx_transactions_booking_date", indexes)
        self.assertIn("idx_transactions_source_bank", indexes)

    def test_columns_match_what_the_importer_inserts(self):
        """Verify schema columns match TRANSACTION_COLUMNS to prevent drift."""
        self.assertEqual(set(self.column_names()) - {"id"}, set(TRANSACTION_COLUMNS))

    def test_calling_twice_keeps_existing_rows(self):
        """Verify that re-running table creation preserves existing records."""
        self.insert("TB", "2026-10-01", 1000, "EUR")
        create_transactions_table(self.db_path)
        self.assertEqual(self.fetch("SELECT COUNT(*) FROM transactions"), [(1,)])

    def test_accepts_str_path(self):
        """Verify that string database paths are accepted in addition to Path objects."""
        other = str(self.db_path.with_name("other.db"))
        create_transactions_table(other)
        self.assertTrue(Path(other).exists())

    def test_id_is_assigned_automatically(self):
        """Verify that the primary key id column auto-increments with each insert."""
        self.insert("TB", "2026-10-01", 1000, "EUR")
        self.insert("FIO", "2026-10-02", -500, "EUR")
        self.assertEqual(self.fetch("SELECT id FROM transactions ORDER BY id"), [(1,), (2,)])

    def test_source_bank_is_restricted_to_known_banks(self):
        """Verify that the source_bank CHECK constraint rejects unknown bank codes."""
        self.insert("FIO", "2026-10-01", 1, "EUR")
        self.insert("TB", "2026-10-01", 1, "EUR")
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert("XX", "2026-10-01", 1, "EUR")

    def test_required_columns_reject_null(self):
        """Verify that NOT NULL constraints reject missing required values."""
        for values in (("TB", None, 1, "EUR"), ("TB", "2026-10-01", None, "EUR"),
                       ("TB", "2026-10-01", 1, None), (None, "2026-10-01", 1, "EUR")):
            with self.subTest(values=values):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.insert(*values)

    def test_optional_columns_default_to_null(self):
        """Verify that optional transaction columns default to NULL when omitted."""
        self.insert("TB", "2026-10-01", 1, "EUR")
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute("SELECT * FROM transactions").fetchone()
        required = {"id", "source_bank", "booking_date", "amount", "currency"}
        for column in row.keys():
            if column not in required:
                with self.subTest(column=column):
                    self.assertIsNone(row[column])


if __name__ == "__main__":
    unittest.main()
