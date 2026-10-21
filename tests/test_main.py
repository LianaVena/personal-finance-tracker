"""
Tests for main.py.

nicegui is replaced by a fake module, so these tests never start a web server
and do not need nicegui to be installed.
"""

import contextlib
import importlib
import io
import sqlite3
import sys
import tempfile
import types
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from src.importer import ImportResult


class MainTests(unittest.TestCase):
    """Test the application's startup and main entry point."""

    def setUp(self):
        """Load main with a fake NiceGUI module and a temporary database path."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db_path = Path(tmp.name) / "banking.db"

        self.app = mock.Mock(name="app")
        self.ui = mock.Mock(name="ui")
        fake_nicegui = types.ModuleType("nicegui")
        fake_nicegui.app = self.app
        fake_nicegui.ui = self.ui

        patcher = mock.patch.dict(sys.modules, {"nicegui": fake_nicegui})
        patcher.start()
        self.addCleanup(patcher.stop)

        sys.modules.pop("main", None)
        self.main = importlib.import_module("main")
        self.addCleanup(lambda: sys.modules.pop("main", None))

    def run_main(self, results):
        """Run main with mocked import results and capture its console output."""
        output = io.StringIO()
        importer_mock = mock.Mock(return_value=results)
        with mock.patch.dict(self.main.__dict__, {
            "DB_PATH": self.db_path,
            "import_csv_files": importer_mock,
        }), contextlib.redirect_stdout(output):
            self.main.main()
        return output.getvalue(), importer_mock

    def test_db_path_is_banking_db_next_to_the_src_folder(self):
        """Place the default database beside the source directory."""
        module_file = self.main.__file__
        if module_file is None:
            self.fail("The imported main module has no file path")
        expected = Path(module_file).resolve().parent.parent / "banking.db"
        self.assertEqual(self.main.DB_PATH, expected)

    def test_importing_the_module_does_not_start_anything(self):
        """Avoid starting the UI or registering shutdown work on import."""
        self.ui.run.assert_not_called()
        self.app.on_shutdown.assert_not_called()

    def test_main_creates_the_table_before_importing(self):
        """Create the transactions table and pass the configured path to import."""
        _, importer_mock = self.run_main([])
        importer_mock.assert_called_once_with(self.db_path)
        with closing(sqlite3.connect(self.db_path)) as connection:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertIn("transactions", tables)

    def test_main_reports_imported_files_but_not_skipped_ones(self):
        """Print summaries for imported files and omit skipped files."""
        output, _ = self.run_main([
            ImportResult("a.csv", "TB", 3),
            ImportResult("b.csv", "FIO", 0, skipped=True),
            ImportResult("c.csv", "FIO", 1),
        ])
        self.assertIn("Imported 3 transactions from a.csv (TB)", output)
        self.assertIn("Imported 1 transactions from c.csv (FIO)", output)
        self.assertNotIn("b.csv", output)

    def test_main_builds_the_page_and_runs_the_server_on_localhost(self):
        """Build the exit control and run NiceGUI on the expected local address."""
        self.run_main([])
        self.ui.label.assert_called_once_with("Banking Transaction Viewer")
        self.ui.button.assert_called_once_with("Exit application", on_click=self.app.shutdown)
        self.ui.run.assert_called_once_with(host="127.0.0.1", port=8765, reload=False, show=False)

    def test_shutdown_hook_is_registered_and_prints_a_message(self):
        """Register the shutdown callback and print its stop message."""
        self.run_main([])
        self.app.on_shutdown.assert_called_once_with(self.main.on_shutdown)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.main.on_shutdown()
        self.assertEqual(output.getvalue().strip(), "Banking application stopped.")


if __name__ == "__main__":
    unittest.main()
