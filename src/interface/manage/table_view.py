"""Selectable management tables."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import ui

if TYPE_CHECKING:
    from .page import ManagePage


def render_management_table(page: ManagePage, kind: str, rows: list[dict], columns: list[dict]) -> dict | None:
    """Render a selectable management table and return its selected row.

    Args:
        page: Manage page supplying selection state and row-click handling.
        kind: Management entity type used by the row-selection handler.
        rows: Records to display in the table.
        columns: NiceGUI column definitions for those records.

    Returns:
        Selected row, or ``None`` when no row is selected.
    """
    table = ui.table(
        rows=rows, columns=columns, row_key="id", pagination=0,
        column_defaults={"align": "left"},
    ).props("dense hide-bottom").classes("manage-table w-full cursor-pointer")
    if kind == "subcategory":
        table.add_slot("body-cell-color", """
            <q-td :props="props">
                <div class="row items-center no-wrap q-gutter-sm">
                    <span v-if="props.value" :style="{backgroundColor: props.value, width: '14px', height: '14px',
                                   borderRadius: '50%', display: 'inline-block'}" aria-hidden="true"></span>
                    <span>{{ props.row.color_name }}</span>
                </div>
            </q-td>
        """)
    if kind == "subscription":
        table.add_slot("body-cell-name", """
            <q-td :props="props">
                <div class="row items-center no-wrap q-gutter-sm">
                    <q-icon :name="props.row.is_active ? 'check' : 'close'"
                        :style="props.row.is_active ? 'color: #4db6ac' : 'color: #d98970'" />
                    <span>{{ props.row.name }}</span>
                </div>
            </q-td>
        """)
    selected = next((row for row in rows if row["id"] == page.selection[kind]), None)
    table.on("row-click", lambda event, key=kind: page.select_management_item(key, event.args[1]))
    return selected
