"""Management matching-rule editors and callbacks."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from nicegui import ui

from .edits import add_rule as _add_rule, delete_rule as _delete_rule, update_rule as _update_rule
from .tables import rules as _rules
from ..context import RULE_FIELDS

if TYPE_CHECKING:
    from .page import ManagePage


def render_management_rules(page: ManagePage, table_name: str, owner_column: str, owner_id: int) -> None:
    """Render editable matching rules for the selected managed record.

    Args:
        page: Manage page supplying database paths and refresh callbacks.
        table_name: Counterparty or subscription rule table.
        owner_column: Foreign-key column identifying the selected record.
        owner_id: ID of the selected counterparty or subscription.
    """
    rules = _rules(page.finance_db_path, table_name, owner_column, owner_id)
    with ui.column().classes("w-full gap-2 mt-3"):
        ui.label("Matching rules").classes("font-medium")
        for rule_id, source_field, pattern_text in rules:
            with ui.row().classes("w-full items-end gap-2"):
                source = ui.select(RULE_FIELDS, value=source_field).classes("w-44")
                pattern = ui.input(value=pattern_text).classes("flex-1")

                def save_rule(saved_rule_id=rule_id, source_input=source, pattern_input=pattern):
                    """Save the edited matching rule.

                    Args:
                        saved_rule_id: ID of the rule being edited.
                        source_input: Control containing the selected source field.
                        pattern_input: Control containing the match pattern.
                    """
                    try:
                        _update_rule(page.finance_db_path, table_name, owner_column, owner_id,
                                     saved_rule_id, source_input.value, pattern_input.value or "")
                        ui.notify("Matching rule updated", type="positive")
                        page.actions.refresh_matching()
                        page.render_management()
                        page.actions.render_transactions()
                    except (sqlite3.Error, ValueError) as error:
                        ui.notify(str(error), type="warning")

                ui.button(icon="save", on_click=save_rule).props(
                    "round outline").tooltip("Save matching rule")
                ui.button(icon="delete", on_click=lambda rid=rule_id: page.remove_rule(
                    table_name, rid)).props("round outline").tooltip("Delete matching rule")
        with ui.row().classes("w-full items-end gap-2"):
            source = ui.select(RULE_FIELDS, value="payment_message", label="New match field").classes("w-44")
            pattern = ui.input("New contains pattern").classes("flex-1")

            def add_matching_rule():
                """Add a match rule to the selected management item."""
                try:
                    _add_rule(page.finance_db_path, table_name, owner_column, owner_id,
                              source.value, pattern.value or "")
                    ui.notify("Matching rule created", type="positive")
                    page.actions.refresh_matching()
                    page.render_management()
                    page.actions.render_transactions()
                except (sqlite3.Error, ValueError) as error:
                    ui.notify(str(error), type="warning")

            ui.button(icon="add", on_click=add_matching_rule).props(
                "round outline").tooltip("Add matching rule")


def remove_rule(page: ManagePage, table_name: str, rule_id: int) -> None:
    """Delete a selected matching rule and refresh the management view.

    Args:
        page: Manage page supplying database paths and refresh callbacks.
        table_name: Counterparty or subscription rule table.
        rule_id: ID of the rule to delete.
    """
    try:
        _delete_rule(page.finance_db_path, table_name, rule_id)
        page.actions.refresh_matching()
        page.render_management()
        page.actions.render_transactions()
    except sqlite3.Error as error:
        ui.notify(f"Could not remove rule: {error}", type="negative")
