"""Synthetic-only tests for connection helpers and the finance v2 schema."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from src.database import connect_database, create_finance_tables, create_transactions_table, initialize_database


class DatabaseTests(unittest.TestCase):
    """Verify database schemas and constraints using temporary files only."""

    def setUp(self):
        """Allocate a fresh path for each synthetic database test."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "synthetic.db"

    def test_connection_enables_foreign_keys(self):
        """Enable SQLite foreign-key checks on every managed connection."""
        with closing(connect_database(self.path)) as connection:
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)

    def test_transaction_schema_remains_independent_and_hash_keyed(self):
        """Keep imported transaction storage independent and hash-keyed."""
        create_transactions_table(self.path)
        with closing(connect_database(self.path)) as connection:
            columns = {row[1]: row for row in connection.execute("PRAGMA table_info(transactions)")}
            indexes = {row[1] for row in connection.execute("PRAGMA index_list(transactions)")}
            self.assertEqual(columns["id"][2].upper(), "TEXT")
            self.assertEqual(columns["id"][3], 1)
            self.assertIn("idx_transactions_booking_date", indexes)
            self.assertIn("idx_transactions_source_bank", indexes)

    def test_finance_v2_has_the_declared_tables_and_columns(self):
        """Create the expected v2 tables and columns for a new finance database."""
        create_finance_tables(self.path)
        expected = {
            "categories": {"id", "name"},
            "colors": {"id", "row_hex", "pie_hex", "name"},
            "subcategories": {"id", "category_id", "name", "color_id"},
            "counterparties": {"id", "name", "default_subcategory_id", "default_is_subscription"},
            "counterparties_match_rules": {"id", "counterparty_id", "source_field", "pattern"},
            "subscriptions": {
                "id", "name", "counterparty_id", "billing_period", "expected_amount", "currency", "is_active",
            },
            "subscription_match_rules": {"id", "subscription_id", "source_field", "pattern"},
            "transaction_metadata": {"transaction_id", "note", "counterparty_id", "counterparty_is_manual"},
            "transaction_splits": {
                "id", "transaction_id", "amount", "subcategory_id", "subcategory_is_manual", "note",
                "is_subscription", "subscription_id", "subscription_is_manual", "excluded",
            },
        }
        with closing(connect_database(self.path)) as connection:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            self.assertEqual(tables, set(expected))
            for table, expected_columns in expected.items():
                actual = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
                self.assertEqual(actual, expected_columns, table)
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)

    def test_categories_counterparties_and_rules_enforce_constraints(self):
        """Reject duplicate names, invalid defaults, and unsupported rule fields."""
        create_finance_tables(self.path)
        with closing(connect_database(self.path)) as connection:
            connection.execute("INSERT INTO categories(name) VALUES ('Food')")
            connection.execute("INSERT INTO subcategories(category_id, name) VALUES (1, 'Groceries')")
            connection.execute("INSERT INTO counterparties(name, default_subcategory_id, default_is_subscription) "
                               "VALUES ('Market', 1, 0)")
            connection.execute("INSERT INTO counterparties_match_rules(counterparty_id, pattern) "
                               "VALUES (1, 'SHOP')")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO categories(name) VALUES ('food')")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO subcategories(category_id, name) VALUES (1, 'groceries')")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO counterparties(name, default_is_subscription) VALUES ('Bad', 2)")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO counterparties_match_rules(counterparty_id, source_field, pattern) "
                                   "VALUES (1, 'amount', '5')")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO counterparties_match_rules(counterparty_id, pattern) "
                                   "VALUES (1, 'shop')")

    def test_subscriptions_require_signature_pair_and_valid_period_currency(self):
        """Enforce valid billing periods and paired amount/currency values."""
        create_finance_tables(self.path)
        with closing(connect_database(self.path)) as connection:
            connection.execute("INSERT INTO subscriptions(name, billing_period) VALUES ('Music', 'monthly')")
            connection.execute("INSERT INTO subscriptions(name, billing_period, expected_amount, currency) "
                               "VALUES ('Video', 'yearly', -500, 'EUR')")
            for sql, values in [
                ("INSERT INTO subscriptions(name, billing_period) VALUES ('Bad period', 'weekly')", ()),
                ("INSERT INTO subscriptions(name, billing_period, expected_amount) "
                 "VALUES ('No currency', 'monthly', -500)", ()),
                ("INSERT INTO subscriptions(name, billing_period, currency) "
                 "VALUES ('No amount', 'monthly', 'EUR')", ()),
                ("INSERT INTO subscriptions(name, billing_period, expected_amount, currency) "
                 "VALUES ('Bad code', 'monthly', -500, 'eu1')", ()),
                ("INSERT INTO subscriptions(name, billing_period, expected_amount, currency) "
                 "VALUES ('Zero', 'monthly', 0, 'EUR')", ()),
            ]:
                with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(sql, values)

    def test_metadata_hash_and_manual_counterparty_pair_are_checked(self):
        """Validate transaction hash length and counterparty provenance pairing."""
        create_finance_tables(self.path)
        with closing(connect_database(self.path)) as connection:
            connection.execute("INSERT INTO counterparties(name) VALUES ('Shop')")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO transaction_metadata(transaction_id) VALUES ('short')")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO transaction_metadata(transaction_id, counterparty_id) "
                                   "VALUES (?, 1)", ("a" * 64,))
            connection.execute("INSERT INTO transaction_metadata(transaction_id, counterparty_id, "
                               "counterparty_is_manual) VALUES (?, 1, 0)", ("b" * 64,))

    def test_splits_enforce_provenance_and_foreign_key_rules(self):
        """Enforce split values, provenance, and protected references."""
        create_finance_tables(self.path)
        with closing(connect_database(self.path)) as connection:
            connection.execute("INSERT INTO categories(name) VALUES ('Food')")
            connection.execute("INSERT INTO subcategories(category_id, name) VALUES (1, 'Meals')")
            connection.execute("INSERT INTO subscriptions(name, billing_period) VALUES ('Video', 'monthly')")
            transaction_id = "c" * 64
            connection.execute("INSERT INTO transaction_metadata(transaction_id) VALUES (?)", (transaction_id,))
            connection.execute("INSERT INTO transaction_splits(transaction_id, amount) VALUES (?, -500)",
                               (transaction_id,))
            connection.execute("INSERT INTO transaction_splits(transaction_id, amount, subcategory_id, "
                               "subcategory_is_manual, is_subscription, subscription_id, "
                               "subscription_is_manual) VALUES (?, -500, 1, 1, 1, 1, 0)",
                               (transaction_id,))
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO transaction_splits(transaction_id, amount) VALUES (?, 0)",
                                   (transaction_id,))
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO transaction_splits(transaction_id, amount, subcategory_id) "
                                   "VALUES (?, -1, 1)", (transaction_id,))
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO transaction_splits(transaction_id, amount, is_subscription) "
                                   "VALUES (?, -1, 0)", (transaction_id,))
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM subcategories WHERE id = 1")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM subscriptions WHERE id = 1")

    def test_existing_non_v2_database_is_rejected_without_changes(self):
        """Leave an unrelated existing database untouched and report incompatibility."""
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("CREATE TABLE legacy_data (value TEXT)")
            connection.execute("INSERT INTO legacy_data VALUES ('keep')")
        with self.assertRaisesRegex(RuntimeError, "left unchanged"):
            create_finance_tables(self.path)
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT value FROM legacy_data").fetchone()[0], "keep")
            self.assertIsNone(connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'transaction_splits'").fetchone())

    def test_initialization_is_idempotent_and_rejects_unknown_schema(self):
        """Allow repeat initialization while rejecting unknown schema paths."""
        transaction_path = self.path.with_name("transactions.db")
        finance_path = self.path.with_name("finance.db")
        create_transactions_table(transaction_path)
        create_finance_tables(self.path)
        create_transactions_table(transaction_path)
        create_finance_tables(finance_path)
        with self.assertRaises(ValueError):
            initialize_database(self.path, "../finance.db")

    def test_finance_initializer_accepts_existing_empty_sqlite_database(self):
        """Initialize a nonempty SQLite container that has no application tables."""
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("PRAGMA user_version = 1")
        initialize_database(self.path, "finance.sql")
        with closing(connect_database(self.path)) as connection:
            self.assertIsNotNone(connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'transaction_splits'",
            ).fetchone())

    def test_matching_table_names_with_unexpected_columns_are_left_unchanged(self):
        """Reject changed column layouts without recreating or rewriting their tables."""
        create_finance_tables(self.path)
        with closing(connect_database(self.path)) as connection:
            connection.execute("ALTER TABLE categories ADD COLUMN custom_note TEXT")
        with self.assertRaisesRegex(RuntimeError, "left unchanged"):
            create_finance_tables(self.path)
        with closing(connect_database(self.path)) as connection:
            self.assertIn("custom_note", {row[1] for row in connection.execute("PRAGMA table_info(categories)")})


if __name__ == "__main__":
    unittest.main()
