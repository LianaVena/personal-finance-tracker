"""Review form state and callbacks retain the correct transaction IDs."""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

from tests.support.pages import InterfacePageTestCase


class ReviewPageTests(InterfacePageTestCase):
    """Review form state and callbacks retain the correct transaction IDs."""

    def test_compact_category_callback_keeps_original_split_id(self):
        """Keep compact category callbacks attached to their original split."""
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
        """Keep expanded split callbacks attached to their original transaction."""
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

    def test_creation_form_keeps_values_and_clears_only_successful_fields(self):
        """Clear successfully saved creation fields while retaining other drafts."""
        self.review.form_values.update(category_name="New category", counterparty_name="Keep")
        self.review.render_configuration = Mock()
        type(self.review).render_configuration(self.review)
        self.assertEqual(self.ui.find("input", label="Category name")[-1].value, "New category")
        self.ui.find("button", title="Add category")[-1].handlers["click"]()
        self.connection.execute.assert_called_once_with("INSERT INTO categories(name) VALUES (?)", ("New category",))
        self.assertEqual(self.review.form_values["category_name"], "")
        self.assertEqual(self.review.form_values["counterparty_name"], "Keep")
        self.review.render_configuration.assert_called_once()
        self.actions.render_management.assert_called_once()

    def test_write_error_does_not_clear_creation_draft(self):
        """Retain the creation draft when a database write fails."""
        self.review.form_values["category_name"] = "Keep on failure"
        self.connection.execute.side_effect = sqlite3.IntegrityError("Duplicate")
        self.modules["review.creation_forms"].render_creation_forms(self.review)
        self.ui.find("button", title="Add category")[-1].handlers["click"]()
        self.assertEqual(self.review.form_values["category_name"], "Keep on failure")
        self.actions.render_management.assert_not_called()
        self.ui.notify.assert_called_with("A category with that name already exists", type="warning")
