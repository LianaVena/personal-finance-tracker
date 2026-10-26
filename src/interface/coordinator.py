"""Application-level page wiring and redraw delegation."""

from __future__ import annotations

from pathlib import Path

from nicegui import ui

from .manage.page import ManagePage
from .review.page import ReviewPage
from .subscriptions.page import SubscriptionsPage


class UiCoordinator:
    """Connect page instances without shared global UI state."""

    def __init__(self, transaction_db_path: Path, finance_db_path: Path,
                 transaction_content: ui.column, creation_content: ui.column,
                 management_content: ui.column, subscriptions_content: ui.column) -> None:
        self.review = ReviewPage(transaction_db_path, finance_db_path, self,
                                 transaction_content, creation_content)
        self.manage = ManagePage(transaction_db_path, finance_db_path, self, management_content)
        self.subscriptions = SubscriptionsPage(transaction_db_path, finance_db_path, self, subscriptions_content)

    def refresh_matching(self, advance_if_complete: bool = False) -> None:
        """Reapply matching while preserving the review position."""
        self.review.refresh_matching(advance_if_complete)

    def refresh_after_edit(self, transaction_id: str) -> None:
        """Keep the edited transaction visible."""
        self.review.refresh_after_edit(transaction_id)

    def render_transactions(self) -> None:
        """Redraw the current review transaction."""
        self.review.render_transactions()

    def render_configuration(self) -> None:
        """Redraw Review creation forms."""
        self.review.render_configuration()

    def render_management(self) -> None:
        """Redraw Manage tables and forms."""
        self.manage.render_management()

    def render_subscriptions(self) -> None:
        """Redraw subscription totals and tables."""
        self.subscriptions.render_subscriptions()

    def render_initial(self) -> None:
        """Render all pages in the established startup order."""
        self.render_transactions()
        self.render_configuration()
        self.render_management()
        self.render_subscriptions()
