"""UI composition and callback tests using synthetic records and mocked services."""

from __future__ import annotations

import importlib
import sqlite3
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch


class Element:
    """Record the public element operations needed by the renderers."""

    def __init__(self, kind: str, args: tuple = (), **kwargs: Any):
        self.kind, self.args = kind, args
        self.kwargs: dict[str, Any] = kwargs
        self.value = kwargs.get("value")
        self.handlers = {}
        self.slots = {}
        self.title = None
        self.disabled = False
        self.text = args[0] if kind == "label" and args else ""
        if "on_click" in kwargs:
            self.handlers["click"] = kwargs["on_click"]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def classes(self, *_):
        return self

    props = classes
    style = classes

    def tooltip(self, title):
        self.title = title
        return self

    def on(self, event, callback):
        self.handlers[event] = callback
        return self

    def on_value_change(self, callback):
        return self.on("value", callback)

    def add_slot(self, name, content):
        self.slots[name] = content

    def clear(self):
        pass

    def set_text(self, text):
        self.text = text

    def disable(self):
        self.disabled = True

    def enable(self):
        self.disabled = False


class FakeUi:
    """Build controls without NiceGUI, a browser, files, or a server."""

    def __init__(self):
        self.elements = []
        self.notify = Mock()
        self.run_javascript = AsyncMock()

    def __getattr__(self, kind):
        def create(*args, **kwargs):
            element = Element(kind, args, **kwargs)
            self.elements.append(element)
            return element

        return create

    def find(self, kind, label=None, title=None):
        return [
            element for element in self.elements if element.kind == kind
                                                    and (label is None or (element.args and element.args[0] == label)
                                                         or element.kwargs.get("label") == label)
                                                    and (title is None or element.title == title)
        ]


