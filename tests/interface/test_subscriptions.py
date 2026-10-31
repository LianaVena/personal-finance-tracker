"""Subscription totals, colored rows, and active-state refreshes."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from tests.support.pages import InterfacePageTestCase
from tests.support.ui import Element


class SubscriptionsPageTests(InterfacePageTestCase):
    """Subscription totals, colored rows, and active-state refreshes."""

    def test_subscription_totals_and_active_change_refresh(self):
        """Calculate subscription equivalents and refresh pages after status edits."""
        module = self.modules["subscriptions.page"]
        module._subscriptions.return_value = [
            {"id": 1, "name": "Monthly", "expected_amount": -1000, "currency": "EUR",
             "counterparty_name": None, "billing_period": "monthly", "is_active": 1},
            {"id": 2, "name": "Yearly", "expected_amount": -12000, "currency": "EUR",
             "counterparty_name": None, "billing_period": "yearly", "is_active": 1},
        ]
        page = module.SubscriptionsPage(
            self.transaction_path, self.finance_path, self.actions, Element("column"),
        )
        page.render_subscriptions()
        table = self.ui.find("table")[0]
        rows = table.kwargs["rows"]
        self.assertIn("10.00", rows[1]["monthly_amount"])
        self.assertTrue(rows[1]["monthly_calculated"])
        labels = [element.text for element in self.ui.find("label")]
        self.assertTrue(any("Monthly: 10.00" in label for label in labels))
        self.assertTrue(any("Yearly: 240.00" in label for label in labels))
        page.render_subscriptions = Mock()
        table.handlers["active_change"](SimpleNamespace(args=[2, False]))
        self.connection.execute.assert_called_once_with(
            "UPDATE subscriptions SET is_active = ? WHERE id = ?", (0, 2),
        )
        page.render_subscriptions.assert_called_once()
        self.actions.render_management.assert_called_once()

    def test_subscription_rows_use_category_color_in_active_and_inactive_tables(self):
        """Apply category colors to subscription cells while retaining checkbox handlers."""
        module = self.modules["subscriptions.page"]
        module._subscriptions.return_value = [
            {"id": item_id, "name": f"Subscription {item_id}", "expected_amount": None,
             "currency": None, "counterparty_name": None, "billing_period": "monthly", "is_active": active}
            for item_id, active in ((1, 1), (2, 0), (3, 1))
        ]
        module._subscription_category_details.return_value = {
            1: ("Food / Meals", "#FF0000"), 2: ("Travel / Train", "#0000FF"),
        }
        page = module.SubscriptionsPage(self.transaction_path, self.finance_path, self.actions, Element("column"))
        page.render_subscriptions()
        active, inactive = self.ui.find("table")
        self.assertEqual(active.kwargs["rows"][0]["color"], "#FF0000")
        self.assertEqual(active.kwargs["rows"][0]["category"], "Food / Meals")
        self.assertIsNone(active.kwargs["rows"][1]["color"])
        self.assertEqual(inactive.kwargs["rows"][0]["color"], "#0000FF")
        for table in (active, inactive):
            for slot in ("body-cell", "body-cell-monthly_amount", "body-cell-yearly_amount", "body-cell-is_active"):
                self.assertIn("backgroundColor: props.row.color", table.slots[slot])
        self.assertIn("active_change", active.handlers)

    def test_subscription_color_follows_latest_payment_and_requires_shared_color(self):
        """Use latest-payment colors only when every linked split shares one color."""
        module = importlib.import_module("src.interface.subscriptions.queries")
        finance, transactions = MagicMock(), MagicMock()
        finance.execute.return_value.fetchall.return_value = [
            (1, "old", "Food", "Meals", "#FF0000"),
            (1, "new", "Food", "Meals", "#00FF00"),
            (2, "new", "Food", "Meals", None),
            (3, "new", "Food", "Meals", "#00FF00"),
            (3, "new", "Travel", "Train", "#0000FF"),
            (4, "new", "Food", "Meals", "#00FF00"),
            (4, "new", "Food", "Snacks", "#00FF00"),
            (5, "new", "Food", "Meals", "#00FF00"),
            (5, "new", None, None, None),
        ]
        transactions.execute.return_value = [("new", "2026-02-01"), ("old", "2026-01-01")]
        connect = Mock(side_effect=[finance, transactions])
        with patch.dict(vars(module), {"connect_database": connect}):
            details = module.subscription_category_details(self.transaction_path, self.finance_path)
        self.assertEqual(details[1], ("Food / Meals", "#00FF00"))
        self.assertIsNone(details[2][1])
        self.assertIsNone(details[3][1])
        self.assertEqual(details[4], ("Food / Meals, Food / Snacks", "#00FF00"))
        self.assertIsNone(details[5][1])
        self.assertEqual(connect.call_count, 2)
