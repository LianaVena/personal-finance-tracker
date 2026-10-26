"""Transaction details and compact review controls."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from nicegui import ui

from .split_controls import render_split_decisions, render_split_editor
from .transactions import format_transaction_field as _format_transaction_field, \
    save_counterparty as _save_counterparty, save_excluded as _save_excluded, save_subcategory as _save_subcategory, \
    save_transaction_note as _save_transaction_note

if TYPE_CHECKING:
    from .page import ReviewPage


def render_transaction_card(page: ReviewPage, transaction: dict, counterparty_options: dict,
                            subcategory_options: dict, subscription_options: dict) -> None:
    """Render a transaction card and capture the IDs used by its controls."""
    tx_id = transaction["id"]
    splits = transaction["splits"]
    expanded = tx_id in page.state["expanded_splits"]
    with ui.card().classes("w-full p-4 shadow-none border-0"):
        with ui.column().classes("w-full gap-2"):
            for field, value in transaction.items():
                if field in {"id", "splits", "review_reasons", "note", "counterparty_id",
                             "counterparty_is_manual", "currency", "currency_related"} or value is None:
                    continue
                if (field == "value_date" and
                        transaction.get("booking_date") == value):
                    continue
                label, formatted = _format_transaction_field(field, value, transaction)
                with ui.row().classes("w-full items-start gap-3"):
                    ui.label(f"{label}:").classes("w-44 shrink-0 text-slate-400")
                    ui.label(formatted).classes("min-w-0 break-all")

        if expanded or len(transaction["splits"]) != 1:
            with ui.row().classes("w-full items-end gap-3 flex-wrap mt-3"):
                counterparty_select = ui.select(
                    counterparty_options, value=transaction["counterparty_id"],
                    label="Counterparty", with_input=True,
                ).classes("min-w-56 flex-1")

                def update_counterparty(event, transaction_id=tx_id):
                    """Save the user's counterparty choice and refresh matches.

                    Args:
                        event: NiceGUI value-change event.
                        transaction_id: Stable ID captured for this transaction.
                    """
                    try:
                        _save_counterparty(page.finance_db_path, transaction_id, event.value)
                        page.refresh_matching()
                        page.refresh_after_edit(transaction_id)
                    except (sqlite3.Error, ValueError) as error:
                        ui.notify(f"Could not save counterparty: {error}", type="negative")

                counterparty_select.on_value_change(update_counterparty)

        note_input = ui.textarea("Transaction note", value=transaction["note"]).props(
            "autogrow rows=1").classes("w-full mt-2")

        def save_transaction_note(event, transaction_id=tx_id):
            """Persist the edited transaction note.

            Args:
                event: NiceGUI value-change event containing the note.
                transaction_id: Stable ID captured for this transaction.
            """
            try:
                _save_transaction_note(
                    page.finance_db_path, transaction_id, (event.value or "").strip() or None,
                )
            except sqlite3.Error as error:
                ui.notify(f"Could not save note: {error}", type="negative")

        note_input.on_value_change(save_transaction_note)

        if len(splits) == 1 and not expanded:
            # The compact, unsplit transaction controls share one row.
            with ui.row().classes("w-full items-end gap-3 flex-wrap mt-3"):
                counterparty_select = ui.select(
                    counterparty_options, value=transaction["counterparty_id"],
                    label="Counterparty", with_input=True,
                ).classes("min-w-56 flex-1")
                category_select = ui.select(
                    subcategory_options, value=splits[0]["subcategory_id"], label="Subcategory",
                ).classes("min-w-48 flex-1")

                def update_counterparty(event, transaction_id=tx_id):
                    """Save the chosen counterparty and apply matching rules.

                    Args:
                        event: NiceGUI value-change event.
                        transaction_id: Stable ID captured for this transaction.
                    """
                    try:
                        _save_counterparty(page.finance_db_path, transaction_id, event.value)
                        page.refresh_matching()
                        page.refresh_after_edit(transaction_id)
                    except (sqlite3.Error, ValueError) as error:
                        ui.notify(f"Could not save counterparty: {error}", type="negative")

                counterparty_select.on_value_change(update_counterparty)

                def update_compact_category(event, split_id=splits[0]["id"], tid=tx_id):
                    """Save a subcategory from the compact transaction controls.

                    Args:
                        event: NiceGUI value-change event.
                        split_id: ID of the transaction's single split.
                        tid: Stable ID of the parent transaction.
                    """
                    try:
                        _save_subcategory(page.finance_db_path, split_id, event.value)
                        page.refresh_matching()
                        page.refresh_after_edit(tid)
                    except sqlite3.Error as error:
                        ui.notify(f"Could not save subcategory: {error}", type="negative")

                category_select.on_value_change(update_compact_category)
            render_split_decisions(page, subscription_options, splits[0], tx_id)
            with ui.row().classes("w-full items-center mt-2"):
                excluded = ui.checkbox(
                    "Exclude from spending", value=bool(splits[0]["excluded"]),
                )

                def save_exclusion(event, split_id=splits[0]["id"], tid=tx_id):
                    """Save the exclusion flag for the transaction's only split.

                    Args:
                        event: NiceGUI value-change event containing the checkbox value.
                        split_id: ID of the transaction's single split.
                        tid: Stable ID of the parent transaction.
                    """
                    _save_excluded(page.finance_db_path, split_id, event.value)
                    page.refresh_after_edit(tid)

                excluded.on_value_change(save_exclusion)
        elif len(splits) > 1 and not expanded:
            ui.label(f"{len(splits)} splits · open split settings to edit them").classes(
                "text-sm text-slate-400 mt-3")

        with ui.row().classes("w-full items-center gap-2 mt-3"):
            ui.button(icon="call_split", on_click=lambda t=tx_id: page.toggle_split_settings(t)).props(
                "round outline").tooltip("Hide split settings" if expanded else "Split settings")
            if expanded:
                ui.button(icon="add", on_click=lambda t=tx_id: page.add_split(t)).props(
                    "round outline").tooltip("Add split")
            ui.element("div").classes("flex-grow")
            ui.button(icon="save", on_click=lambda t=tx_id: page.save_transaction(t)).props(
                "round outline color=primary").tooltip("Save transaction")

        if expanded:
            if not splits:
                ui.label("This transaction cannot be split because its amount is zero.").classes(
                    "text-sm text-slate-400")
            for split in splits:
                render_split_editor(page, transaction, split, splits, subcategory_options, subscription_options)
