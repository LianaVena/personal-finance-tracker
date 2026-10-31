"""UI success, validation, and failure callbacks using only synthetic services."""

import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tests.support.pages import InterfacePageTestCase


class InterfaceCallbackTests(InterfacePageTestCase):
    """Exercise editable forms, review controls, and error recovery."""

    def management_data(self):
        """Build entity data for creation and editing callbacks.

        Returns:
            Synthetic category, counterparty, and subscription records.
        """
        return self.modules["manage.models"].ManagementData(
            {1: "Food"}, {None: "Unassigned", 7: "Food / Meals"},
            [{"id": 3, "name": "Shop", "default_subcategory_id": 7, "default_is_subscription": 0}],
            [{"id": 4, "name": "Music", "counterparty_id": 3, "counterparty_name": "Shop",
              "billing_period": "monthly", "expected_amount": -999, "currency": "EUR", "is_active": 1}],
            [(7, 1, "Meals", "Food", None, None, None)],
            {"category": [{"id": 1, "name": "Food"}]}, {},
        )

    def test_management_counterparty_creation_forwards_defaults_and_rule(self):
        """Save counterparty fields and refresh affected pages after creation."""
        module = self.modules["manage.create_forms"]
        self.manage.render_management = Mock()
        module.render_create_form(self.manage, self.management_data(), "counterparty")
        self.ui.find("input", label="Counterparty name")[-1].value = "Market"
        self.ui.find("select", label="Default subcategory")[-1].value = 7
        self.ui.find("select", label="Default subscription answer")[-1].value = 0
        self.ui.find("input", label="Contains pattern")[-1].value = "MARKET"
        self.ui.find("button", title="Create counterparty")[-1].handlers["click"]()
        module._create_counterparty.assert_called_once_with(
            self.finance_path, "Market", 7, 0, "payment_message", "MARKET",
        )
        self.assertNotIn(("counterparty", None), self.manage.drafts)
        self.actions.refresh_matching.assert_called_once()

    def test_management_subscription_creation_converts_money_and_currency(self):
        """Convert amount text to cents and normalize the subscription currency."""
        module = self.modules["manage.create_forms"]
        self.manage.render_management = Mock()
        module.render_create_form(self.manage, self.management_data(), "subscription")
        self.ui.find("input", label="Subscription name")[-1].value = "Music"
        self.ui.find("input", label="Expected amount")[-1].value = "-12.34"
        self.ui.find("select", label="Currency")[-1].value = "eur"
        self.ui.find("button", title="Create subscription")[-1].handlers["click"]()
        module._create_subscription.assert_called_once_with(
            self.finance_path, "Music", None, "monthly", -1234, "EUR", None,
        )
        self.actions.render_subscriptions.assert_called_once()

    def test_management_subscription_creation_rejects_invalid_money_and_preserves_draft(self):
        """Reject fractional cents, zero, and unsupported currency formats before saving."""
        module = self.modules["manage.create_forms"]
        module.render_create_form(self.manage, self.management_data(), "subscription")
        for amount, currency in (("1.001", "EUR"), ("0", "EUR"), ("10", "EU"), ("10", "123")):
            with self.subTest(amount=amount, currency=currency):
                self.ui.find("input", label="Expected amount")[-1].value = amount
                self.ui.find("select", label="Currency")[-1].value = currency
                self.ui.find("button", title="Create subscription")[-1].handlers["click"]()
                module._create_subscription.assert_not_called()
                self.assertIn(("subscription", None), self.manage.drafts)
        self.actions.render_subscriptions.assert_not_called()

    def test_management_creation_failure_keeps_drafts_and_avoids_refresh(self):
        """Keep entity drafts and report service failures without showing success."""
        module = self.modules["manage.create_forms"]
        for kind in ("counterparty", "subscription"):
            with self.subTest(kind=kind):
                service = getattr(module, "_create_" + kind)
                service.side_effect = ValueError("Synthetic validation failure")
                module.render_create_form(self.manage, self.management_data(), kind)
                self.ui.find("button", title="Create " + kind)[-1].handlers["click"]()
                self.assertIn((kind, None), self.manage.drafts)
                self.ui.notify.assert_called_with("Synthetic validation failure", type="warning")
        self.actions.refresh_matching.assert_not_called()

    def test_management_counterparty_edit_saves_name_and_defaults(self):
        """Persist the selected counterparty's name and optional default values."""
        self.manage.render_management = Mock()
        self.modules["manage.edit_forms"].render_edit_form(self.manage, self.management_data(), "counterparty", 3)
        self.ui.find("input", label="Counterparty name")[-1].value = "  Market  "
        self.ui.find("select", label="Default subcategory")[-1].value = None
        self.ui.find("select", label="Default subscription")[-1].value = 1
        self.ui.find("button", title="Save counterparty")[-1].handlers["click"]()
        self.connection.execute.assert_called_once_with(
            "UPDATE counterparties SET name = ?, default_subcategory_id = ?, default_is_subscription = ? WHERE id = ?",
            ("Market", None, 1, 3),
        )
        self.assertEqual(self.manage.drafts[("counterparty", 3)]["name"], "Market")
        self.actions.refresh_matching.assert_called_once()

    def test_management_subscription_edit_updates_amount_period_and_active_status(self):
        """Save subscription edits with normalized money and active status."""
        self.manage.render_management = Mock()
        self.modules["manage.edit_forms"].render_edit_form(self.manage, self.management_data(), "subscription", 4)
        self.assertEqual(self.ui.find("input", label="Expected amount")[-1].value, "-9.99")
        self.ui.find("input", label="Expected amount")[-1].value = "-120.00"
        self.ui.find("select", label="Billing period")[-1].value = "yearly"
        self.ui.find("checkbox", label="Active")[-1].value = False
        self.ui.find("button", title="Save subscription")[-1].handlers["click"]()
        self.connection.execute.assert_called_once_with(
            "UPDATE subscriptions SET name = ?, counterparty_id = ?, billing_period = ?, expected_amount = ?, "
            "currency = ?, is_active = ? WHERE id = ?", ("Music", 3, "yearly", -12000, "EUR", 0, 4),
        )
        self.actions.render_subscriptions.assert_called_once()

    def test_subscription_edit_requires_amount_and_currency_together(self):
        """Reject a half-filled amount pair and allow clearing both fields."""
        self.manage.render_management = Mock()
        self.modules["manage.edit_forms"].render_edit_form(self.manage, self.management_data(), "subscription", 4)
        self.ui.find("input", label="Expected amount")[-1].value = ""
        save = self.ui.find("button", title="Save subscription")[-1]
        save.handlers["click"]()
        self.connection.execute.assert_not_called()
        self.actions.render_subscriptions.assert_not_called()
        self.ui.find("select", label="Currency")[-1].value = ""
        save.handlers["click"]()
        self.assertEqual(self.connection.execute.call_args.args[1], ("Music", 3, "monthly", None, None, 1, 4))

    def test_empty_management_names_do_not_write(self):
        """Require a nonblank name before saving any managed entity."""
        module = self.modules["manage.edit_forms"]
        for kind, item_id, label in (("category", 1, "Category name"), ("subcategory", 7, "Subcategory name"),
                                     ("counterparty", 3, "Counterparty name"),
                                     ("subscription", 4, "Subscription name")):
            with self.subTest(kind=kind):
                module.render_edit_form(self.manage, self.management_data(), kind, item_id)
                self.ui.find("input", label=label)[-1].value = "   "
                self.ui.find("button", title="Save " + kind)[-1].handlers["click"]()
                self.connection.execute.assert_not_called()

    def test_review_counterparty_and_subscription_creation_save_and_reset(self):
        """Forward Review creation fields and clear only successfully saved drafts."""
        module = self.modules["review.creation_forms"]
        self.review.render_configuration = Mock()
        self.review.render_transactions = Mock()
        self.review.refresh_matching = Mock()
        self.review.form_values.update(counterparty_name="Market", counterparty_pattern="SHOP",
                                       subscription_name="Music", subscription_amount="-9.99")
        self.review.render_configuration = Mock()
        module.render_creation_forms(self.review)
        self.ui.find("button", title="Add counterparty")[-1].handlers["click"]()
        module._create_counterparty.assert_called_once_with(
            self.finance_path, "Market", None, None, "payment_message", "SHOP",
        )
        self.assertEqual(self.review.form_values["counterparty_name"], "")
        self.assertEqual(self.review.form_values["subscription_name"], "Music")
        self.ui.find("button", title="Add subscription")[-1].handlers["click"]()
        module._create_subscription.assert_called_once_with(
            self.finance_path, "Music", None, "monthly", -999, "EUR", None,
        )
        self.assertEqual(self.review.form_values["subscription_name"], "")
        self.actions.render_subscriptions.assert_called_once()

    def test_review_creation_error_retains_values(self):
        """Retain Review creation values when the creation service rejects them."""
        module = self.modules["review.creation_forms"]
        self.review.form_values.update(counterparty_name="Keep", subscription_name="Also keep")
        module._create_counterparty.side_effect = ValueError("Synthetic duplicate")
        module._create_subscription.side_effect = sqlite3.IntegrityError("Synthetic duplicate")
        module.render_creation_forms(self.review)
        for title in ("Add counterparty", "Add subscription"):
            self.ui.find("button", title=title)[-1].handlers["click"]()
        self.assertEqual(self.review.form_values["counterparty_name"], "Keep")
        self.assertEqual(self.review.form_values["subscription_name"], "Also keep")
        self.actions.render_subscriptions.assert_not_called()

    def test_review_empty_queue_and_stale_pinned_selection(self):
        """Clear a stale pinned item and display the reviewed message for an empty queue."""
        self.review.state.update(pinned_id="gone", offset=99)
        self.review.render_transactions()
        self.assertIsNone(self.review.state["pinned_id"])
        self.assertIsNone(self.review.state["active_id"])
        self.assertEqual(self.review.state["offset"], 0)
        self.assertTrue(self.ui.find("label", label="All transactions are reviewed"))

    def test_review_renders_pinned_completed_transaction_and_clamps_unpinned_offset(self):
        """Keep completed pinned items visible and clamp offsets after queue changes."""
        module = self.modules["review.page"]
        module._review_transactions.return_value = [self.transaction("pending"),
                                                    self.transaction("done", complete=True)]
        self.review.state.update(pinned_id="done", offset=10)
        render = Mock()
        with patch.dict(vars(module), {"render_transaction_card": render}):
            self.review.render_transactions()
            self.assertEqual(render.call_args.args[1]["id"], "done")
            self.review.state["pinned_id"] = None
            self.review.render_transactions()
            self.assertEqual(render.call_args.args[1]["id"], "pending")
        self.assertEqual(self.review.state["offset"], 0)

    def test_split_add_delete_and_toggle_preserve_review_state(self):
        """Expand new splits, collapse the final split, and toggle settings predictably."""
        self.review.refresh_after_edit = Mock()
        self.review.render_transactions = Mock()
        self.review.add_split("tx-1")
        self.assertIn("tx-1", self.review.state["expanded_splits"])
        self.modules["review.page"]._add_split.assert_called_once_with(self.finance_path, "tx-1")
        self.connection.execute.return_value.fetchone.return_value = (1,)
        self.review.delete_split("tx-1", 11)
        self.assertNotIn("tx-1", self.review.state["expanded_splits"])
        self.review.refresh_after_edit.assert_called_with("tx-1")
        self.review.toggle_split_settings("tx-1")
        self.assertIn("tx-1", self.review.state["expanded_splits"])
        self.review.toggle_split_settings("tx-1")
        self.assertNotIn("tx-1", self.review.state["expanded_splits"])

    def test_split_service_failures_do_not_change_review_state(self):
        """Report failed split changes without refreshing or altering expansion state."""
        module = self.modules["review.page"]
        self.review.refresh_after_edit = Mock()
        module._add_split.side_effect = ValueError("Cannot split one cent")
        self.review.add_split("tx-1")
        self.assertNotIn("tx-1", self.review.state["expanded_splits"])
        module._delete_split.side_effect = sqlite3.DatabaseError("Synthetic database failure")
        self.review.delete_split("tx-1", 11)
        self.review.refresh_after_edit.assert_not_called()
        self.ui.notify.assert_called_with("Synthetic database failure", type="warning")

    def test_subscription_decision_and_link_callbacks_keep_original_split(self):
        """Persist subscription answers and linked IDs for the control's original split."""
        module = self.modules["review.split_controls"]
        self.review.refresh_after_edit = Mock()
        split = self.transaction()["splits"][0]
        split.update(is_subscription=1, subscription_id=4)
        module.render_split_decisions(self.review, {4: "Music"}, split, "tx-1")
        self.ui.find("select", label="Subscription")[-1].handlers["value"](SimpleNamespace(value="no"))
        module._save_subscription_decision.assert_called_with(self.finance_path, 11, "no", None)
        self.ui.find("select", label="Linked subscription")[-1].handlers["value"](SimpleNamespace(value=5))
        module._save_subscription_decision.assert_called_with(self.finance_path, 11, "yes", 5)
        self.review.refresh_after_edit.assert_called_with("tx-1")

    def test_expanded_split_amount_note_and_exclusion_callbacks(self):
        """Save valid split amounts, trim notes, and refresh exclusion changes."""
        module = self.modules["review.split_controls"]
        self.review.refresh_after_edit = Mock()
        transaction = self.transaction()
        module.render_split_editor(self.review, transaction, transaction["splits"][0], transaction["splits"], {}, {})
        self.ui.find("number", label="Split amount")[-1].handlers["value"](SimpleNamespace(value=-2.34))
        module._save_split_amount.assert_called_once_with(self.finance_path, 11, -234)
        self.ui.find("input", label="Split note")[-1].handlers["value"](SimpleNamespace(value="  Note  "))
        module._save_split_note.assert_called_once_with(self.finance_path, 11, "Note")
        self.ui.find("checkbox", label="Exclude from spending")[-1].handlers["value"](SimpleNamespace(value=True))
        module._save_excluded.assert_called_once_with(self.finance_path, 11, True)
        self.review.refresh_after_edit.assert_called_once_with("tx-1")

    def test_split_amount_rejects_wrong_sign_blank_zero_and_fractional_cents(self):
        """Prevent invalid split amounts from reaching persistence."""
        module = self.modules["review.split_controls"]
        transaction = self.transaction()
        module.render_split_editor(self.review, transaction, transaction["splits"][0], transaction["splits"], {}, {})
        callback = self.ui.find("number", label="Split amount")[-1].handlers["value"]
        for value in (2.0, None, 0, -1.001):
            with self.subTest(value=value):
                callback(SimpleNamespace(value=value))
                module._save_split_amount.assert_not_called()

    def test_transaction_notes_counterparty_and_exclusion_in_both_layouts(self):
        """Capture IDs and trim notes in compact and expanded transaction controls."""
        module = self.modules["review.transaction_card"]
        self.review.refresh_matching = Mock()
        self.review.refresh_after_edit = Mock()
        for expanded in (False, True):
            with self.subTest(expanded=expanded):
                self.review.state["expanded_splits"] = {"tx-1"} if expanded else set()
                module.render_transaction_card(self.review, self.transaction(), {}, {}, {})
                self.ui.find("select", label="Counterparty")[-1].handlers["value"](SimpleNamespace(value=3))
                module._save_counterparty.assert_called_with(self.finance_path, "tx-1", 3)
                self.ui.find("textarea", label="Transaction note")[-1].handlers["value"](SimpleNamespace(value="  "))
                module._save_transaction_note.assert_called_with(self.finance_path, "tx-1", None)
        self.review.state["expanded_splits"] = set()
        module.render_transaction_card(self.review, self.transaction(), {}, {}, {})
        self.ui.find("checkbox", label="Exclude from spending")[-1].handlers["value"](SimpleNamespace(value=True))
        module._save_excluded.assert_called_once_with(self.finance_path, 11, True)

    def test_rules_can_be_added_deleted_and_fail_without_refresh(self):
        """Refresh after successful rule changes and retain the editor after failures."""
        module = self.modules["manage.rule_controls"]
        self.manage.render_management = Mock()
        self.manage.render_management_rules("counterparties_match_rules", "counterparty_id", 3)
        self.ui.find("input", label="New contains pattern")[-1].value = "SHOP"
        add = self.ui.find("button", title="Add matching rule")[-1]
        add.handlers["click"]()
        module._add_rule.assert_called_once_with(
            self.finance_path, "counterparties_match_rules", "counterparty_id", 3, "payment_message", "SHOP",
        )
        self.manage.remove_rule("counterparties_match_rules", 9)
        module._delete_rule.assert_called_once_with(self.finance_path, "counterparties_match_rules", 9)
        self.actions.refresh_matching.reset_mock()
        module._add_rule.side_effect = ValueError("Duplicate rule")
        add.handlers["click"]()
        self.actions.refresh_matching.assert_not_called()
        self.ui.notify.assert_called_with("Duplicate rule", type="warning")

    def test_subscription_status_failure_reports_error_without_refresh(self):
        """Report status write failures and leave subscription tables in place."""
        module = self.modules["subscriptions.page"]
        from tests.support.ui import Element
        page = module.SubscriptionsPage(self.transaction_path, self.finance_path, self.actions, Element("column"))
        page.render_subscriptions()
        page.render_subscriptions = Mock()
        self.connection.execute.side_effect = sqlite3.DatabaseError("Synthetic write failure")
        self.ui.find("table")[0].handlers["active_change"](SimpleNamespace(args=[4, False]))
        page.render_subscriptions.assert_not_called()
        self.actions.render_management.assert_not_called()
        self.ui.notify.assert_called_with("Could not update subscription status: Synthetic write failure",
                                          type="negative")
