"""Subscription decisions and expanded transaction split controls."""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import TYPE_CHECKING

from nicegui import ui

from .transactions import save_excluded as _save_excluded, save_split_amount as _save_split_amount, \
    save_split_note as _save_split_note, save_subcategory as _save_subcategory, \
    save_subscription_decision as _save_subscription_decision
from ..common import money_to_minor_units as _money_to_minor_units

if TYPE_CHECKING:
    from .page import ReviewPage


def render_split_decisions(page: ReviewPage, subscription_options: dict, split_record: dict,
                           transaction_id: str) -> None:
    """Render subscription controls beside the existing split category control.

    Args:
        page: Review page supplying database paths and refresh callbacks.
        subscription_options: Subscription IDs mapped to display labels.
        split_record: Split record and its current category/subscription values.
        transaction_id: Stable ID of the parent transaction.
    """
    with ui.row().classes("w-full items-end gap-2 flex-wrap"):
        decision_value = ("unknown" if split_record["is_subscription"] is None else
                          "yes" if split_record["is_subscription"] else "no")
        decision_select = ui.select(
            {"unknown": "Not set", "yes": "Yes", "no": "No"},
            value=decision_value, label="Subscription",
        ).classes("min-w-0").style("width: calc(50% - 4px); flex: none")
        subscription_select = None
        if split_record["is_subscription"] == 1:
            subscription_select = ui.select(
                subscription_options, value=split_record["subscription_id"],
                label="Linked subscription",
            ).classes("min-w-0").style("width: calc(50% - 4px); flex: none")

        def save_decision(event, split_id=split_record["id"], tid=transaction_id,
                          linked_select=subscription_select):
            """Save the split's subscription answer.

            Args:
                event: NiceGUI value-change event containing the answer.
                split_id: ID of the split captured for this control.
                tid: Stable ID of the parent transaction.
                linked_select: Control used to select its linked subscription.
            """
            try:
                _save_subscription_decision(
                    page.finance_db_path, split_id, event.value,
                    linked_select.value if event.value == "yes" and linked_select else None,
                )
                page.refresh_after_edit(tid)
            except sqlite3.Error as error:
                ui.notify(f"Could not save subscription status: {error}", type="negative")

        def save_subscription(event, split_id=split_record["id"], tid=transaction_id,
                              status_select=decision_select):
            """Link the selected subscription to the split.

            Args:
                event: NiceGUI value-change event containing the linked ID.
                split_id: ID of the split captured for this control.
                tid: Stable ID of the parent transaction.
                status_select: Control containing the subscription answer.
            """
            try:
                _save_subscription_decision(page.finance_db_path, split_id, "yes", event.value)
                status_select.value = "yes"
                page.refresh_after_edit(tid)
            except sqlite3.Error as error:
                ui.notify(f"Could not link subscription: {error}", type="negative")

        decision_select.on_value_change(save_decision)
        if subscription_select is not None:
            subscription_select.on_value_change(save_subscription)


def render_split_editor(page: ReviewPage, transaction: dict, split: dict, splits: list[dict],
                        subcategory_options: dict, subscription_options: dict) -> None:
    """Render one expanded split while capturing its IDs in callbacks."""
    tx_id = transaction["id"]
    with ui.card().classes("w-full p-3 shadow-none border border-slate-700"):
        split_note = ui.input(
            "Split note", value=split["note"] or "",
        ).classes("w-full")

        def save_split_note(event, split_id=split["id"]):
            """Persist the note attached to this split.

            Args:
                event: NiceGUI value-change event containing the note.
                split_id: ID of the split captured for this input.
            """
            try:
                _save_split_note(page.finance_db_path, split_id,
                                 (event.value or "").strip() or None)
            except sqlite3.Error as error:
                ui.notify(f"Could not save split note: {error}", type="negative")

        split_note.on_value_change(save_split_note)

        with ui.row().classes("w-full items-end gap-2 flex-nowrap"):
            amount_input = ui.number(
                "Split amount", value=float(Decimal(split["amount"]) / 100),
                format="%.2f", step=0.01,
            ).classes("flex-1 min-w-0")
            category_select = ui.select(
                subcategory_options, value=split["subcategory_id"], label="Subcategory",
            ).classes("flex-1 min-w-0")

            def save_amount(event, split_id=split["id"],
                            transaction_amount=transaction["amount"]):
                """Convert the edited amount to cents and save it.

                Args:
                    event: NiceGUI value-change event containing the amount.
                    split_id: ID of the split captured for this input.
                    transaction_amount: Original signed transaction amount.
                """
                try:
                    cents = _money_to_minor_units(event.value)
                    if cents is None:
                        raise ValueError("Enter a split amount")
                    if cents * transaction_amount <= 0:
                        raise ValueError("Every split must have the transaction's sign")
                    _save_split_amount(page.finance_db_path, split_id, cents)
                except (sqlite3.Error, ValueError) as error:
                    ui.notify(str(error), type="warning")

            def save_exclusion(event, split_id=split["id"], tid=tx_id):
                """Save this split's exclusion flag.

                Args:
                    event: NiceGUI value-change event with the checkbox value.
                    split_id: ID of the split captured for this control.
                    tid: Stable ID of the parent transaction.
                """
                _save_excluded(page.finance_db_path, split_id, event.value)
                page.refresh_after_edit(tid)

            amount_input.on_value_change(save_amount)

            def save_split_category(event, split_id=split["id"], tid=tx_id):
                """Save this split's manual subcategory.

                Args:
                    event: NiceGUI value-change event.
                    split_id: ID of the split captured for this control.
                    tid: Stable ID of the parent transaction.
                """
                try:
                    _save_subcategory(page.finance_db_path, split_id, event.value)
                    page.refresh_matching()
                    page.refresh_after_edit(tid)
                except sqlite3.Error as error:
                    ui.notify(f"Could not save subcategory: {error}", type="negative")

            category_select.on_value_change(save_split_category)

        render_split_decisions(page, subscription_options, split, tx_id)
        excluded = ui.checkbox(
            "Exclude from spending", value=bool(split["excluded"]),
        ).classes("w-full")
        excluded.on_value_change(save_exclusion)
        if len(splits) > 1:
            ui.button(icon="delete", on_click=lambda s=split["id"], t=tx_id:
            page.delete_split(t, s)).props("round outline").tooltip("Delete split")
