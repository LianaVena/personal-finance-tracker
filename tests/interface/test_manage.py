"""Management drafts, selection, pagination, and captured entity IDs."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from tests.support.pages import InterfacePageTestCase
from tests.support.ui import Element


class ManagePageTests(InterfacePageTestCase):
    """Management drafts, selection, pagination, and captured entity IDs."""

    def test_management_drafts_survive_selection_and_binding(self):
        """Retain bound draft edits when management selections change."""
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
        """Clamp counterparty navigation to the available pages."""
        self.modules["manage.page"]._counterparties.return_value = [{"id": i} for i in range(51)]
        self.manage.render_management = Mock()
        for direction, expected in ((1, 2), (1, 2), (-1, 1), (-1, 1)):
            self.manage.change_counterparty_page(direction)
            self.assertEqual(self.manage.counterparty_page["value"], expected)

    def test_management_selection_updates_editors_without_rebuilding_tables_or_querying(self):
        """Refresh selection forms while preserving tables and avoiding new queries."""
        self.modules["manage.page"]._categories.return_value = {1: "Food", 2: "Travel"}
        self.manage.render_management()
        tables = self.ui.find("table")
        self.modules["manage.page"].connect_database.reset_mock()
        self.manage.select_management_item("category", {"id": 2})
        self.assertEqual(self.ui.find("table"), tables)
        self.assertEqual(self.ui.find("input", label="Category name")[-1].value, "Travel")
        self.assertEqual(self.manage.selection["category"], 2)
        self.manage.select_management_item("category", {"id": 2})
        self.assertIsNone(self.manage.selection["category"])
        self.assertEqual(self.ui.find("input", label="Category name")[-1].value, "")
        self.assertEqual(self.ui.find("table"), tables)
        self.modules["manage.page"].connect_database.assert_not_called()

    def test_rule_callbacks_keep_their_own_rule_and_controls(self):
        """Save the rule and input values captured by each rule editor."""
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

    def test_manage_create_and_edit_forms_capture_their_entity_ids(self):
        """Apply management form callbacks to the entity they originally displayed."""
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

    def test_category_create_trims_persists_notifies_and_refreshes(self):
        """Exercise the category create callback's successful save behavior."""
        data = self.modules["manage.models"].ManagementData(
            {1: "Food"}, {None: "Unassigned"}, [], [], [], {}, {},
        )
        self.manage.render_management = Mock()
        self.modules["manage.create_forms"].render_create_form(self.manage, data, "category")
        self.ui.find("input", label="Category name")[-1].value = "  Dining  "
        self.ui.find("button", title="Create category")[-1].handlers["click"]()

        self.connection.execute.assert_called_once_with(
            "INSERT INTO categories(name) VALUES (?)", ("Dining",),
        )
        self.ui.notify.assert_called_once_with("Category created", type="positive")
        self.manage.render_management.assert_called_once()
        self.actions.render_configuration.assert_called_once()
        self.assertNotIn(("category", None), self.manage.drafts)
