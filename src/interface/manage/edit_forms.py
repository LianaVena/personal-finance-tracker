"""Management entity editing forms."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from decimal import Decimal
from typing import TYPE_CHECKING

from nicegui import ui

from src.database import connect_database
from src.subcategory_colors import normalize_subcategory_color
from .models import ManagementData
from ..color_grid import SubcategoryColorGrid
from ..common import currency_options as _currency_options, money_to_minor_units as _money_to_minor_units
from ..common import notify as _notify

if TYPE_CHECKING:
    from .page import ManagePage


def render_edit_form(page: ManagePage, data: ManagementData, entity_kind: str, item_id: int) -> None:
    """Render an edit form for one selected management entity.

    Args:
        page: Manage page supplying form state and refresh callbacks.
        data: Query results and table definitions for the current redraw.
        entity_kind: Entity type being edited.
        item_id: Database ID of the selected entity.
    """
    ui.label(f"Edit {entity_kind}").classes("text-lg font-semibold")
    if entity_kind == "category":
        item = next(candidate for candidate in data.rows_by_kind[entity_kind] if candidate["id"] == item_id)
        draft = page.management_draft(entity_kind, item_id, {"name": item["name"]})
        with ui.row().classes("w-full items-end gap-2 flex-nowrap"):
            name_input = ui.input("Category name", value=draft["name"]).classes("flex-1 min-w-0")
            page.bind_management_draft(draft, "name", name_input)
            ui.button(icon="save", on_click=lambda: save()).props("round outline").tooltip(
                f"Save {entity_kind}")

        def save():
            """Validate and persist the selected category's new name."""
            name = (name_input.value or "").strip()
            if not name:
                _notify(ui, "Category name cannot be empty", type="warning")
                return
            try:
                with closing(connect_database(page.finance_db_path)) as connection, connection:
                    connection.execute("UPDATE categories SET name = ? WHERE id = ?", (name, item_id))
                _notify(ui, "Category updated", type="positive")
                draft["name"] = name
                page.render_management()
                page.actions.render_configuration()
            except sqlite3.IntegrityError:
                _notify(ui, "A category with that name already exists", type="warning")
    elif entity_kind == "subcategory":
        item = next(candidate for candidate in data.subcategories if candidate[0] == item_id)
        draft = page.management_draft(entity_kind, item_id, {
            "parent": item[1], "name": item[2], "color": item[4],
        })
        with ui.row().classes("w-full items-center gap-2 flex-nowrap"):
            parent = ui.select(data.categories, value=draft["parent"],
                               label="Category").classes("flex-1 min-w-0")
            name_input = ui.input("Subcategory name", value=draft["name"]).classes("flex-1 min-w-0")
            page.bind_management_draft(draft, "parent", parent)
            page.bind_management_draft(draft, "name", name_input)
            color = SubcategoryColorGrid(
                draft["color"], lambda value: draft.__setitem__("color", value), data.colors,
            )
            ui.button(icon="save", on_click=lambda: save()).props("round outline").tooltip(
                f"Save {entity_kind}")

        def save():
            """Validate and persist the selected subcategory's changes."""
            name = (name_input.value or "").strip()
            if parent.value is None or not name:
                _notify(ui, "Choose a category and enter a subcategory name", type="warning")
                return
            try:
                selected_color = normalize_subcategory_color(color.value, data.colors)
                with closing(connect_database(page.finance_db_path)) as connection, connection:
                    connection.execute("UPDATE subcategories SET category_id = ?, name = ?, color_id = ? WHERE id = ?",
                                       (parent.value, name, selected_color, item_id))
                _notify(ui, "Subcategory updated", type="positive")
                draft.update(parent=parent.value, name=name, color=selected_color)
                page.render_management()
                page.actions.render_configuration()
                page.actions.render_transactions()
                page.actions.render_subscriptions()
            except sqlite3.IntegrityError:
                _notify(ui, "That subcategory already exists in this category", type="warning")
            except ValueError as error:
                _notify(ui, str(error), type="warning")
    elif entity_kind == "counterparty":
        item = next(candidate for candidate in data.counterparties if candidate["id"] == item_id)
        draft = page.management_draft(entity_kind, item_id, {"name": item["name"],
                                                             "subcategory": item["default_subcategory_id"],
                                                             "subscription": item["default_is_subscription"]})
        name_input = ui.input("Counterparty name", value=draft["name"]).classes("w-full")
        page.bind_management_draft(draft, "name", name_input)
        with ui.row().classes("w-full items-end gap-2 flex-wrap"):
            subcategory = ui.select(data.subcategory_options, value=draft["subcategory"],
                                    label="Default subcategory").classes("flex-1")
            subscription = ui.select({None: "Not set", 0: "No", 1: "Yes"},
                                     value=draft["subscription"],
                                     label="Default subscription").classes("flex-1")
            page.bind_management_draft(draft, "subcategory", subcategory)
            page.bind_management_draft(draft, "subscription", subscription)
            ui.button(icon="save", on_click=lambda: save()).props("round outline").tooltip(
                f"Save {entity_kind}")

        def save():
            """Persist the selected counterparty's name and defaults."""
            name = (name_input.value or "").strip()
            if not name:
                _notify(ui, "Counterparty name cannot be empty", type="warning")
                return
            try:
                with closing(connect_database(page.finance_db_path)) as connection, connection:
                    connection.execute("UPDATE counterparties SET name = ?, default_subcategory_id = ?, "
                                       "default_is_subscription = ? WHERE id = ?",
                                       (name, subcategory.value, subscription.value, item_id))
                _notify(ui, "Counterparty updated", type="positive")
                draft.update(name=name, subcategory=subcategory.value,
                             subscription=subscription.value)
                page.actions.refresh_matching()
                page.render_management()
                page.actions.render_configuration()
                page.actions.render_transactions()
            except sqlite3.IntegrityError:
                _notify(ui, "A counterparty with that name already exists", type="warning")
    else:
        item = next(candidate for candidate in data.subscriptions if candidate["id"] == item_id)
        draft = page.management_draft(entity_kind, item_id, {
            "name": item["name"], "counterparty": item["counterparty_id"],
            "period": item["billing_period"],
            "amount": "" if item["expected_amount"] is None else
            f"{Decimal(item['expected_amount']) / 100:.2f}",
            "currency": item["currency"], "active": bool(item["is_active"]),
        })
        with ui.row().classes("w-full items-end gap-2 flex-nowrap"):
            name_input = ui.input("Subscription name", value=draft["name"]).classes("flex-1 min-w-0")
            page.bind_management_draft(draft, "name", name_input)
            counterparty_input = ui.select(
                {None: "No counterparty", **{cp["id"]: cp["name"] for cp in data.counterparties}},
                value=draft["counterparty"], label="Counterparty",
            ).classes("flex-1 min-w-0")
            page.bind_management_draft(draft, "counterparty", counterparty_input)
        with ui.row().classes("w-full items-end gap-2 flex-nowrap"):
            period = ui.select({"monthly": "Monthly", "yearly": "Yearly"},
                               value=draft["period"], label="Billing period").classes("flex-1 min-w-0")
            page.bind_management_draft(draft, "period", period)
            amount_input = ui.input("Expected amount", value=draft["amount"]).classes("flex-1 min-w-0")
            currency = ui.select(_currency_options(draft["currency"]), value=draft["currency"],
                                 label="Currency").classes("flex-1 min-w-0")
            active = ui.checkbox("Active", value=draft["active"])
            page.bind_management_draft(draft, "amount", amount_input)
            page.bind_management_draft(draft, "currency", currency)
            page.bind_management_draft(draft, "active", active)
            ui.button(icon="save", on_click=lambda: save()).props("round outline").tooltip(
                f"Save {entity_kind}")

        def save():
            """Validate and persist the selected subscription's fields."""
            name = (name_input.value or "").strip()
            if not name:
                _notify(ui, "Subscription name cannot be empty", type="warning")
                return
            try:
                amount = _money_to_minor_units(amount_input.value)
                currency_value = (currency.value or "").strip().upper()
                if amount is None and currency_value:
                    raise ValueError("Leave both expected amount and currency blank")
                if amount is not None and (len(currency_value) != 3 or not currency_value.isascii()
                                           or not currency_value.isalpha()):
                    raise ValueError("Currency must be a three-letter code")
                with closing(connect_database(page.finance_db_path)) as connection, connection:
                    connection.execute("UPDATE subscriptions SET name = ?, counterparty_id = ?, "
                                       "billing_period = ?, expected_amount = ?, currency = ?, "
                                       "is_active = ? WHERE id = ?",
                                       (name, counterparty_input.value, period.value, amount,
                                        currency_value or None,
                                        int(bool(active.value)), item_id))
                _notify(ui, "Subscription updated", type="positive")
                draft.update(name=name, counterparty=counterparty_input.value, period=period.value,
                             amount=amount_input.value, currency=currency.value, active=active.value)
                page.actions.refresh_matching()
                page.render_management()
                page.actions.render_configuration()
                page.actions.render_transactions()
                page.actions.render_subscriptions()
            except sqlite3.IntegrityError:
                _notify(ui, "A subscription with that name already exists", type="warning")
            except (sqlite3.Error, ValueError) as error:
                _notify(ui, str(error), type="warning")
    if entity_kind == "counterparty":
        page.render_management_rules("counterparties_match_rules", "counterparty_id", item_id)
    elif entity_kind == "subscription":
        page.render_management_rules("subscription_match_rules", "subscription_id", item_id)
