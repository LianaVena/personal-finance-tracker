"""Inline color controls, named palettes, draft persistence, and stored color IDs."""

from __future__ import annotations

from unittest.mock import Mock

from src.subcategory_colors import DEFAULT_SUBCATEGORY_COLOR
from tests.support.pages import InterfacePageTestCase, TEST_COLORS


class SubcategoryColorControlTests(InterfacePageTestCase):
    """Inline color controls, named palettes, draft persistence, and stored color IDs."""

    def test_manage_subcategory_creation_saves_id_and_offers_database_colors(self):
        """Persist an offered color ID when creating a management subcategory."""
        data = self.modules["manage.models"].ManagementData(
            {1: "Food"}, {None: "Unassigned"}, [], [], [], {}, {}, TEST_COLORS,
        )
        self.manage.render_management = Mock()
        self.modules["manage.create_forms"].render_create_form(self.manage, data, "subcategory")
        self.assertEqual(self.ui.find("select", label="Color"), [])
        self.assertEqual(self.manage.drafts[("subcategory", None)]["color"], DEFAULT_SUBCATEGORY_COLOR)
        self.ui.find("select", label="Parent category")[-1].value = 1
        self.ui.find("input", label="Subcategory name")[-1].value = "Meals"
        self.ui.find("button", title="Test Red")[-1].handlers["click"]()
        self.ui.find("button", title="Create subcategory")[-1].handlers["click"]()
        self.connection.execute.assert_called_once_with(
            "INSERT INTO subcategories(category_id, name, color_id) VALUES (?, ?, ?)", (1, "Meals", 31),
        )
        self.assertNotIn(("subcategory", None), self.manage.drafts)

    def test_manage_subcategory_edit_loads_saves_and_retains_color(self):
        """Load, change, and clear saved colors while refreshing subscription rows."""
        data = self.modules["manage.models"].ManagementData(
            {1: "Food"}, {None: "Unassigned"}, [], [],
            [(7, 1, "Meals", "Food", 32, "#AA0000", "Test Red")], {}, {}, TEST_COLORS,
        )
        self.manage.render_management = Mock()
        self.modules["manage.edit_forms"].render_edit_form(self.manage, data, "subcategory", 7)
        self.assertTrue(any(button.text == "Test Green" for button in self.ui.find("button")))
        self.ui.find("button", title="Test Blue")[-1].handlers["click"]()
        self.ui.find("button", title="Save subcategory")[-1].handlers["click"]()
        self.connection.execute.assert_called_once_with(
            "UPDATE subcategories SET category_id = ?, name = ?, color_id = ? WHERE id = ?",
            (1, "Meals", 33, 7),
        )
        self.assertEqual(self.manage.drafts[("subcategory", 7)]["color"], 33)
        self.actions.render_subscriptions.assert_called_once()
        self.connection.execute.reset_mock()
        self.ui.find("button", title="No color")[-1].handlers["click"]()
        self.ui.find("button", title="Save subcategory")[-1].handlers["click"]()
        self.connection.execute.assert_called_once_with(
            "UPDATE subcategories SET category_id = ?, name = ?, color_id = ? WHERE id = ?", (1, "Meals", None, 7),
        )
        self.assertIsNone(self.manage.drafts[("subcategory", 7)]["color"])
        self.assertEqual(self.actions.render_subscriptions.call_count, 2)

    def test_invalid_subcategory_color_preserves_draft_without_writing(self):
        """Reject unsupported colors without changing the database or losing the draft."""
        data = self.modules["manage.models"].ManagementData(
            {1: "Food"}, {None: "Unassigned"}, [], [], [], {}, {}, TEST_COLORS,
        )
        self.manage.management_draft("subcategory", None, {"parent": 1, "name": "Meals", "color": "#FFFFFF"})
        self.modules["manage.create_forms"].render_create_form(self.manage, data, "subcategory")
        self.ui.find("select", label="Parent category")[-1].value = 1
        self.ui.find("input", label="Subcategory name")[-1].value = "Meals"
        self.ui.find("button", title="Create subcategory")[-1].handlers["click"]()
        self.connection.execute.assert_not_called()
        self.assertEqual(self.manage.drafts[("subcategory", None)]["color"], "#FFFFFF")
        self.ui.notify.assert_called_with("Choose a subcategory color from the available colors", type="warning")

    def test_review_subcategory_creation_saves_color_and_resets_to_no_color(self):
        """Save Review subcategory colors and reset successful drafts to no color."""
        self.review.form_values.update(subcategory_parent=1, subcategory_name="Meals", subcategory_color=32)
        self.review.render_configuration = Mock()
        self.review.render_transactions = Mock()
        self.modules["review.creation_forms"].render_creation_forms(self.review)
        self.assertTrue(any(button.text == "Test Green" for button in self.ui.find("button")))
        self.ui.find("button", title="Test Blue")[-1].handlers["click"]()
        self.ui.find("button", title="Add subcategory")[-1].handlers["click"]()
        self.connection.execute.assert_called_once_with(
            "INSERT INTO subcategories(category_id, name, color_id) VALUES (?, ?, ?)", (1, "Meals", 33),
        )
        self.assertEqual(self.review.form_values["subcategory_color"], DEFAULT_SUBCATEGORY_COLOR)
        self.actions.render_management.assert_called_once()

    def test_palette_has_name_only_tooltips_and_no_color_in_first_cell(self):
        """Show database colors after no color and keep each picker independent."""
        callback = Mock()
        grid = self.modules["color_grid"].SubcategoryColorGrid(DEFAULT_SUBCATEGORY_COLOR, callback, TEST_COLORS)
        swatches = [button for button in self.ui.find("button") if button.title is not None]
        self.assertEqual([button.title for button in swatches],
                         ["No color", *(name for _, _, _, name in TEST_COLORS)])
        self.assertEqual(len(swatches), len(TEST_COLORS) + 1)
        palette = swatches[0].parent
        self.assertIsNotNone(palette)
        assert palette is not None
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", palette.style_history[0])
        self.assertIn("grid-template-rows: repeat(3, minmax(0, 1fr))", palette.style_history[0])
        self.assertIn("width: 240px", palette.style_history[0])
        self.assertTrue(all(button.parent is palette for button in swatches))
        other = self.modules["color_grid"].SubcategoryColorGrid(DEFAULT_SUBCATEGORY_COLOR, Mock(), TEST_COLORS)
        red = self.ui.find("button", title="Test Red")[0]
        red.handlers["click"]()
        self.assertEqual(grid.value, 31)
        self.assertEqual(grid.trigger.text, "Test Red")
        self.assertEqual(grid.tooltip.text, "Test Red")
        self.assertIn("background-color: #AA0000 !important", red.style_history[-1])
        self.assertEqual(other.value, DEFAULT_SUBCATEGORY_COLOR)
        self.assertIn("aria-pressed=true", red.props_history[-1])
        callback.assert_called_once_with(31)

    def test_color_grid_opens_on_click_and_closes_after_selection(self):
        """Toggle the palette on click and close it after picking or clearing a color."""
        callback = Mock()
        grid = self.modules["color_grid"].SubcategoryColorGrid(DEFAULT_SUBCATEGORY_COLOR, callback, TEST_COLORS)
        menu = self.ui.find("menu")[-1]
        trigger = self.ui.find("button")[0]
        self.assertFalse(menu.value)
        trigger.handlers["click"]()
        self.assertTrue(menu.value)
        self.assertIn("aria-expanded=true", trigger.props_history[-1])
        self.ui.find("button", title="Test Red")[-1].handlers["click"]()
        self.assertFalse(menu.value)
        self.assertIn("aria-expanded=false", trigger.props_history[-1])
        self.assertEqual(grid.value, 31)
        self.assertEqual(grid.trigger.text, "Test Red")
        callback.assert_called_once_with(31)
        trigger.handlers["click"]()
        self.assertTrue(menu.value)
        trigger.handlers["click"]()
        self.assertFalse(menu.value)
        self.assertEqual(grid.value, 31)
        trigger.handlers["click"]()
        self.ui.find("button", title="No color")[-1].handlers["click"]()
        self.assertFalse(menu.value)
        self.assertIsNone(grid.value)
        self.assertEqual(grid.trigger.text, "No color")
        self.assertEqual(callback.call_args.args, (None,))

    def test_review_subcategory_can_be_saved_without_a_color(self):
        """Persist a null color when the Review form has no selected color."""
        self.review.form_values.update(subcategory_parent=1, subcategory_name="Meals")
        self.review.render_configuration = Mock()
        self.review.render_transactions = Mock()
        self.modules["review.creation_forms"].render_creation_forms(self.review)
        self.ui.find("button", title="Add subcategory")[-1].handlers["click"]()
        self.connection.execute.assert_called_once_with(
            "INSERT INTO subcategories(category_id, name, color_id) VALUES (?, ?, ?)", (1, "Meals", None),
        )

    def test_subcategory_color_controls_share_parent_name_and_action_row(self):
        """Keep the picker inline with parent, name, and action in every subcategory form."""
        data = self.modules["manage.models"].ManagementData(
            {1: "Food"}, {None: "Unassigned"}, [], [],
            [(7, 1, "Meals", "Food", None, None, None)], {}, {}, TEST_COLORS,
        )
        renderers = (
            (lambda: self.modules["manage.create_forms"].render_create_form(self.manage, data, "subcategory"),
             "Parent category", "Create subcategory"),
            (lambda: self.modules["manage.edit_forms"].render_edit_form(self.manage, data, "subcategory", 7),
             "Category", "Save subcategory"),
            (lambda: self.modules["review.creation_forms"].render_creation_forms(self.review),
             "Parent category", "Add subcategory"),
        )
        for render, parent_label, action_title in renderers:
            with self.subTest(form=action_title):
                render()
                parent = self.ui.find("select", label=parent_label)[-1]
                name = self.ui.find("input", label="Subcategory name")[-1]
                action = self.ui.find("button", title=action_title)[-1]
                trigger = next(button for button in reversed(self.ui.find("button"))
                               if button.kwargs.get("icon") == "palette")
                self.assertIsNotNone(parent.parent)
                self.assertIs(name.parent, parent.parent)
                self.assertIs(action.parent, parent.parent)
                self.assertIsNotNone(trigger.parent)
                assert trigger.parent is not None
                self.assertIs(trigger.parent.parent, parent.parent)

    def test_manage_subcategory_table_contains_stored_color_and_swatch(self):
        """Include saved color values and swatch templates in the management table."""
        self.modules["manage.page"]._categories.return_value = {1: "Food"}
        self.connection.execute.return_value.fetchall.return_value = [
            (7, 1, "Meals", "Food", 32, "#AA0000", "Test Red"),
        ]
        self.manage.render_management()
        tables = [table for table in self.ui.find("table") if "body-cell-color" in table.slots]
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0].kwargs["rows"][0]["color"], "#AA0000")
        self.assertIn("backgroundColor: props.value", tables[0].slots["body-cell-color"])
