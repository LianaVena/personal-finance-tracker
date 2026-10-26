"""Review page state, navigation, and rendering coordination."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from nicegui import ui

from src.categorization import apply_matching_rules
from src.database import connect_database
from .creation_forms import render_creation_forms
from .transaction_card import render_transaction_card
from .transactions import add_split as _add_split, delete_split as _delete_split, \
    review_transactions as _review_transactions
from ..context import PAGE_SIZE, ReviewState, UiActions
from ..manage.tables import counterparties as _counterparties, subcategories as _subcategories, \
    subscriptions as _subscriptions


class ReviewPage:
    """Own review navigation and creation-form state for one UI instance."""

    def __init__(self, transaction_db_path: Path, finance_db_path: Path, actions: UiActions,
                 transaction_content: ui.column, creation_content: ui.column) -> None:
        self.transaction_db_path = transaction_db_path
        self.finance_db_path = finance_db_path
        self.actions = actions
        self.transaction_content = transaction_content
        self.creation_content = creation_content
        self.state: ReviewState = {
            "offset": 0, "pinned_id": None, "active_id": None, "expanded_splits": set(),
        }
        self.form_defaults: dict[str, Any] = {
            "category_name": "",
            "subcategory_parent": None,
            "subcategory_name": "",
            "counterparty_name": "",
            "counterparty_subcategory": None,
            "counterparty_subscription": None,
            "counterparty_source": "payment_message",
            "counterparty_pattern": "",
            "subscription_name": "",
            "subscription_counterparty": None,
            "subscription_period": "monthly",
            "subscription_amount": "",
            "subscription_currency": "EUR",
            "subscription_source": "payment_message",
            "subscription_pattern": "",
        }
        self.form_values = self.form_defaults.copy()

    def refresh_matching(self, advance_if_complete: bool = False) -> None:
        """Reapply automatic matches and preserve or advance the current review item.

        Args:
            advance_if_complete: Whether to release the current transaction if
                matching completes its review requirements.
        """
        active_id = self.state["active_id"]
        was_incomplete = False
        if advance_if_complete and active_id is not None:
            before = next((transaction for transaction in
                           _review_transactions(self.transaction_db_path, self.finance_db_path)
                           if transaction["id"] == active_id), None)
            was_incomplete = before is not None and bool(before["review_reasons"])
        apply_matching_rules(self.transaction_db_path, self.finance_db_path)
        if active_id is None:
            return
        if advance_if_complete and was_incomplete:
            active = next((transaction for transaction in
                           _review_transactions(self.transaction_db_path, self.finance_db_path)
                           if transaction["id"] == active_id), None)
            if active is not None and not active["review_reasons"]:
                self.state["pinned_id"] = None
                return
        self.state["pinned_id"] = active_id

    def refresh_after_edit(self, transaction_id: str) -> None:
        """Rebuild the review queue while keeping the edited transaction in view.

        Args:
            transaction_id: Stable hash ID of the edited transaction.
        """
        all_transactions = _review_transactions(self.transaction_db_path, self.finance_db_path)
        selected = next((candidate for candidate in all_transactions
                         if candidate["id"] == transaction_id), None)
        review = [transaction for transaction in all_transactions if transaction["review_reasons"]]
        if selected is not None and not selected["review_reasons"]:
            self.state["pinned_id"] = transaction_id
        else:
            self.state["pinned_id"] = None
            if selected is not None and selected in review:
                self.state["offset"] = review.index(selected)
        self.render_transactions()

    def save_transaction(self, transaction_id: str) -> None:
        """Validate a transaction and remove it from the review queue when complete.

        Args:
            transaction_id: Stable hash ID of the transaction to validate.
        """
        transaction = next(
            (item for item in _review_transactions(self.transaction_db_path, self.finance_db_path)
             if item["id"] == transaction_id),
            None,
        )
        if transaction is None:
            ui.notify("Transaction is no longer available", type="negative")
            return
        if transaction["review_reasons"]:
            ui.notify("Complete the required fields before saving: "
                      + " · ".join(transaction["review_reasons"]), type="warning")
            return
        self.state["pinned_id"] = None
        ui.notify("Transaction saved", type="positive")
        self.render_transactions()

    def render_transactions(self) -> None:
        """Render the current review transaction and its split controls."""
        self.transaction_content.clear()
        all_transactions = _review_transactions(self.transaction_db_path, self.finance_db_path)
        review = [transaction for transaction in all_transactions if transaction["review_reasons"]]
        total = len(review)
        pinned = next((candidate for candidate in all_transactions
                       if candidate["id"] == self.state["pinned_id"]), None)
        if pinned is None:
            self.state["pinned_id"] = None
        elif pinned["review_reasons"]:
            self.state["pinned_id"] = None
            pinned = None
        if pinned is not None:
            current = [pinned]
        else:
            self.state["offset"] = min(self.state["offset"], max(0, total - 1))
            current = review[self.state["offset"]:self.state["offset"] + PAGE_SIZE]
        self.state["active_id"] = current[0]["id"] if current else None
        with self.transaction_content:
            with ui.row().classes("w-full items-center gap-3"):
                ui.label("Transaction review").classes("text-2xl font-semibold")
                ui.element("div").classes("flex-grow")
                if pinned is not None:
                    pinned_key = (pinned["booking_date"], pinned["id"])
                    has_newer = any((tx["booking_date"], tx["id"]) > pinned_key for tx in review)
                    has_older = any((tx["booking_date"], tx["id"]) < pinned_key for tx in review)
                    position_text = f"{self.state['offset'] + 1}/{total + 1}"
                else:
                    has_newer = self.state["offset"] > 0
                    has_older = self.state["offset"] + 1 < total
                    position_text = f"{self.state['offset'] + 1 if total else 0}/{total}"
                ui.button(icon="chevron_left", on_click=lambda: self.change_page(-1)).props(
                    f"round outline {'disable' if not has_newer else ''}").tooltip("Newer transaction")
                ui.label(position_text).classes("self-center text-sm text-slate-400")
                ui.button(icon="chevron_right", on_click=lambda: self.change_page(1)).props(
                    f"round outline {'disable' if not has_older else ''}").tooltip("Older transaction")

            if not current:
                with ui.card().classes("w-full p-8 items-center shadow-none border-0"):
                    ui.icon("task_alt", size="2rem").classes("text-emerald-400")
                    ui.label("All transactions are reviewed").classes("text-lg font-medium")

            counterparties = _counterparties(self.finance_db_path)
            counterparty_options = {None: "Unassigned", **{cp["id"]: cp["name"] for cp in counterparties}}
            subcategory_options = _subcategories(self.finance_db_path)
            subscriptions = _subscriptions(self.finance_db_path)
            subscription_options = {None: "Choose subscription", **{sub["id"]: sub["name"]
                                                                    for sub in subscriptions}}
            for transaction in current:
                render_transaction_card(self, transaction, counterparty_options, subcategory_options,
                                        subscription_options)

    def add_split(self, transaction_id: str) -> None:
        """Add a split and open its settings if the amount can be divided.

        Args:
            transaction_id: Stable hash ID of the transaction to split.
        """
        try:
            _add_split(self.finance_db_path, transaction_id)
            self.state["expanded_splits"].add(transaction_id)
            self.refresh_after_edit(transaction_id)
        except (sqlite3.Error, ValueError) as error:
            ui.notify(str(error), type="warning")

    def delete_split(self, transaction_id: str, split_id: int) -> None:
        """Delete the selected split and refresh the current transaction.

        Args:
            transaction_id: Stable hash ID of the parent transaction.
            split_id: ID of the split to delete.
        """
        try:
            _delete_split(self.finance_db_path, transaction_id, split_id)
            with closing(connect_database(self.finance_db_path)) as connection:
                remaining_row = connection.execute(
                    "SELECT COUNT(*) FROM transaction_splits WHERE transaction_id = ?",
                    (transaction_id,),
                ).fetchone()
                if remaining_row is None:
                    raise sqlite3.DatabaseError("Split count query returned no result")
                remaining = remaining_row[0]
            if remaining <= 1:
                self.state["expanded_splits"].discard(transaction_id)
            self.refresh_after_edit(transaction_id)
        except (sqlite3.Error, ValueError) as error:
            ui.notify(str(error), type="warning")

    def toggle_split_settings(self, transaction_id: str) -> None:
        """Show or hide the split editor for one transaction.

        Args:
            transaction_id: Stable hash ID of the transaction to expand or collapse.
        """
        if transaction_id in self.state["expanded_splits"]:
            self.state["expanded_splits"].discard(transaction_id)
        else:
            self.state["expanded_splits"].add(transaction_id)
        self.render_transactions()

    def change_page(self, direction: int) -> None:
        """Move to the next or previous transaction that still needs review.

        Args:
            direction: Positive to move forward; negative to move backward.
        """
        all_transactions = _review_transactions(self.transaction_db_path, self.finance_db_path)
        review = [transaction for transaction in all_transactions if transaction["review_reasons"]]
        pinned = next((candidate for candidate in all_transactions
                       if candidate["id"] == self.state["pinned_id"]
                       and not candidate["review_reasons"]), None)
        if pinned is not None:
            pinned_key = (pinned["booking_date"], pinned["id"])
            if direction > 0:
                candidates = [tx for tx in review if (tx["booking_date"], tx["id"]) < pinned_key]
                target = candidates[0] if candidates else None
            else:
                candidates = [tx for tx in review if (tx["booking_date"], tx["id"]) > pinned_key]
                target = min(candidates,
                             key=lambda candidate: (candidate["booking_date"], candidate["id"])) if candidates else None
            if target is None:
                ui.notify("There are no more transactions in that direction", type="info")
                return
            self.state["pinned_id"] = None
            self.state["offset"] = review.index(target)
        else:
            self.state["pinned_id"] = None
            self.state["offset"] = min(max(self.state["offset"] + direction, 0), max(len(review) - 1, 0))
        self.render_transactions()

    def bind_form_value(self, key: str, control) -> None:
        """Keep a Review-side creation form value between redraws.

        Args:
            key: Field key in the Review form state.
            control: NiceGUI input control to observe.
        """
        control.on_value_change(
            lambda event, field=key: self.form_values.__setitem__(field, event.value)
        )

    def clear_form(self, *keys: str) -> None:
        """Reset only the named creation-form fields to their defaults.

        Args:
            *keys: Form field keys to reset.
        """
        for key in keys:
            self.form_values[key] = self.form_defaults[key]

    def render_configuration(self) -> None:
        """Redraw the creation forms while retaining their values."""
        render_creation_forms(self)
