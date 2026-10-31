"""Independent page state, matching, and review navigation."""

from __future__ import annotations

from unittest.mock import Mock

from tests.support.pages import InterfacePageTestCase
from tests.support.ui import Element


class PageStateTests(InterfacePageTestCase):
    """Independent page state, matching, and review navigation."""

    def test_construction_creates_independent_state_without_queries(self):
        """Keep page drafts and navigation state independent without querying data."""
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
        """Release a completed review item only when advancing is requested."""
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
        """Keep edited transactions visible until the user explicitly saves them."""
        module = self.modules["review.page"]
        module._review_transactions.return_value = [self.transaction(complete=True)]
        self.review.render_transactions = Mock()
        self.review.refresh_after_edit("tx-1")
        self.assertEqual(self.review.state["pinned_id"], "tx-1")
        self.review.save_transaction("tx-1")
        self.assertIsNone(self.review.state["pinned_id"])
        self.assertEqual(self.review.render_transactions.call_count, 2)

    def test_pinned_navigation_selects_neighbor_and_respects_boundaries(self):
        """Navigate around a pinned item without crossing review queue boundaries."""
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
