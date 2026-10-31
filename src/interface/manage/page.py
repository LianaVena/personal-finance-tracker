"""Manage page state, table data, and component composition."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path

from nicegui import ui

from src.database import connect_database
from .create_forms import render_create_form
from .edit_forms import render_edit_form
from .models import ManagementData
from .rule_controls import render_management_rules, remove_rule
from .table_view import render_management_table
from .tables import categories as _categories, colors as _colors, counterparties as _counterparties, \
    subcategories as _subcategories, subscriptions as _subscriptions
from ..common import format_money as _format_money
from ..context import UiActions


class ManagePage:
    """Own selections, pagination, and form drafts for one UI instance."""

    def __init__(self, transaction_db_path: Path, finance_db_path: Path,
                 actions: UiActions, content: ui.column) -> None:
        """Initialize management state without querying either database.

        Args:
            transaction_db_path: Database containing imported transactions.
            finance_db_path: Database containing entities, classifications, and rules.
            actions: Cross-page refresh operations supplied by the coordinator.
            content: Container for management tables and forms.
        """
        self.transaction_db_path = transaction_db_path
        self.finance_db_path = finance_db_path
        self.actions = actions
        self.content = content
        self.selection: dict[str, int | None] = {
            "category": None, "subcategory": None, "counterparty": None, "subscription": None,
        }
        self.counterparty_page = {"value": 1}
        self.drafts: dict[tuple[str, int | None], dict] = {}
        self.form_containers: dict[str, ui.card] = {}
        self.management_data: ManagementData | None = None

    def management_draft(self, kind: str, item_id: int | None, defaults: dict) -> dict:
        """Return persistent form values for one selected management item.

        Args:
            kind: Management entity type, such as ``category`` or ``subscription``.
            item_id: Selected entity ID, or ``None`` for a new item.
            defaults: Initial field values used when no draft exists.

        Returns:
            Mutable form values shared by subsequent redraws for this entity.
        """
        return self.drafts.setdefault((kind, item_id), defaults.copy())

    @staticmethod
    def bind_management_draft(draft: dict, field: str, control) -> None:
        """Keep a management form draft synchronized with its input.

        Args:
            draft: Mutable values mapping for the selected management item.
            field: Draft key updated when the control changes.
            control: NiceGUI input control to observe.
        """
        control.on_value_change(lambda event: draft.__setitem__(field, event.value))

    def select_management_item(self, kind: str, row: dict) -> None:
        """Select a table row and open its matching editor.

        Args:
            kind: Management entity type represented by the table.
            row: Selected table record containing its database ID.
        """
        was_selected = self.selection[kind] == row["id"]
        for key in self.selection:
            self.selection[key] = None
        if not was_selected:
            self.selection[kind] = row["id"]
        self.render_management_forms()

    def render_management_forms(self) -> None:
        """Refresh editors while keeping table elements and their scroll positions."""
        data = self.management_data
        if data is None:
            return
        for kind, container in self.form_containers.items():
            container.clear()
            with container:
                selected_id = self.selection[kind]
                exists = any(candidate["id"] == selected_id for candidate in data.rows_by_kind[kind])
                if selected_id is not None and exists:
                    render_edit_form(self, data, kind, selected_id)
                else:
                    render_create_form(self, data, kind)

    def change_counterparty_page(self, direction: int) -> None:
        """Page through the counterparty table in fixed-size groups.

        Args:
            direction: Positive to move forward; negative to move backward.
        """
        counterparties = _counterparties(self.finance_db_path)
        page_count = max(1, (len(counterparties) + 49) // 50)
        self.counterparty_page["value"] = max(
            1, min(page_count, self.counterparty_page["value"] + direction),
        )
        self.render_management()

    def render_management(self) -> None:
        """Render management tables alongside create or edit forms."""
        self.content.clear()
        self.form_containers.clear()
        categories = _categories(self.finance_db_path)
        subcategory_options = _subcategories(self.finance_db_path)
        counterparties = _counterparties(self.finance_db_path)
        subscriptions = _subscriptions(self.finance_db_path)
        color_rows = _colors(self.finance_db_path)
        with closing(connect_database(self.finance_db_path)) as management_connection:
            subcategories: list[
                tuple[int, int, str, str, int | None, str | None, str | None]] = management_connection.execute(
                "SELECT s.id, s.category_id, s.name, c.name, s.color_id, colors.pie_hex, colors.name "
                "FROM subcategories AS s JOIN categories AS c ON c.id = s.category_id "
                "LEFT JOIN colors ON colors.id = s.color_id "
                "ORDER BY s.name COLLATE NOCASE"
            ).fetchall()
        rows_by_kind = {
            "category": [{"id": key, "name": value} for key, value in categories.items()],
            "subcategory": [{"id": row[0], "name": row[2], "category": row[3], "color": row[5],
                             "color_name": row[6] or "No color"}
                            for row in subcategories],
            "counterparty": [],
            "subscription": [{"id": sub["id"], "name": sub["name"],
                              "counterparty": sub["counterparty_name"] or "",
                              "billing_period": sub["billing_period"].capitalize(),
                              "expected_amount": ("—" if sub["expected_amount"] is None else
                                                  _format_money(sub["expected_amount"], sub["currency"],
                                                                absolute=True)),
                              "billing_spacer": "",
                              "right_gutter": "",
                              "is_active": bool(sub["is_active"])} for sub in subscriptions],
        }
        subcategory_by_id = {row[0]: row for row in subcategories}
        for counterparty in counterparties:
            default_subcategory = subcategory_by_id.get(counterparty["default_subcategory_id"])
            rows_by_kind["counterparty"].append({
                "id": counterparty["id"],
                "name": counterparty["name"],
                "default_category": default_subcategory[3] if default_subcategory is not None else "—",
                "default_sub": default_subcategory[2] if default_subcategory is not None else "—",
            })
        columns_by_kind = {
            "category": [{"name": "name", "label": "Category", "field": "name", "sortable": True}],
            "subcategory": [{"name": "name", "label": "Subcategory", "field": "name", "sortable": True},
                            {"name": "category", "label": "Category", "field": "category", "sortable": True},
                            {"name": "color", "label": "Color", "field": "color", "sortable": True}],
            "counterparty": [{"name": "name", "label": "Counterparty", "field": "name", "sortable": True},
                             {"name": "default_category", "label": "Default category",
                              "field": "default_category", "sortable": True},
                             {"name": "default_sub", "label": "Default sub",
                              "field": "default_sub", "sortable": True}],
            "subscription": [{"name": "name", "label": "Subscription", "field": "name", "sortable": True,
                              "align": "left", "style": "width: 25%;", "headerStyle": "width: 25%;"},
                             {"name": "counterparty", "label": "Counterparty", "field": "counterparty",
                              "sortable": True, "align": "left", "style": "width: 25%;",
                              "headerStyle": "width: 25%;"},
                             {"name": "billing_spacer", "label": "", "field": "billing_spacer",
                              "style": "width: 10%;", "headerStyle": "width: 10%;"},
                             {"name": "billing_period", "label": "Billing period", "field": "billing_period",
                              "sortable": True, "align": "center", "style": "width: 15%;",
                              "headerStyle": "width: 15%;"},
                             {"name": "expected_amount", "label": "Expected amount", "field": "expected_amount",
                              "sortable": True, "align": "right", "style": "width: 15%;",
                              "headerStyle": "width: 15%;"},
                             {"name": "right_gutter", "label": "", "field": "right_gutter",
                              "style": "width: 10%;", "headerStyle": "width: 10%;"}],
        }

        data = ManagementData(categories, subcategory_options, counterparties, subscriptions,
                              subcategories, rows_by_kind, columns_by_kind, color_rows)
        self.management_data = data

        with self.content:
            with ui.element("div").classes("w-full grid grid-cols-1 md:grid-cols-2 gap-4 items-start"):
                entities = [
                    ("category", "Categories"), ("subcategory", "Subcategories"),
                    ("counterparty", "Counterparties"), ("subscription", "Subscriptions"),
                ]
                for kind, title in entities:
                    with ui.card().classes("w-full p-4 gap-3 shadow-none border-0"):
                        rows = rows_by_kind[kind]
                        if kind == "counterparty":
                            total = len(rows)
                            page_count = max(1, (total + 49) // 50)
                            self.counterparty_page["value"] = min(
                                self.counterparty_page["value"], page_count,
                            )
                            page = self.counterparty_page["value"]
                            start = (page - 1) * 50
                            end = min(start + 50, total)
                            with ui.row().classes("w-full items-center gap-2"):
                                ui.label(title).classes("text-lg font-semibold")
                                ui.element("div").classes("flex-grow")
                                ui.button(icon="chevron_left",
                                          on_click=lambda: self.change_counterparty_page(-1)).props(
                                    f"round outline {'disable' if page <= 1 else ''}").tooltip("Previous page")
                                ui.label(f"{start + 1 if total else 0}-{end}/{total}").classes(
                                    "text-sm text-slate-400")
                                ui.button(icon="chevron_right",
                                          on_click=lambda: self.change_counterparty_page(1)).props(
                                    f"round outline {'disable' if page >= page_count else ''}").tooltip("Next page")
                            rows = rows[start:end]
                        else:
                            with ui.row().classes("w-full items-center justify-between"):
                                ui.label(title).classes("text-lg font-semibold")
                                ui.label(str(len(rows))).classes("text-sm text-slate-400")
                        self.render_management_table(kind, rows, columns_by_kind[kind])
                    self.form_containers[kind] = ui.card().classes("w-full p-4 gap-3 shadow-none border-0")
        self.render_management_forms()

    def render_management_table(self, kind: str, rows: list[dict], columns: list[dict]) -> dict | None:
        """Render the table and return its selected record.

        Args:
            kind: Entity type represented by the table.
            rows: Records displayed in the table.
            columns: NiceGUI column definitions for the records.

        Returns:
            Selected record, or ``None`` if no displayed row is selected.
        """
        return render_management_table(self, kind, rows, columns)

    def render_management_rules(self, table_name: str, owner_column: str, owner_id: int) -> None:
        """Render the matching-rule editor for the selected record.

        Args:
            table_name: Matching-rule table to query.
            owner_column: Foreign-key column linking rules to their owner.
            owner_id: ID of the entity whose rules are displayed.
        """
        render_management_rules(self, table_name, owner_column, owner_id)

    def remove_rule(self, table_name: str, rule_id: int) -> None:
        """Delete a matching rule and redraw affected pages.

        Args:
            table_name: Matching-rule table containing the rule.
            rule_id: ID of the rule to delete.
        """
        remove_rule(self, table_name, rule_id)
