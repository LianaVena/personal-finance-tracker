"""Tests for application startup without opening databases or starting a server."""

import contextlib
import importlib
import io
import runpy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


class MainTests(unittest.TestCase):
    """Test application startup with mocked UI and isolated paths."""

    def setUp(self):
        """Install a fake NiceGUI module and import the packaged entry point."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.transactions_path = self.root / "transactions.db"
        self.finance_path = self.root / "finance.db"

        self.app = mock.Mock(name="app")
        self.ui = mock.Mock(name="ui")
        fake_nicegui = types.ModuleType("nicegui")
        fake_nicegui.app = self.app
        fake_nicegui.ui = self.ui
        patcher = mock.patch.dict(sys.modules, {"nicegui": fake_nicegui})
        patcher.start()
        self.addCleanup(patcher.stop)

        sys.modules.pop("src.main", None)
        self.main = importlib.import_module("src.main")
        self.addCleanup(lambda: sys.modules.pop("src.main", None))

    def run_main(self, results, *, matched=0, inactivated=0):
        """Run startup with mocked database work and capture its output.

        Args:
            results: Synthetic import results returned by the mocked importer.
            matched: Number of synthetic transactions updated by matching.
            inactivated: Number of synthetic subscriptions marked inactive.

        Returns:
            Captured standard output and the mocked importer.
        """
        output = io.StringIO()
        importer = mock.Mock(return_value=results)
        with mock.patch.dict(self.main.__dict__, {
            "TRANSACTIONS_DB_PATH": self.transactions_path,
            "FINANCE_DB_PATH": self.finance_path,
            "create_transactions_table": mock.Mock(),
            "create_finance_tables": mock.Mock(),
            "import_csv_files": importer,
            "apply_matching_rules": mock.Mock(return_value=matched),
            "inactivate_stale_subscriptions": mock.Mock(return_value=inactivated),
            "build_ui": mock.Mock(),
        }), contextlib.redirect_stdout(output):
            self.main.main()
        return output.getvalue(), importer

    def test_default_database_paths_are_separate(self):
        """Place the transaction and finance databases at separate paths."""
        module_file = self.main.__file__
        assert module_file is not None, "Main module has no source file"
        root = Path(module_file).resolve().parent.parent
        self.assertEqual(self.main.TRANSACTIONS_DB_PATH, root / "transactions.db")
        self.assertEqual(self.main.FINANCE_DB_PATH, root / "finance.db")

    def test_startup_validates_finance_before_transactions_or_imports(self):
        """Initialize persistent finance data before transaction imports."""
        events = []
        with mock.patch.dict(self.main.__dict__, {
            "TRANSACTIONS_DB_PATH": self.transactions_path,
            "FINANCE_DB_PATH": self.finance_path,
            "create_transactions_table": mock.Mock(
                side_effect=lambda path: events.append(("transactions", path))),
            "create_finance_tables": mock.Mock(
                side_effect=lambda path: events.append(("finance", path))),
            "import_csv_files": mock.Mock(
                side_effect=lambda path: events.append(("import", path)) or []),
            "apply_matching_rules": mock.Mock(
                side_effect=lambda transactions, finance: events.append(("categorize", transactions, finance)) or 0),
            "inactivate_stale_subscriptions": mock.Mock(
                side_effect=lambda transactions, finance: events.append(("inactivate", transactions, finance)) or 0),
            "build_ui": mock.Mock(
                side_effect=lambda transaction_path, finance_path:
                events.append(("ui", transaction_path, finance_path))),
        }), contextlib.redirect_stdout(io.StringIO()):
            self.main.main()

        self.assertEqual(events, [
            ("finance", self.finance_path),
            ("transactions", self.transactions_path),
            ("import", self.transactions_path),
            ("categorize", self.transactions_path, self.finance_path),
            ("inactivate", self.transactions_path, self.finance_path),
            ("ui", self.transactions_path, self.finance_path),
        ])

    def test_existing_finance_schema_error_stops_before_transaction_database_or_import(self):
        """Stop startup before imports when the existing finance schema is invalid."""
        transaction_initializer = mock.Mock()
        importer = mock.Mock()
        with mock.patch.dict(self.main.__dict__, {
            "TRANSACTIONS_DB_PATH": self.transactions_path,
            "FINANCE_DB_PATH": self.finance_path,
            "create_finance_tables": mock.Mock(side_effect=RuntimeError("legacy finance schema")),
            "create_transactions_table": transaction_initializer,
            "import_csv_files": importer,
        }), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "legacy finance schema"):
                self.main.main()
        transaction_initializer.assert_not_called()
        importer.assert_not_called()

    def test_reports_new_imports_and_omits_skipped_files(self):
        """Report newly imported rows without reporting skipped files."""
        output, importer = self.run_main([
            SimpleNamespace(filename="new.csv", bank="TB", rows_imported=2, skipped=False),
            SimpleNamespace(filename="old.csv", bank="FIO", rows_imported=0, skipped=True),
        ])
        importer.assert_called_once_with(self.transactions_path)
        self.assertIn("Imported 2 transactions from new.csv (TB)", output)
        self.assertNotIn("old.csv", output)

    def test_builds_interface_and_runs_locally_with_keyboard_interrupt_handling(self):
        """Start NiceGUI on localhost and handle an interrupted local run."""
        self.ui.run.side_effect = KeyboardInterrupt
        _, importer = self.run_main([])
        importer.assert_called_once_with(self.transactions_path)
        self.ui.run.assert_called_once_with(host="127.0.0.1", port=8765, reload=False, show=True)

    def test_reports_matching_and_stale_subscription_changes(self):
        """Report nonzero matching and stale-subscription updates during startup."""
        output, _ = self.run_main([], matched=2, inactivated=3)
        self.assertIn("Automatically updated matching data for 2 transactions", output)
        self.assertIn("Inactivated 3 stale subscription(s)", output)

    def test_direct_script_execution_uses_packaged_imports_and_mocked_startup(self):
        """Support IDE script execution without opening databases or starting a server."""
        module_file = self.main.__file__
        assert module_file is not None, "Main module has no source file"
        with mock.patch("src.database.create_finance_tables") as finance, \
                mock.patch("src.database.create_transactions_table"), \
                mock.patch("src.importer.import_csv_files", return_value=[]), \
                mock.patch("src.categorization.apply_matching_rules", return_value=0), \
                mock.patch("src.categorization.inactivate_stale_subscriptions", return_value=0), \
                mock.patch("src.interface.interface.build_ui") as build, \
                mock.patch.object(sys, "path", sys.path.copy()):
            runpy.run_path(module_file, run_name="__main__")
        finance.assert_called_once()
        build.assert_called_once()
        self.ui.run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
