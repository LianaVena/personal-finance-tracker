"""Compose the application shell and connect its pages."""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path

from nicegui import app, ui

from src.database import connect_database
from .coordinator import UiCoordinator
from .styles import apply_styles


def build_ui(transaction_db_path: Path, finance_db_path: Path) -> None:
    """Build the Review, Subscriptions, and Manage tabs with isolated page state."""
    apply_styles()
    ui.page_title("Personal Finance Tracker")
    ui.colors(primary="#176b5b", secondary="#d8a24a", accent="#b4543b")
    with ui.column().classes("w-full max-w-none mx-auto px-2 py-6 gap-5"):
        with ui.row().classes("w-full items-center justify-between flex-wrap gap-4"):
            with ui.tabs().classes("w-auto flex-none justify-start") as page_tabs:
                review_tab = ui.tab("Review", icon="receipt_long")
                subscriptions_tab = ui.tab("Subscriptions", icon="autorenew")
                management_tab = ui.tab("Manage", icon="settings")
            exit_status = ui.label("").classes("text-sm text-slate-400")

            async def exit_app() -> None:
                """Check database integrity, then close the app and browser tab."""
                exit_button.disable()
                exit_status.set_text("Checking saved data…")
                try:
                    for database_path in (transaction_db_path, finance_db_path):
                        with closing(connect_database(database_path)) as connection:
                            result_row = connection.execute("PRAGMA integrity_check").fetchone()
                            if result_row is None:
                                raise sqlite3.DatabaseError("Integrity check returned no result")
                            result = result_row[0]
                        if result != "ok":
                            raise sqlite3.DatabaseError(f"Integrity check failed: {result}")
                    exit_status.set_text("All changes are saved. Closing this tab…")
                    await ui.run_javascript(
                        "window.close(); setTimeout(() => { if (!window.closed) "
                        "window.location.replace('about:blank'); }, 300);"
                    )
                    await asyncio.sleep(1)
                    app.shutdown()
                except Exception as error:
                    exit_status.set_text(f"Could not exit safely: {error}")
                    exit_button.enable()

            exit_button = ui.button("Exit", on_click=exit_app).props("outline rounded icon=logout")

        with ui.tab_panels(page_tabs, value=review_tab).classes("w-full"):
            with ui.tab_panel(review_tab):
                with ui.element("div").classes("w-full grid grid-cols-1 md:grid-cols-2 gap-4 items-start"):
                    transaction_content = ui.column().classes("w-full min-w-0 gap-5")
                    creation_content = ui.column().classes("w-full min-w-0 gap-5")
            with ui.tab_panel(subscriptions_tab):
                subscriptions_content = ui.column().classes("w-full min-w-0 gap-5")
            with ui.tab_panel(management_tab):
                management_content = ui.column().classes("w-full min-w-0 gap-5")

    coordinator = UiCoordinator(
        transaction_db_path, finance_db_path, transaction_content, creation_content,
        management_content, subscriptions_content,
    )
    coordinator.render_initial()
