"""
Main entry point for the Personal Finance Tracker application.

Initializes separate transaction and finance databases, imports bank CSV files,
and launches NiceGUI for reviewing transactions and managing finance data.
"""

import sys
from pathlib import Path

# Keep direct execution from PyCharm working while importing the application
# consistently as the ``src`` package.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nicegui import ui

from src.database import create_transactions_table, create_finance_tables
from src.importer import import_csv_files
from src.categorization import apply_matching_rules, inactivate_stale_subscriptions
from src.interface.interface import build_ui

ROOT_DIR = Path(__file__).resolve().parent.parent
TRANSACTIONS_DB_PATH = ROOT_DIR / "transactions.db"
FINANCE_DB_PATH = ROOT_DIR / "finance.db"


def main():
    """Initialize both databases, import CSV files, and launch NiceGUI.

    Protect the persistent finance database before touching imports or the
    rebuildable transaction database.
    """
    create_finance_tables(FINANCE_DB_PATH)
    create_transactions_table(TRANSACTIONS_DB_PATH)

    for result in import_csv_files(TRANSACTIONS_DB_PATH):
        if not result.skipped:
            print(
                f"Imported {result.rows_imported} transactions "
                f"from {result.filename} ({result.bank})"
            )

    automatically_updated = apply_matching_rules(TRANSACTIONS_DB_PATH, FINANCE_DB_PATH)
    if automatically_updated:
        print(f"Automatically updated matching data for {automatically_updated} transactions")

    inactivated = inactivate_stale_subscriptions(TRANSACTIONS_DB_PATH, FINANCE_DB_PATH)
    if inactivated:
        print(f"Inactivated {inactivated} stale subscription(s)")

    build_ui(TRANSACTIONS_DB_PATH, FINANCE_DB_PATH)

    try:
        ui.run(
            host="127.0.0.1",
            port=8765,
            reload=False,
            show=True,
        )
    except KeyboardInterrupt:
        pass


if __name__ in {"__main__", "__mp_main__"}:
    main()
