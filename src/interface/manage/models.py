"""Typed data passed to management form components."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ManagementData:
    """Hold the query results and table definitions for one Manage redraw."""

    categories: dict[int, str]
    subcategory_options: dict[int | None, str]
    counterparties: list[dict]
    subscriptions: list[dict]
    subcategories: list[tuple[int, int, str, str]]
    rows_by_kind: dict[str, list[dict]]
    columns_by_kind: dict[str, list[dict]]
