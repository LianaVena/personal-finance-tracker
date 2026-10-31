"""Palette, current schema, and compatibility checks using only in-memory SQLite."""

import sqlite3
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.database import create_finance_tables
from src.interface.manage import tables as manage_tables
from src.subcategory_colors import (
    DEFAULT_SUBCATEGORY_COLOR, normalize_subcategory_color, sort_subcategory_colors,
)

SQL_ROOT = Path(__file__).resolve().parents[2] / "src" / "sql"


class SubcategoryColorTests(unittest.TestCase):
    """Verify color storage and schema validation without opening a database file."""

    def setUp(self):
        """Create an in-memory database and load the current public schema."""
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.schema = (SQL_ROOT / "finance.sql").read_text(encoding="utf-8")
        self.colors = [
            (31, "#FF0000", "#AA0000", "Test Red"), (32, "#00FF00", "#00AA00", "Test Green"),
            (33, "#0000FF", "#0000AA", "Test Blue"), (34, "#808080", "#606060", "Test Gray"),
        ]

    def assert_startup_rejects_schema(self, expected_message: str) -> None:
        """Verify startup rejects an incompatible schema without modifying its contents.

        Args:
            expected_message: Error message fragment identifying the incompatible schema.
        """
        before = tuple(self.connection.iterdump())
        wrapped = MagicMock(wraps=self.connection)
        wrapped.close.return_value = None
        with patch("src.database.connect_database", return_value=wrapped), \
                patch.object(Path, "exists", return_value=True), \
                patch.object(Path, "stat", return_value=SimpleNamespace(st_size=1024)):
            with self.assertRaisesRegex(RuntimeError, expected_message):
                create_finance_tables(Path("synthetic-finance"))
        self.assertEqual(tuple(self.connection.iterdump()), before)

    def test_colors_sort_by_hue_and_normalize_database_ids(self):
        """Sort database colors by hue and validate IDs against loaded rows."""
        self.assertIsNone(DEFAULT_SUBCATEGORY_COLOR)
        unordered = [self.colors[2], self.colors[3], self.colors[1], self.colors[0]]
        self.assertEqual(sort_subcategory_colors(unordered), self.colors)
        for color_id, _, _, _ in self.colors:
            self.assertEqual(normalize_subcategory_color(color_id, self.colors), color_id)
        for blank in (None, "", "  "):
            self.assertIsNone(normalize_subcategory_color(blank, self.colors))
        for invalid in (999, "not a database ID"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                normalize_subcategory_color(invalid, self.colors)

    def test_new_schema_stores_color_ids_and_defaults_to_no_color(self):
        """Store color IDs in subcategories and keep the color lookup table empty by default."""
        self.connection.executescript(self.schema)
        self.connection.execute("INSERT INTO categories(id, name) VALUES (1, 'Food')")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM colors").fetchone(), (0,))
        self.connection.executemany("INSERT INTO colors(id, row_hex, pie_hex, name) VALUES (?, ?, ?, ?)", self.colors)
        self.connection.execute("INSERT INTO subcategories(category_id, name) VALUES (1, 'Default')")
        self.assertEqual(self.connection.execute(
            "SELECT color_id FROM subcategories WHERE name = 'Default'",
        ).fetchone(), (DEFAULT_SUBCATEGORY_COLOR,))
        for color_id, _, _, name in self.colors:
            self.connection.execute(
                "INSERT INTO subcategories(category_id, name, color_id) VALUES (1, ?, ?)", (name, color_id),
            )
        actual = dict(self.connection.execute("SELECT id, row_hex FROM colors ORDER BY id"))
        self.assertEqual(actual, {color_id: row_hex for color_id, row_hex, _, _ in self.colors})
        actual_pie = dict(self.connection.execute("SELECT id, pie_hex FROM colors ORDER BY id"))
        self.assertEqual(actual_pie, {color_id: pie_hex for color_id, _, pie_hex, _ in self.colors})
        actual_names = dict(self.connection.execute("SELECT id, name FROM colors ORDER BY id"))
        self.assertEqual(actual_names, {color_id: name for color_id, _, _, name in self.colors})

    def test_picker_colors_are_loaded_from_database_and_sorted(self):
        """Load picker options from SQLite and return them in hue order."""
        self.connection.executescript(self.schema)
        self.connection.executemany(
            "INSERT INTO colors(id, row_hex, pie_hex, name) VALUES (?, ?, ?, ?)",
            [self.colors[2], self.colors[3], self.colors[1], self.colors[0]],
        )
        wrapped = MagicMock(wraps=self.connection)
        wrapped.close.return_value = None
        with patch.dict(vars(manage_tables), {"connect_database": MagicMock(return_value=wrapped)}):
            self.assertEqual(manage_tables.colors(Path("synthetic-finance")), self.colors)

    def test_startup_accepts_current_schema_without_rewriting_saved_colors(self):
        """Accept repeated startup validation while preserving current records and colors."""
        self.connection.executescript(self.schema)
        self.connection.execute("INSERT INTO categories(id, name) VALUES (1, 'Food')")
        self.connection.executemany("INSERT INTO colors(id, row_hex, pie_hex, name) VALUES (?, ?, ?, ?)", self.colors)
        self.connection.execute(
            "INSERT INTO subcategories(category_id, name, color_id) VALUES (1, 'Meals', 31)",
        )
        self.connection.commit()
        before = tuple(self.connection.iterdump())
        wrapped = MagicMock(wraps=self.connection)
        wrapped.close.return_value = None
        with patch("src.database.connect_database", return_value=wrapped), \
                patch.object(Path, "exists", return_value=True), \
                patch.object(Path, "stat", return_value=SimpleNamespace(st_size=1024)):
            create_finance_tables(Path("synthetic-finance"))
            create_finance_tables(Path("synthetic-finance"))
        self.assertEqual(tuple(self.connection.iterdump()), before)

    def test_schema_accepts_no_color_and_rejects_unknown_color_ids(self):
        """Accept null colors while enforcing color references."""
        self.connection.executescript(self.schema)
        self.connection.execute("INSERT INTO categories(id, name) VALUES (1, 'Food')")
        self.connection.execute(
            "INSERT INTO subcategories(category_id, name, color_id) VALUES (1, 'No color', NULL)",
        )
        self.assertIsNone(self.connection.execute("SELECT color_id FROM subcategories").fetchone()[0])
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "INSERT INTO subcategories(category_id, name, color_id) VALUES (1, 'Invalid', 999)",
            )

    def test_startup_rejects_schema_without_colors_without_changes(self):
        """Reject the former hex-column schema without changing its contents."""
        self.connection.executescript(
            "CREATE TABLE categories(id INTEGER PRIMARY KEY, name TEXT); "
            "CREATE TABLE subcategories(id INTEGER PRIMARY KEY, category_id INTEGER, name TEXT, color TEXT); "
            "INSERT INTO categories VALUES (1, 'Food'); "
            "INSERT INTO subcategories VALUES (1, 1, 'Meals', '#123456');"
        )
        self.connection.commit()
        self.assert_startup_rejects_schema("not the expected finance schema")

    def test_startup_rejects_missing_subcategory_color_id_without_changes(self):
        """Reject a lookup-table schema missing its subcategory foreign-key column."""
        self.connection.executescript(self.schema)
        self.connection.execute("ALTER TABLE subcategories DROP COLUMN color_id")
        self.connection.execute("INSERT INTO categories(id, name) VALUES (1, 'Food')")
        self.connection.execute("INSERT INTO subcategories(category_id, name) VALUES (1, 'Meals')")
        self.connection.commit()
        self.assert_startup_rejects_schema("missing subcategory colors")
