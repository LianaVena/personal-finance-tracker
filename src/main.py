"""
Main entry point for the Personal Finance Tracker application.

Initializes the banking database, imports pending transaction CSV files,
and launches the NiceGUI web interface for viewing transactions.
"""

from pathlib import Path

from nicegui import app, ui

from database import create_transactions_table
from importer import import_csv_files

DB_PATH = Path(__file__).resolve().parent.parent / "banking.db"


def main():
    """Initialize the database, import pending data, and launch the UI.

    Ensures the transactions table exists, processes all CSV files
    available for import, registers shutdown hooks, constructs the
    user interface, and starts the NiceGUI local web server.
    """
    create_transactions_table(DB_PATH)

    for result in import_csv_files(DB_PATH):
        if not result.skipped:
            print(
                f"Imported {result.rows_imported} transactions "
                f"from {result.filename} ({result.bank})"
            )

    ui.label("Banking Transaction Viewer")
    ui.button("Exit application", on_click=app.shutdown)

    try:
        ui.run(
            host="127.0.0.1",
            port=8765,
            reload=False,
            show=False,
        )
    except KeyboardInterrupt:
        pass


if __name__ in {"__main__", "__mp_main__"}:
    main()
