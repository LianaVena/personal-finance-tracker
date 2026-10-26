"""Review-side category, counterparty, and subscription creation forms."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

from nicegui import ui

from src.database import connect_database
from .create import create_counterparty as _create_counterparty, create_subscription as _create_subscription
from ..common import currency_options as _currency_options, money_to_minor_units as _money_to_minor_units
from ..context import RULE_FIELDS
from ..manage.tables import categories as _categories, counterparties as _counterparties, \
    subcategories as _subcategories

if TYPE_CHECKING:
    from .page import ReviewPage


def render_creation_forms(page: ReviewPage) -> None:
    """Render the Review page's category, counterparty, and subscription forms."""
    page.creation_content.clear()
    categories = _categories(page.finance_db_path)
    subcategory_options = _subcategories(page.finance_db_path)
    counterparties = _counterparties(page.finance_db_path)
    with page.creation_content:
        with ui.card().classes("w-full p-4 gap-3 shadow-none border-0"):
            ui.label("Create category").classes("text-lg font-semibold")
            with ui.row().classes("w-full items-end gap-2"):
                category_name_input = ui.input(
                    "Category name", value=page.form_values["category_name"],
                ).classes("flex-1")
                page.bind_form_value("category_name", category_name_input)

                def add_category() -> None:
                    """Create a category from the Review panel."""
                    name = (category_name_input.value or "").strip()
                    if not name:
                        ui.notify("Enter a category name", type="warning")
                        return
                    try:
                        with closing(connect_database(page.finance_db_path)) as connection, connection:
                            connection.execute("INSERT INTO categories(name) VALUES (?)", (name,))
                        ui.notify("Category created", type="positive")
                        page.clear_form("category_name")
                        page.render_configuration()
                        page.actions.render_management()
                    except sqlite3.IntegrityError:
                        ui.notify("A category with that name already exists", type="warning")

                ui.button(icon="add", on_click=add_category).props("round outline").tooltip("Add category")

        with ui.card().classes("w-full p-4 gap-3 shadow-none border-0"):
            ui.label("Create subcategory").classes("text-lg font-semibold")
            with ui.row().classes("w-full items-end gap-2"):
                parent = ui.select(
                    categories, value=page.form_values["subcategory_parent"], label="Parent category",
                ).classes("flex-1")
                subcategory_name_input = ui.input(
                    "Subcategory name", value=page.form_values["subcategory_name"],
                ).classes("flex-1")
                page.bind_form_value("subcategory_parent", parent)
                page.bind_form_value("subcategory_name", subcategory_name_input)

                def add_subcategory() -> None:
                    """Create a subcategory under the selected category."""
                    name = (subcategory_name_input.value or "").strip()
                    if parent.value is None or not name:
                        ui.notify("Choose a category and enter a subcategory", type="warning")
                        return
                    try:
                        with closing(connect_database(page.finance_db_path)) as connection, connection:
                            connection.execute(
                                "INSERT INTO subcategories(category_id, name) VALUES (?, ?)",
                                (parent.value, name),
                            )
                        ui.notify("Subcategory created", type="positive")
                        page.clear_form("subcategory_parent", "subcategory_name")
                        page.render_configuration()
                        page.actions.render_management()
                        page.render_transactions()
                    except sqlite3.IntegrityError:
                        ui.notify("That subcategory already exists in this category", type="warning")

                ui.button(icon="add", on_click=add_subcategory).props(
                    "round outline").tooltip("Add subcategory")

        with ui.card().classes("w-full p-4 gap-3 shadow-none border-0"):
            ui.label("Create counterparty").classes("text-lg font-semibold")
            counterparty_name_input = ui.input(
                "Counterparty name", value=page.form_values["counterparty_name"],
            ).classes("w-full")
            page.bind_form_value("counterparty_name", counterparty_name_input)
            with ui.row().classes("w-full items-end gap-2 flex-wrap"):
                default_subcategory = ui.select(
                    subcategory_options, value=page.form_values["counterparty_subcategory"],
                    label="Default subcategory",
                ).classes("min-w-44 flex-1")
                default_subscription = ui.select(
                    {None: "Not set", 0: "No", 1: "Yes"},
                    value=page.form_values["counterparty_subscription"],
                    label="Default subscription answer",
                ).classes("min-w-44 flex-1")
                page.bind_form_value("counterparty_subcategory", default_subcategory)
                page.bind_form_value("counterparty_subscription", default_subscription)
            with ui.row().classes("w-full items-end gap-2 flex-nowrap"):
                source = ui.select(RULE_FIELDS, value=page.form_values["counterparty_source"],
                                   label="Match field").classes("flex-[1] min-w-0")
                pattern = ui.input(
                    "Contains pattern", value=page.form_values["counterparty_pattern"],
                ).classes("flex-[2] min-w-0")
                page.bind_form_value("counterparty_source", source)
                page.bind_form_value("counterparty_pattern", pattern)

                def add_counterparty() -> None:
                    """Create a counterparty and its optional matching rule."""
                    try:
                        match_pattern = pattern.value or ""
                        _create_counterparty(page.finance_db_path, counterparty_name_input.value or "",
                                             default_subcategory.value, default_subscription.value,
                                             source.value, match_pattern)
                        ui.notify(
                            "Counterparty and matching rule created" if match_pattern.strip()
                            else "Counterparty created",
                            type="positive",
                        )
                        page.clear_form(
                            "counterparty_name", "counterparty_subcategory",
                            "counterparty_subscription", "counterparty_source", "counterparty_pattern",
                        )
                        page.refresh_matching(advance_if_complete=True)
                        page.render_configuration()
                        page.actions.render_management()
                        page.render_transactions()
                    except (sqlite3.Error, ValueError) as error:
                        ui.notify(str(error), type="warning")

                ui.button(icon="add", on_click=add_counterparty).props(
                    "round outline").tooltip("Add counterparty")

        with ui.card().classes("w-full p-4 gap-3 shadow-none border-0"):
            ui.label("Create subscription").classes("text-lg font-semibold")
            subscription_name_input = ui.input(
                "Subscription name", value=page.form_values["subscription_name"],
            ).classes("w-full")
            page.bind_form_value("subscription_name", subscription_name_input)
            with ui.row().classes("w-full items-end gap-2 flex-nowrap"):
                cp_options = {None: "No counterparty", **{cp["id"]: cp["name"] for cp in counterparties}}
                cp_select = ui.select(
                    cp_options, value=page.form_values["subscription_counterparty"], label="Counterparty",
                ).classes("flex-[2] min-w-0")
                billing = ui.select({"monthly": "Monthly", "yearly": "Yearly"},
                                    value=page.form_values["subscription_period"],
                                    label="Billing period").classes("flex-[2] min-w-0")
                page.bind_form_value("subscription_counterparty", cp_select)
                page.bind_form_value("subscription_period", billing)
                expected_amount = ui.input(
                    "Expected amount", value=page.form_values["subscription_amount"],
                ).classes("flex-[1] min-w-0")
                currency = ui.select(
                    _currency_options(page.form_values["subscription_currency"]),
                    value=page.form_values["subscription_currency"], label="Currency",
                ).classes("flex-[1] min-w-0")
                page.bind_form_value("subscription_amount", expected_amount)
                page.bind_form_value("subscription_currency", currency)
            with ui.row().classes("w-full items-end gap-2 flex-nowrap"):
                rule_field = ui.select(
                    RULE_FIELDS, value=page.form_values["subscription_source"], label="Match field",
                ).classes("flex-[2.2] min-w-0")
                rule_pattern = ui.input(
                    "Contains pattern", value=page.form_values["subscription_pattern"],
                ).classes("flex-[4] min-w-0")
                page.bind_form_value("subscription_source", rule_field)
                page.bind_form_value("subscription_pattern", rule_pattern)

                def add_subscription() -> None:
                    """Create a subscription and its optional text rule."""
                    try:
                        minor = _money_to_minor_units(expected_amount.value)
                        currency_value = (currency.value or "").strip().upper() if minor is not None else None
                        if currency_value is not None and (len(currency_value) != 3 or not currency_value.isalpha()
                                                           or not currency_value.isascii()):
                            raise ValueError("Currency must be a three-letter code")
                        rule = (rule_field.value, rule_pattern.value or "")
                        _create_subscription(page.finance_db_path, subscription_name_input.value or "", cp_select.value,
                                             billing.value, minor, currency_value,
                                             rule if rule[1].strip() else None)
                        ui.notify("Subscription created", type="positive")
                        page.clear_form(
                            "subscription_name", "subscription_counterparty", "subscription_period",
                            "subscription_amount", "subscription_currency", "subscription_source",
                            "subscription_pattern",
                        )
                        page.refresh_matching(advance_if_complete=True)
                        page.actions.render_subscriptions()
                        page.render_configuration()
                        page.actions.render_management()
                        page.render_transactions()
                    except (sqlite3.Error, ValueError) as error:
                        ui.notify(str(error), type="warning")

                ui.button(icon="add", on_click=add_subscription).props(
                    "round outline").tooltip("Add subscription")
