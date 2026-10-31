"""Typed data passed to management form components."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ManagementData:
    """Hold the query results and table definitions for one Manage redraw."""

    categories: dict[int, str]
    subcategory_options: dict[int | None, str]
    counterparties: list[dict]
    subscriptions: list[dict]
    subcategories: list[tuple[int, int, str, str, int | None, str | None, str | None]]
    rows_by_kind: dict[str, list[dict]]
    columns_by_kind: dict[str, list[dict]]
    colors: list[tuple[int, str, str, str]] = field(default_factory=list)
