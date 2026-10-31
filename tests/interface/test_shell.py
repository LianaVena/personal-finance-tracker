"""Application page wiring, tabs, and safe exit behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

from tests.support.pages import InterfacePageTestCase
from tests.support.ui import Element


class ApplicationShellTests(InterfacePageTestCase):
    """Application page wiring, tabs, and safe exit behavior."""

    def test_coordinator_constructs_all_pages_before_rendering_in_original_order(self):
        """Construct every page before rendering and preserve refresh delegation."""
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
            coordinator.refresh_after_edit("tx-1")
            review_type.return_value.refresh_after_edit.assert_called_once_with("tx-1")

    def test_shell_preserves_tabs_and_exit_success(self):
        """Retain application tabs and shut down after successful integrity checks."""
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
        """Keep the app running and restore the exit control after failed checks."""
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