class InterfacePageTests(unittest.TestCase):
    """Verify the state and behavior most vulnerable to UI extraction."""

    MODULES = (
        "interface", "styles", "coordinator", "review.page", "review.transaction_card",
        "review.split_controls", "review.creation_forms", "manage.page", "manage.models",
        "manage.table_view", "manage.rule_controls", "manage.create_forms",
        "manage.edit_forms", "subscriptions.page",
    )

    def setUp(self):
        self.ui = FakeUi()
        fake_nicegui = types.ModuleType("nicegui")
        fake_nicegui.ui, fake_nicegui.app = self.ui, Mock()
        self.enterContext(patch.dict(sys.modules, {"nicegui": fake_nicegui}))
        self.modules = {
            name: importlib.import_module("src.interface." + name) for name in self.MODULES
        }
        self.connection = MagicMock()
        self.connection.__enter__.return_value = self.connection
        self.connection.execute.return_value.fetchall.return_value = []
        self.connection.execute.return_value.fetchone.return_value = ("ok",)
        defaults = {
            "_categories": {}, "_counterparties": [], "_subcategories": {None: "Unassigned"},
            "_subscriptions": [], "_subscription_categories": {}, "_rules": [],
            "_review_transactions": [], "apply_matching_rules": 0,
        }
        for module in self.modules.values():
            if hasattr(module, "ui"):
                self.enterContext(patch.object(module, "ui", self.ui))
            if hasattr(module, "connect_database"):
                self.enterContext(patch.object(module, "connect_database", return_value=self.connection))
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
        return self.modules["review.page"].ReviewPage(
            self.transaction_path, self.finance_path, self.actions, Element("column"), Element("column"),
        )

    def run_exit(self, callback):
        """Complete the callback with mocked awaits without creating an OS event loop."""
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
        return {
            "id": transaction_id, "booking_date": booking_date, "amount": -500, "currency": "EUR",
            "note": None, "counterparty_id": None,
            "review_reasons": [] if complete else ["A split needs a subcategory"],
            "splits": [{
                "id": split_id, "amount": -500, "note": None, "subcategory_id": None,
                "is_subscription": None, "subscription_id": None, "excluded": 0,
            }],
        }

    def test_construction_creates_independent_state_without_queries(self):
        other = self.new_review()
        self.review.state["expanded_splits"].add("tx-1")
        self.review.form_values["category_name"] = "Draft"
        self.assertEqual(other.state["expanded_splits"], set())
        self.assertEqual(other.form_values["category_name"], "")
        second_manage = self.modules["manage.page"].ManagePage(
            self.transaction_path, self.finance_path, self.actions, Element("column"),
        )
        self.manage.management_draft("category", None, {"name": "Draft"})
        self.assertEqual(second_manage.drafts, {})
        self.modules["review.page"]._review_transactions.assert_not_called()
        self.modules["manage.page"].connect_database.assert_not_called()

    def test_matching_advances_only_when_requested_and_completed(self):
        module = self.modules["review.page"]
        self.review.state["active_id"] = "tx-1"
        module._review_transactions.side_effect = [
            [self.transaction()], [self.transaction(complete=True)],
        ]
        self.review.refresh_matching(advance_if_complete=True)
        self.assertIsNone(self.review.state["pinned_id"])
        module.apply_matching_rules.assert_called_once_with(self.transaction_path, self.finance_path)
        self.review.refresh_matching()
        self.assertEqual(self.review.state["pinned_id"], "tx-1")

    def test_edit_and_save_preserve_then_release_completed_transaction(self):
        module = self.modules["review.page"]
        module._review_transactions.return_value = [self.transaction(complete=True)]
        self.review.render_transactions = Mock()
        self.review.refresh_after_edit("tx-1")
        self.assertEqual(self.review.state["pinned_id"], "tx-1")
        self.review.save_transaction("tx-1")
        self.assertIsNone(self.review.state["pinned_id"])
        self.assertEqual(self.review.render_transactions.call_count, 2)

    def test_pinned_navigation_selects_neighbor_and_respects_boundaries(self):
        module = self.modules["review.page"]
        module._review_transactions.return_value = [
            self.transaction("new", booking_date="2026-01-03"),
            self.transaction("pin", complete=True),
            self.transaction("old", booking_date="2026-01-01"),
        ]
        self.review.render_transactions = Mock()
        self.review.state["pinned_id"] = "pin"
        self.review.change_page(1)
        self.assertEqual(self.review.state["offset"], 1)
        self.assertIsNone(self.review.state["pinned_id"])
        self.review.change_page(1)
        self.assertEqual(self.review.state["offset"], 1)
        self.review.state["pinned_id"] = "pin"
        self.review.change_page(-1)
        self.assertEqual(self.review.state["offset"], 0)

    def test_management_drafts_survive_selection_and_binding(self):
        defaults = {"name": "Original"}
        draft = self.manage.management_draft("category", 1, defaults)
        control = Element("input")
        self.manage.bind_management_draft(draft, "name", control)
        control.handlers["value"](SimpleNamespace(value="Edited"))
        self.manage.render_management = Mock()
        self.manage.select_management_item("category", {"id": 1})
        self.manage.select_management_item("category", {"id": 1})
        self.assertIsNone(self.manage.selection["category"])
        self.assertIs(self.manage.management_draft("category", 1, defaults), draft)
        self.assertEqual(draft["name"], "Edited")
        self.assertEqual(defaults["name"], "Original")

    def test_counterparty_pagination_is_clamped(self):
        self.modules["manage.page"]._counterparties.return_value = [{"id": i} for i in range(51)]
        self.manage.render_management = Mock()
        for direction, expected in ((1, 2), (1, 2), (-1, 1), (-1, 1)):
            self.manage.change_counterparty_page(direction)
            self.assertEqual(self.manage.counterparty_page["value"], expected)

    def test_compact_category_callback_keeps_original_split_id(self):
        module = self.modules["review.transaction_card"]
        self.review.refresh_matching = Mock()
        self.review.refresh_after_edit = Mock()
        module.render_transaction_card(self.review, self.transaction(), {}, {}, {})
        first_control = self.ui.find("select", label="Subcategory")[-1]
        module.render_transaction_card(self.review, self.transaction("tx-2", 22), {}, {}, {})
        first_control.handlers["value"](SimpleNamespace(value=7))
        module._save_subcategory.assert_called_once_with(self.finance_path, 11, 7)
        self.review.refresh_after_edit.assert_called_once_with("tx-1")

    def test_expanded_split_callback_keeps_original_split_id(self):
        module = self.modules["review.split_controls"]
        self.review.refresh_matching = Mock()
        self.review.refresh_after_edit = Mock()
        controls = []
        for tx_id, split_id in (("tx-1", 11), ("tx-2", 22)):
            transaction = self.transaction(tx_id, split_id)
            module.render_split_editor(self.review, transaction, transaction["splits"][0],
                                       transaction["splits"], {}, {})
            controls.append(self.ui.find("select", label="Subcategory")[-1])
        controls[0].handlers["value"](SimpleNamespace(value=7))
        module._save_subcategory.assert_called_once_with(self.finance_path, 11, 7)
        self.review.refresh_after_edit.assert_called_once_with("tx-1")

    def test_rule_callbacks_keep_their_own_rule_and_controls(self):
        module = self.modules["manage.rule_controls"]
        module._rules.return_value = [(1, "description", "First"), (2, "description", "Second")]
        self.manage.render_management = Mock()
        module.render_management_rules(self.manage, "counterparties_match_rules", "counterparty_id", 9)
        self.ui.find("button", title="Save matching rule")[0].handlers["click"]()
        module._update_rule.assert_called_once_with(
            self.finance_path, "counterparties_match_rules", "counterparty_id", 9, 1, "description", "First",
        )
        self.actions.refresh_matching.assert_called_once()
        self.actions.render_transactions.assert_called_once()

    def test_creation_form_keeps_values_and_clears_only_successful_fields(self):
        self.review.form_values.update(category_name="New category", counterparty_name="Keep")
        self.review.render_configuration = Mock()
        module = self.modules["review.creation_forms"]
        module.render_creation_forms(self.review)
        self.assertEqual(self.ui.find("input", label="Category name")[-1].value, "New category")
        self.ui.find("button", title="Add category")[-1].handlers["click"]()
        self.connection.execute.assert_called_once_with("INSERT INTO categories(name) VALUES (?)", ("New category",))
        self.assertEqual(self.review.form_values["category_name"], "")
        self.assertEqual(self.review.form_values["counterparty_name"], "Keep")
        self.review.render_configuration.assert_called_once()
        self.actions.render_management.assert_called_once()

    def test_manage_create_and_edit_forms_capture_their_entity_ids(self):
        data = self.modules["manage.models"].ManagementData(
            {1: "Food"}, {None: "Unassigned"}, [], [], [],
            {"category": [{"id": 1, "name": "First"}, {"id": 2, "name": "Second"}]}, {},
        )
        self.manage.render_management = Mock()
        edit = self.modules["manage.edit_forms"]
        edit.render_edit_form(self.manage, data, "category", 1)
        first_save = self.ui.find("button", title="Save category")[-1]
        self.ui.find("input", label="Category name")[-1].value = "Edited"
        edit.render_edit_form(self.manage, data, "category", 2)
        first_save.handlers["click"]()
        self.connection.execute.assert_called_once_with(
            "UPDATE categories SET name = ? WHERE id = ?", ("Edited", 1),
        )
        self.connection.execute.reset_mock()
        self.modules["manage.create_forms"].render_create_form(self.manage, data, "category")
        self.ui.find("input", label="Category name")[-1].value = "Created"
        self.ui.find("button", title="Create category")[-1].handlers["click"]()
        self.connection.execute.assert_called_once_with(
            "INSERT INTO categories(name) VALUES (?)", ("Created",),
        )
        self.assertNotIn(("category", None), self.manage.drafts)

    def test_subscription_totals_and_active_change_refresh(self):
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

    def test_coordinator_constructs_all_pages_before_rendering_in_original_order(self):
        module = self.modules["coordinator"]
        with patch("src.interface.coordinator.ReviewPage") as review_type, \
                patch("src.interface.coordinator.ManagePage") as manage_type, \
                patch("src.interface.coordinator.SubscriptionsPage") as subscriptions_type:
            coordinator = module.UiCoordinator(
                self.transaction_path, self.finance_path,
                Element("column"), Element("column"), Element("column"), Element("column"),
            )
            review_type.return_value.render_transactions.assert_not_called()
            manage_type.return_value.render_management.assert_not_called()
            subscriptions_type.return_value.render_subscriptions.assert_not_called()
            order = Mock()
            order.attach_mock(review_type.return_value.render_transactions, "transactions")
            order.attach_mock(review_type.return_value.render_configuration, "creation")
            order.attach_mock(manage_type.return_value.render_management, "manage")
            order.attach_mock(subscriptions_type.return_value.render_subscriptions, "subscriptions")
            coordinator.render_initial()
            self.assertEqual([entry[0] for entry in order.mock_calls],
                             ["transactions", "creation", "manage", "subscriptions"])
            coordinator.refresh_matching(advance_if_complete=True)
            review_type.return_value.refresh_matching.assert_called_once_with(True)

    def test_shell_preserves_tabs_and_exit_success(self):
        module = self.modules["interface"]
        with patch("src.interface.interface.UiCoordinator") as coordinator_type, \
                patch("src.interface.interface.app") as app, \
                patch("src.interface.interface.asyncio.sleep", new_callable=AsyncMock):
            module.build_ui(self.transaction_path, self.finance_path)
            self.assertEqual([element.args[0] for element in self.ui.find("tab")],
                             ["Review", "Subscriptions", "Manage"])
            coordinator_type.return_value.render_initial.assert_called_once()
            exit_button = self.ui.find("button", label="Exit")[-1]
            self.run_exit(exit_button.handlers["click"])
            self.assertTrue(exit_button.disabled)
            self.assertEqual(self.connection.execute.call_count, 2)
            self.ui.run_javascript.assert_awaited_once()
            app.shutdown.assert_called_once()

    def test_exit_failure_restores_button_and_keeps_app_running(self):
        module = self.modules["interface"]
        self.connection.execute.return_value.fetchone.return_value = ("damaged",)
        with patch("src.interface.interface.UiCoordinator"), patch("src.interface.interface.app") as app:
            module.build_ui(self.transaction_path, self.finance_path)
            exit_button = self.ui.find("button", label="Exit")[-1]
            self.run_exit(exit_button.handlers["click"])
            self.assertFalse(exit_button.disabled)
            app.shutdown.assert_not_called()
            self.ui.run_javascript.assert_not_awaited()
            self.assertTrue(any("Could not exit safely" in element.text
                                for element in self.ui.find("label")))

    def test_write_error_does_not_clear_creation_draft(self):
        self.review.form_values["category_name"] = "Keep on failure"
        self.connection.execute.side_effect = sqlite3.IntegrityError("Duplicate")
        self.modules["review.creation_forms"].render_creation_forms(self.review)
        self.ui.find("button", title="Add category")[-1].handlers["click"]()
        self.assertEqual(self.review.form_values["category_name"], "Keep on failure")
        self.actions.render_management.assert_not_called()
        self.ui.notify.assert_called_with("A category with that name already exists", type="warning")
