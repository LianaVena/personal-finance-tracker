"""Validation and recovery checks for UI callbacks with synthetic dependencies."""

import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

from tests.support.pages import InterfacePageTestCase


class InterfaceFailureTests(InterfacePageTestCase):
    """Verify failed actions preserve drafts, selection, and navigation state."""

    def management_data(self):
        """Build a synthetic record for each editable management entity.

        Returns:
            Management data containing valid category and subscription defaults.
        """
        return self.modules["manage.models"].ManagementData(
            {1: "Food"}, {None: "Unassigned", 7: "Food / Meals"},
            [{"id": 3, "name": "Shop", "default_subcategory_id": 7, "default_is_subscription": 0}],
            [{"id": 4, "name": "Music", "counterparty_id": 3, "counterparty_name": "Shop",
              "billing_period": "monthly", "expected_amount": -999, "currency": "EUR", "is_active": 1}],
            [(7, 1, "Meals", "Food", None, None, None)], {"category": [{"id": 1, "name": "Food"}]}, {},
        )

    def test_duplicate_management_edits_report_errors_and_keep_drafts(self):
        """Retain all entity drafts when unique constraints reject an edit."""
        self.manage.render_management = Mock()
        for kind, item_id in (("category", 1), ("subcategory", 7), ("counterparty", 3), ("subscription", 4)):
            with self.subTest(kind=kind):
                self.modules["manage.edit_forms"].render_edit_form(self.manage, self.management_data(), kind, item_id)
                self.connection.execute.side_effect = sqlite3.IntegrityError("Synthetic duplicate")
                self.ui.find("button", title="Save " + kind)[-1].handlers["click"]()
                self.assertIn((kind, item_id), self.manage.drafts)
                self.assertEqual(self.ui.notify.call_args.kwargs["type"], "warning")
        self.manage.render_management.assert_not_called()
        self.actions.refresh_matching.assert_not_called()

    def test_management_creation_requires_name_parent_and_unique_category(self):
        """Reject incomplete creation forms and report duplicate category names."""
        module = self.modules["manage.create_forms"]
        self.manage.render_management = Mock()
        for kind in ("category", "subcategory"):
            module.render_create_form(self.manage, self.management_data(), kind)
            save = self.ui.find("button", title="Create " + kind)[-1]
            save.handlers["click"]()
            self.connection.execute.assert_not_called()
            self.ui.find("input", label="Category name" if kind == "category" else "Subcategory name")[
                -1].value = "Name"
            if kind == "subcategory":
                self.ui.find("select", label="Parent category")[-1].value = 1
            self.connection.execute.side_effect = sqlite3.IntegrityError("Synthetic duplicate")
            save.handlers["click"]()
            self.assertIn((kind, None), self.manage.drafts)
            self.connection.execute.reset_mock(side_effect=True)
        self.manage.render_management.assert_not_called()

    def test_invalid_edited_color_and_subscription_currency_do_not_write(self):
        """Reject unsupported colors and invalid currency codes before database updates."""
        module = self.modules["manage.edit_forms"]
        self.manage.management_draft("subcategory", 7, {"parent": 1, "name": "Meals", "color": "#FFFFFF"})
        module.render_edit_form(self.manage, self.management_data(), "subcategory", 7)
        self.ui.find("button", title="Save subcategory")[-1].handlers["click"]()
        module.render_edit_form(self.manage, self.management_data(), "subscription", 4)
        self.ui.find("select", label="Currency")[-1].value = "EU"
        self.ui.find("button", title="Save subscription")[-1].handlers["click"]()
        self.connection.execute.assert_not_called()
        self.actions.render_subscriptions.assert_not_called()

    def test_management_counterparty_rows_show_present_and_missing_default_categories(self):
        """Resolve default category labels and retain placeholders for unknown defaults."""
        self.modules["manage.page"]._counterparties.return_value = [
            {"id": 3, "name": "Known", "default_subcategory_id": 7},
            {"id": 4, "name": "Unknown", "default_subcategory_id": None},
        ]
        self.connection.execute.return_value.fetchall.return_value = [
            (7, 1, "Meals", "Food", None, None, None),
        ]
        self.manage.render_management()
        table = next(table for table in self.ui.find("table")
                     if any(column["field"] == "default_category" for column in table.kwargs["columns"]))
        rows = table.kwargs["rows"]
        self.assertEqual((rows[0]["default_category"], rows[0]["default_sub"]), ("Food", "Meals"))
        self.assertNotEqual(rows[1]["default_category"], "Food")
        self.assertEqual(rows[1]["default_category"], rows[1]["default_sub"])

    def test_review_creation_reports_incomplete_duplicate_and_invalid_color(self):
        """Keep Review drafts through required-field, uniqueness, and palette failures."""
        module = self.modules["review.creation_forms"]
        module.render_creation_forms(self.review)
        for title in ("Add category", "Add subcategory"):
            self.ui.find("button", title=title)[-1].handlers["click"]()
        self.connection.execute.assert_not_called()
        self.ui.find("input", label="Subcategory name")[-1].value = "Meals"
        self.ui.find("select", label="Parent category")[-1].value = 1
        self.connection.execute.side_effect = sqlite3.IntegrityError("Synthetic duplicate")
        self.ui.find("button", title="Add subcategory")[-1].handlers["click"]()
        self.assertEqual(self.ui.notify.call_args.kwargs["type"], "warning")
        self.connection.execute.reset_mock(side_effect=True)
        self.review.form_values.update(subcategory_name="Meals", subcategory_parent=1, subcategory_color="#FFFFFF")
        module.render_creation_forms(self.review)
        self.ui.find("button", title="Add subcategory")[-1].handlers["click"]()
        self.connection.execute.assert_not_called()
        self.assertEqual(self.review.form_values["subcategory_color"], "#FFFFFF")

    def test_review_subscription_rejects_invalid_currency(self):
        """Prevent subscription creation when its currency is not a three-letter code."""
        module = self.modules["review.creation_forms"]
        self.review.form_values.update(subscription_amount="-10", subscription_currency="12X")
        module.render_creation_forms(self.review)
        self.ui.find("button", title="Add subscription")[-1].handlers["click"]()
        module._create_subscription.assert_not_called()
        self.actions.render_subscriptions.assert_not_called()

    def test_rule_update_and_delete_failures_do_not_refresh_matching(self):
        """Report rejected rule changes without rebuilding the management state."""
        module = self.modules["manage.rule_controls"]
        module._rules.return_value = [(1, "description", "SHOP")]
        module._update_rule.side_effect = ValueError("Duplicate rule")
        self.manage.render_management_rules("counterparties_match_rules", "counterparty_id", 3)
        self.ui.find("button", title="Save matching rule")[-1].handlers["click"]()
        module._delete_rule.side_effect = sqlite3.DatabaseError("Synthetic delete failure")
        self.ui.find("button", title="Delete matching rule")[-1].handlers["click"]()
        self.actions.refresh_matching.assert_not_called()
        self.ui.notify.assert_called_with("Could not remove rule: Synthetic delete failure", type="negative")

    def test_review_save_refuses_missing_and_incomplete_transactions(self):
        """Keep incomplete payments in review and report payments that disappeared."""
        module = self.modules["review.page"]
        self.review.render_transactions = Mock()
        self.review.save_transaction("gone")
        self.ui.notify.assert_called_with("Transaction is no longer available", type="negative")
        module._review_transactions.return_value = [self.transaction()]
        self.review.save_transaction("tx-1")
        self.assertEqual(self.ui.notify.call_args.kwargs["type"], "warning")
        self.review.render_transactions.assert_not_called()

    def test_review_refresh_handles_missing_active_and_incomplete_pinned_items(self):
        """Update queue position when edited transactions are incomplete or disappear."""
        module = self.modules["review.page"]
        self.review.refresh_matching()
        self.assertIsNone(self.review.state["pinned_id"])
        module._review_transactions.return_value = [self.transaction("first"), self.transaction("second")]
        self.review.render_transactions = Mock()
        self.review.refresh_after_edit("second")
        self.assertEqual(self.review.state["offset"], 1)
        self.review.refresh_after_edit("gone")
        self.assertIsNone(self.review.state["pinned_id"])
        self.review.state["pinned_id"] = "second"
        type(self.review).render_transactions(self.review)
        self.assertIsNone(self.review.state["pinned_id"])

    def test_pinned_navigation_at_boundary_keeps_current_item(self):
        """Keep the pinned transaction visible when no neighbor exists in that direction."""
        module = self.modules["review.page"]
        module._review_transactions.return_value = [self.transaction("done", complete=True)]
        self.review.state["pinned_id"] = "done"
        self.review.render_transactions = Mock()
        self.review.change_page(1)
        self.assertEqual(self.review.state["pinned_id"], "done")
        self.review.render_transactions.assert_not_called()

    def test_missing_split_count_reports_failure_and_preserves_expansion(self):
        """Handle a missing split-count query result without collapsing the editor."""
        self.review.state["expanded_splits"].add("tx-1")
        self.review.refresh_after_edit = Mock()
        self.connection.execute.return_value.fetchone.return_value = None
        self.review.delete_split("tx-1", 11)
        self.review.refresh_after_edit.assert_not_called()
        self.assertIn("tx-1", self.review.state["expanded_splits"])
        self.ui.notify.assert_called_with("Split count query returned no result", type="warning")

    def test_split_control_write_failures_report_errors_without_refresh(self):
        """Retain split controls when note, category, or subscription saves fail."""
        module = self.modules["review.split_controls"]
        self.review.refresh_after_edit = Mock()
        transaction = self.transaction()
        split = transaction["splits"][0]
        split.update(is_subscription=1, subscription_id=4)
        for name in ("_save_split_note", "_save_subcategory", "_save_subscription_decision"):
            getattr(module, name).side_effect = sqlite3.DatabaseError("Synthetic write failure")
        module.render_split_editor(self.review, transaction, split, transaction["splits"], {}, {4: "Music"})
        for kind, label, value in (("input", "Split note", "Note"), ("select", "Subcategory", 7),
                                   ("select", "Subscription", "no"), ("select", "Linked subscription", 4)):
            with self.subTest(control=label):
                self.ui.find(kind, label=label)[-1].handlers["value"](SimpleNamespace(value=value))
                self.assertEqual(self.ui.notify.call_args.kwargs["type"], "negative")
        self.review.refresh_after_edit.assert_not_called()

    def test_transaction_write_failures_keep_current_transaction_visible(self):
        """Report note, counterparty, and category write failures in both card layouts."""
        module = self.modules["review.transaction_card"]
        self.review.refresh_after_edit = Mock()
        self.review.refresh_matching = Mock()
        for name in ("_save_transaction_note", "_save_counterparty", "_save_subcategory"):
            getattr(module, name).side_effect = sqlite3.DatabaseError("Synthetic write failure")
        for expanded in (False, True):
            self.review.state["expanded_splits"] = {"tx-1"} if expanded else set()
            module.render_transaction_card(self.review, self.transaction(), {}, {}, {})
            self.ui.find("select", label="Counterparty")[-1].handlers["value"](SimpleNamespace(value=3))
            self.ui.find("textarea", label="Transaction note")[-1].handlers["value"](SimpleNamespace(value="Note"))
            if not expanded:
                self.ui.find("select", label="Subcategory")[-1].handlers["value"](SimpleNamespace(value=7))
        self.review.refresh_after_edit.assert_not_called()
        self.review.refresh_matching.assert_not_called()

    def test_multiple_split_summary_empty_split_message_and_delete_callback(self):
        """Show appropriate split summaries and keep delete callbacks tied to their split."""
        module = self.modules["review.transaction_card"]
        self.review.delete_split = Mock()
        transaction = self.transaction()
        transaction["value_date"] = transaction["booking_date"]
        transaction["splits"].append({**transaction["splits"][0], "id": 12})
        module.render_transaction_card(self.review, transaction, {}, {}, {})
        self.assertFalse(self.ui.find("label", label="Value date:"))
        self.assertTrue(any("2 splits" in label.text for label in self.ui.find("label")))
        self.review.state["expanded_splits"].add("tx-1")
        module.render_transaction_card(self.review, transaction, {}, {}, {})
        self.ui.find("button", title="Delete split")[-1].handlers["click"]()
        self.review.delete_split.assert_called_once_with("tx-1", 12)
        transaction["splits"] = []
        module.render_transaction_card(self.review, transaction, {}, {}, {})
        self.assertTrue(any("amount is zero" in label.text for label in self.ui.find("label")))

    def test_exit_missing_integrity_result_does_not_shutdown(self):
        """Restore the exit button when the integrity query returns no result."""
        module = self.modules["interface"]
        self.connection.execute.return_value.fetchone.return_value = None
        from unittest.mock import patch
        with patch("src.interface.interface.UiCoordinator"), patch("src.interface.interface.app") as app:
            module.build_ui(self.transaction_path, self.finance_path)
            button = self.ui.find("button", label="Exit")[-1]
            self.run_exit(button.handlers["click"])
            self.assertFalse(button.disabled)
            app.shutdown.assert_not_called()
