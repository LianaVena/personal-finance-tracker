"""Subscription page totals, tables, and active-state callbacks."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from nicegui import ui

from src.database import connect_database
from .queries import subscription_category_details as _subscription_category_details
from ..common import format_money as _format_money
from ..common import notify as _notify
from ..context import UiActions
from ..manage.tables import subscriptions as _subscriptions


class SubscriptionsPage:
    """Render subscription totals and updates for one UI instance."""

    def __init__(self, transaction_db_path: Path, finance_db_path: Path,
                 actions: UiActions, content: ui.column) -> None:
        """Initialize the subscription controller without loading data.

        Args:
            transaction_db_path: Database containing payment booking dates.
            finance_db_path: Database containing subscriptions and split classifications.
            actions: Cross-page refresh operations supplied by the coordinator.
            content: Container for subscription totals and tables.
        """
        self.transaction_db_path = transaction_db_path
        self.finance_db_path = finance_db_path
        self.actions = actions
        self.content = content

    def render_subscriptions(self) -> None:
        """Render active and inactive subscriptions with their totals."""
        self.content.clear()
        subscriptions = _subscriptions(self.finance_db_path)
        categories_by_subscription = _subscription_category_details(self.transaction_db_path, self.finance_db_path)
        columns = [
            {"name": "name", "label": "Name", "field": "name", "sortable": True, "align": "left",
             "style": "width: 20%; white-space: normal;", "headerStyle": "width: 20%; white-space: normal;"},
            {"name": "category", "label": "Category", "field": "category", "sortable": True,
             "style": "width: 24%; white-space: normal;", "headerStyle": "width: 24%; white-space: normal;"},
            {"name": "billing_period", "label": "Billing period", "field": "billing_period",
             "sortable": True, "align": "right", "style": "width: 15%; white-space: normal;",
             "headerStyle": "width: 15%; white-space: normal;"},
            {"name": "monthly_amount", "label": "Monthly", "field": "monthly_amount",
             "sortable": True, "align": "right", "style": "width: 15%; white-space: normal;",
             "headerStyle": "width: 15%; white-space: normal;"},
            {"name": "yearly_amount", "label": "Yearly", "field": "yearly_amount",
             "sortable": True, "align": "right", "style": "width: 16%; white-space: normal;",
             "headerStyle": "width: 16%; white-space: normal;"},
            {"name": "is_active", "label": "Active", "field": "is_active", "align": "center",
             "style": "width: 10%;", "headerStyle": "width: 10%; white-space: normal;"},
        ]
        with self.content:
            with ui.element("div").classes("w-full grid grid-cols-1 md:grid-cols-2 gap-4 items-start"):
                for is_active, title in ((True, "Active subscriptions"), (False, "Inactive subscriptions")):
                    rows = []
                    totals_by_period: dict[str, dict[str, int]] = {"monthly": {}, "yearly": {}}
                    for subscription in subscriptions:
                        if bool(subscription["is_active"]) != is_active:
                            continue
                        amount = subscription["expected_amount"]
                        if amount is not None:
                            period_totals = totals_by_period[subscription["billing_period"]]
                            currency_code = subscription["currency"]
                            period_totals[currency_code] = period_totals.get(currency_code, 0) + abs(amount)
                            absolute_amount = abs(amount)
                            monthly_amount = (
                                absolute_amount if subscription["billing_period"] == "monthly" else
                                int((Decimal(absolute_amount) / 12).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                            )
                            yearly_amount = (
                                absolute_amount * 12 if subscription["billing_period"] == "monthly" else
                                absolute_amount
                            )
                            monthly_display = _format_money(monthly_amount, currency_code, absolute=True)
                            yearly_display = _format_money(yearly_amount, currency_code, absolute=True)
                        else:
                            monthly_display = yearly_display = "—"
                        rows.append({
                            "id": subscription["id"],
                            "name": subscription["name"],
                            "is_active": bool(subscription["is_active"]),
                            "billing_period": subscription["billing_period"].capitalize(),
                            "category": categories_by_subscription.get(subscription["id"], ("—", None))[0],
                            "color": categories_by_subscription.get(subscription["id"], ("—", None))[1],
                            "monthly_amount": monthly_display,
                            "yearly_amount": yearly_display,
                            "monthly_calculated": amount is not None
                                                  and subscription["billing_period"] == "yearly",
                            "yearly_calculated": amount is not None
                                                 and subscription["billing_period"] == "monthly",
                        })
                    if is_active:
                        for currency_code, monthly_total in totals_by_period["monthly"].items():
                            totals_by_period["yearly"][currency_code] = (
                                    totals_by_period["yearly"].get(currency_code, 0) + monthly_total * 12
                            )
                    with ui.card().classes("w-full p-4 shadow-none border-0"):
                        with ui.row().classes("w-full items-center justify-between gap-3"):
                            ui.label(title).classes("text-lg font-semibold")
                            if is_active:
                                def format_period_total(billing_period: str) -> str:
                                    """Format the calculated active total for a billing period.

                                    Args:
                                        billing_period: Billing period key, ``monthly`` or ``yearly``.

                                    Returns:
                                        Currency totals formatted for display.
                                    """
                                    currency_totals = totals_by_period[billing_period]
                                    return ", ".join(
                                        _format_money(total, total_currency, absolute=True)
                                        for total_currency, total in sorted(currency_totals.items())
                                    ) or "—"

                                with ui.row().classes("items-center gap-3"):
                                    for period in ("monthly", "yearly"):
                                        with ui.row().classes("items-center gap-1"):
                                            ui.label("fx").classes(
                                                "text-xs font-semibold text-slate-500").tooltip("Calculated total")
                                            ui.label(
                                                f"{period.capitalize()}: {format_period_total(period)}"
                                            ).classes("text-sm text-slate-400")
                        table = ui.table(columns=columns, rows=rows, row_key="id").props(
                            'table-style="table-layout: fixed; width: 100%"'
                        ).classes("w-full min-w-0")
                        table.add_slot("body-cell", """
                            <q-td :props="props" :style="props.row.color
                                ? {backgroundColor: props.row.color, color: 'white'} : {}">
                                {{ props.value }}
                            </q-td>
                        """)
                        table.add_slot("body-cell-monthly_amount", """
                            <q-td :props="props" :style="props.row.color
                                ? {backgroundColor: props.row.color, color: 'white'} : {}">
                                <div class="row items-center justify-end no-wrap q-gutter-xs">
                                    <span v-if="props.row.monthly_calculated"
                                        class="text-xs font-semibold" style="opacity: 0.7">
                                        fx
                                        <q-tooltip>Calculated equivalent</q-tooltip>
                                    </span>
                                    <span>{{ props.value }}</span>
                                </div>
                            </q-td>
                        """)
                        table.add_slot("body-cell-yearly_amount", """
                            <q-td :props="props" :style="props.row.color
                                ? {backgroundColor: props.row.color, color: 'white'} : {}">
                                <div class="row items-center justify-end no-wrap q-gutter-xs">
                                    <span v-if="props.row.yearly_calculated"
                                        class="text-xs font-semibold" style="opacity: 0.7">
                                        fx
                                        <q-tooltip>Calculated equivalent</q-tooltip>
                                    </span>
                                    <span>{{ props.value }}</span>
                                </div>
                            </q-td>
                        """)
                        table.add_slot("body-cell-is_active", """
                            <q-td :props="props" class="text-right" :style="props.row.color
                                ? {backgroundColor: props.row.color, color: 'white'} : {}">
                                <q-checkbox :model-value="props.row.is_active"
                                    @update:model-value="$parent.$emit('active_change', props.row.id, $event)" />
                            </q-td>
                        """)

                        def change_active(event):
                            """Persist an active-status checkbox change for one subscription.

                            Args:
                                event: Table event carrying the subscription ID and new state.
                            """
                            args = event.args
                            subscription_id, active_value = args[0], args[1]
                            try:
                                with closing(connect_database(self.finance_db_path)) as connection, connection:
                                    connection.execute("UPDATE subscriptions SET is_active = ? WHERE id = ?",
                                                       (int(bool(active_value)), int(subscription_id)))
                                _notify(ui, "Subscription activated" if active_value else "Subscription inactivated",
                                        type="positive")
                                self.render_subscriptions()
                                self.actions.render_management()
                            except (sqlite3.Error, TypeError, ValueError) as error:
                                _notify(ui, f"Could not update subscription status: {error}", type="negative")

                        table.on("active_change", change_active)
