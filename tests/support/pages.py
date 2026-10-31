"""Isolated UI page fixtures with mocked services and synthetic records."""

from __future__ import annotations

import importlib
import sys
import types
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, Mock, patch

from tests.support.ui import Element, FakeUi

TEST_COLORS = [
    (31, "#FF0000", "#AA0000", "Test Red"),
    (32, "#00FF00", "#00AA00", "Test Green"),
    (33, "#0000FF", "#0000AA", "Test Blue"),
    (34, "#808080", "#606060", "Test Gray"),
]


class InterfacePageTestCase(unittest.TestCase):
    """Provide isolated page controllers and synthetic UI helpers."""

    MODULES = (
        "interface", "styles", "color_grid", "coordinator", "review.page", "review.transaction_card",
        "review.split_controls", "review.creation_forms", "manage.page", "manage.models",
        "manage.table_view", "manage.rule_controls", "manage.create_forms",
        "manage.edit_forms", "subscriptions.page",
    )

    def setUp(self):
        """Create isolated page controllers with mocked UI, queries, and writes."""
        self.ui = FakeUi()
        fake_nicegui = types.ModuleType("nicegui")
        fake_nicegui.ui, fake_nicegui.app = self.ui, Mock()
        self.enterContext(patch.dict(sys.modules, {"nicegui": fake_nicegui}))
        self.modules: dict[str, Any] = {
            name: importlib.import_module("src.interface." + name) for name in self.MODULES
        }
        self.connection = MagicMock()
        self.connection.__enter__.return_value = self.connection
        self.connection.execute.return_value.fetchall.return_value = []
        self.connection.execute.return_value.fetchone.return_value = ("ok",)
        defaults = {
            "_categories": {}, "_colors": TEST_COLORS, "_counterparties": [],
            "_subcategories": {None: "Unassigned"},
            "_subscriptions": [], "_subscription_category_details": {}, "_rules": [],
            "_review_transactions": [], "apply_matching_rules": 0,
        }
        for module in self.modules.values():
            if hasattr(module, "ui"):
                self.enterContext(patch.object(module, "ui", self.ui))
            if hasattr(module, "connect_database"):
                self.enterContext(patch.dict(vars(module), {
                    "connect_database": Mock(return_value=self.connection),
                }))
            for name, result in defaults.items():
                if hasattr(module, name):
                    self.enterContext(patch.object(module, name, return_value=result))
            for name in vars(module):
                if name.startswith(("_save_", "_create_", "_update_", "_add_", "_delete_")):
                    self.enterContext(patch.object(module, name, return_value=101))
        self.actions = Mock()
        self.transaction_path = Path("synthetic-transactions")
        self.finance_path = Path("synthetic-finance")
        self.review = self.new_review()
        self.manage = self.modules["manage.page"].ManagePage(
            self.transaction_path, self.finance_path, self.actions, Element("column"),
        )

    def new_review(self):
        """Create an independent Review controller using synthetic paths.

        Returns:
            Review page with fresh state and fake content containers.
        """
        return self.modules["review.page"].ReviewPage(
            self.transaction_path, self.finance_path, self.actions, Element("column"), Element("column"),
        )

    def run_exit(self, callback):
        """Complete the callback with mocked awaits without creating an OS event loop.

        Args:
            callback: Asynchronous exit handler whose dependencies are mocked.
        """
        coroutine = callback()
        try:
            coroutine.send(None)
        except StopIteration:
            return
        finally:
            coroutine.close()
        self.fail("Exit unexpectedly suspended despite its mocked asynchronous dependencies")

    @staticmethod
    def transaction(transaction_id="tx-1", split_id=11, *, complete=False,
                    booking_date="2026-01-02") -> dict[str, Any]:
        """Build a synthetic transaction and one split for UI tests.

        Args:
            transaction_id: Stable identifier used by captured callbacks.
            split_id: Identifier of the transaction's only split.
            complete: Whether the transaction has no outstanding review reasons.
            booking_date: Date used to order the review queue.

        Returns:
            Transaction record containing synthetic details and split metadata.
        """
        return {
            "id": transaction_id, "booking_date": booking_date, "amount": -500, "currency": "EUR",
            "note": None, "counterparty_id": None,
            "review_reasons": [] if complete else ["A split needs a subcategory"],
            "splits": [{
                "id": split_id, "amount": -500, "note": None, "subcategory_id": None,
                "is_subscription": None, "subscription_id": None, "excluded": 0,
            }],
        }
