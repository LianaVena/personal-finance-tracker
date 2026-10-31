"""Management entity creation forms."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

from nicegui import ui

from src.database import connect_database
from src.subcategory_colors import DEFAULT_SUBCATEGORY_COLOR, normalize_subcategory_color
from .models import ManagementData
from ..color_grid import SubcategoryColorGrid
from ..common import currency_options as _currency_options, money_to_minor_units as _money_to_minor_units
from ..common import notify as _notify
from ..context import RULE_FIELDS
from ..review.create import create_counterparty as _create_counterparty, create_subscription as _create_subscription

if TYPE_CHECKING:
    from .page import ManagePage


def render_create_form(page: ManagePage, data: ManagementData, entity_kind: str) -> None:
    """Render a create form for the selected management entity type.

    Args:
        page: Manage page supplying form state and refresh callbacks.
        data: Query results and table definitions for the current redraw.
        entity_kind: Entity type to create: category, subcategory, counterparty,
            or subscription.
    """
    create_title = {"category": "Create category", "subcategory": "Create subcategory",
                    "counterparty": "Create counterparty", "subscription": "Create subscription"}[entity_kind]
    ui.label(create_title).classes("text-lg font-semibold")
    if entity_kind == "category":
        draft = page.management_draft(entity_kind, None, {"name": ""})
        with ui.row().classes("w-full items-end gap-2 flex-nowrap"):
            name_input = ui.input("Category name", value=draft["name"]).classes("flex-1 min-w-0")
            page.bind_management_draft(draft, "name", name_input)
            ui.button(icon="add", on_click=lambda: save()).props("round outline").tooltip(create_title)

        def save():
            """Validate and create the category currently in the form."""
            name = (name_input.value or "").strip()
            if not name:
                _notify(ui, "Enter a category name", type="warning")
                return
            try:
                with closing(connect_database(page.finance_db_path)) as connection, connection:
                    connection.execute("INSERT INTO categories(name) VALUES (?)", (name,))
                _notify(ui, "Category created", type="positive")
                page.drafts.pop((entity_kind, None), None)
                page.render_management()
                page.actions.render_configuration()
            except sqlite3.IntegrityError:
                _notify(ui, "A category with that name already exists", type="warning")
    elif entity_kind == "subcategory":
        draft = page.management_draft(entity_kind, None, {
            "parent": None, "name": "", "color": DEFAULT_SUBCATEGORY_COLOR,
        })
        with ui.row().classes("w-full items-center gap-2 flex-nowrap"):
            parent = ui.select(data.categories, value=draft["parent"],
                               label="Parent category").classes("flex-1 min-w-0")
            name_input = ui.input("Subcategory name", value=draft["name"]).classes("flex-1 min-w-0")
            page.bind_management_draft(draft, "parent", parent)
            page.bind_management_draft(draft, "name", name_input)
            color = SubcategoryColorGrid(
                draft["color"], lambda value: draft.__setitem__("color", value), data.colors,
            )
            ui.button(icon="add", on_click=lambda: save()).props("round outline").tooltip(create_title)

        def save():
            """Validate and create the subcategory currently in the form."""
            name = (name_input.value or "").strip()
            if parent.value is None or not name:
                _notify(ui, "Choose a category and enter a subcategory name", type="warning")
                return
            try:
                selected_color = normalize_subcategory_color(color.value, data.colors)
                with closing(connect_database(page.finance_db_path)) as connection, connection:
                    connection.execute("INSERT INTO subcategories(category_id, name, color_id) VALUES (?, ?, ?)",
                                       (parent.value, name, selected_color))
                _notify(ui, "Subcategory created", type="positive")
                page.drafts.pop((entity_kind, None), None)
                page.render_management()
                page.actions.render_configuration()
                page.actions.render_transactions()
            except sqlite3.IntegrityError:
                _notify(ui, "That subcategory already exists in this category", type="warning")
            except ValueError as error:
                _notify(ui, str(error), type="warning")
    elif entity_kind == "counterparty":
        draft = page.management_draft(entity_kind, None, {"name": "", "subcategory": None, "subscription": None,
                                                          "source": "payment_message", "pattern": ""})
        name_input = ui.input("Counterparty name", value=draft["name"]).classes("w-full")
        page.bind_management_draft(draft, "name", name_input)
        with ui.row().classes("w-full items-end gap-2 flex-wrap"):
            subcategory = ui.select(data.subcategory_options, value=draft["subcategory"],
                                    label="Default subcategory").classes("flex-1")
            default_subscription = ui.select(
                {None: "Not set", 0: "No", 1: "Yes"}, value=draft["subscription"],
                label="Default subscription answer",
            ).classes("flex-1")
            page.bind_management_draft(draft, "subcategory", subcategory)
            page.bind_management_draft(draft, "subscription", default_subscription)
        ui.label("Matching rule").classes("text-sm font-medium text-slate-300")
        with ui.row().classes("w-full items-end gap-2 flex-nowrap"):
            source = ui.select(RULE_FIELDS, value=draft["source"], label="Match field").classes(
                "flex-[1] min-w-0")
            pattern = ui.input("Contains pattern", value=draft["pattern"]).classes(
                "flex-[2] min-w-0")
            page.bind_management_draft(draft, "source", source)
            page.bind_management_draft(draft, "pattern", pattern)
            ui.button(icon="add", on_click=lambda: save()).props("round outline").tooltip(create_title)

        def save():
            """Create a counterparty using its form values and optional rule."""
            try:
                _create_counterparty(page.finance_db_path, name_input.value or "", subcategory.value,
                                     default_subscription.value, source.value, pattern.value or "")
                _notify(ui, "Counterparty and matching rule created" if (pattern.value or "").strip()
                else "Counterparty created", type="positive")
                page.drafts.pop((entity_kind, None), None)
                page.actions.refresh_matching()
                page.render_management()
                page.actions.render_configuration()
                page.actions.render_transactions()
            except (sqlite3.Error, ValueError) as error:
                _notify(ui, str(error), type="warning")
    else:
        draft = page.management_draft(entity_kind, None, {"name": "", "counterparty": None, "period": "monthly",
                                                          "amount": "", "currency": "EUR",
                                                          "source": "payment_message", "pattern": ""})
        name_input = ui.input("Subscription name", value=draft["name"]).classes("w-full")
        page.bind_management_draft(draft, "name", name_input)
        with ui.row().classes("w-full items-end gap-2 flex-nowrap"):
            counterparty_input = ui.select(
                {None: "No counterparty", **{cp["id"]: cp["name"] for cp in data.counterparties}},
                value=draft["counterparty"], label="Counterparty",
            ).classes("flex-1 min-w-0")
            period = ui.select({"monthly": "Monthly", "yearly": "Yearly"}, value=draft["period"],
                               label="Billing period").classes("flex-1 min-w-0")
            page.bind_management_draft(draft, "counterparty", counterparty_input)
            page.bind_management_draft(draft, "period", period)
        with ui.row().classes("w-full items-end gap-2 flex-nowrap"):
            amount_input = ui.input("Expected amount", value=draft["amount"]).classes("flex-1 min-w-0")
            currency = ui.select(_currency_options(draft["currency"]), value=draft["currency"],
                                 label="Currency").classes("flex-1 min-w-0")
            page.bind_management_draft(draft, "amount", amount_input)
            page.bind_management_draft(draft, "currency", currency)
        ui.label("Matching rule").classes("text-sm font-medium text-slate-300")
        with ui.row().classes("w-full items-end gap-2 flex-nowrap"):
            source = ui.select(RULE_FIELDS, value=draft["source"], label="Match field").classes(
                "flex-1 min-w-0")
            pattern = ui.input("Contains pattern", value=draft["pattern"]).classes("flex-1 min-w-0")
            page.bind_management_draft(draft, "source", source)
            page.bind_management_draft(draft, "pattern", pattern)
            ui.button(icon="add", on_click=lambda: save()).props("round outline").tooltip(create_title)

        def save():
            """Create a subscription using its form values and optional rule."""
            try:
                amount = _money_to_minor_units(amount_input.value)
                currency_value = (currency.value or "").strip().upper() if amount is not None else None
                if currency_value is not None and (len(currency_value) != 3 or not currency_value.isascii()
                                                   or not currency_value.isalpha()):
                    raise ValueError("Currency must be a three-letter code")
                _create_subscription(page.finance_db_path, name_input.value or "", counterparty_input.value,
                                     period.value, amount, currency_value,
                                     (source.value, pattern.value or "") if (pattern.value or "").strip()
                                     else None)
                _notify(ui, "Subscription and matching rule created" if (pattern.value or "").strip()
                else "Subscription created", type="positive")
                page.drafts.pop((entity_kind, None), None)
                page.actions.refresh_matching()
                page.render_management()
                page.actions.render_configuration()
                page.actions.render_transactions()
                page.actions.render_subscriptions()
            except (sqlite3.Error, ValueError) as error:
                _notify(ui, str(error), type="warning")
