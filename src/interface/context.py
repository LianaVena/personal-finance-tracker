"""Shared UI constants, state types, and refresh contracts."""

from __future__ import annotations

from typing import Protocol, TypedDict

PAGE_SIZE = 1


class ReviewState(TypedDict):
    """Hold the current position and split state for transaction review."""

    offset: int
    pinned_id: str | None
    active_id: str | None
    expanded_splits: set[str]


RULE_FIELDS = {
    "counterparty_name": "Bank counterparty name",
    "counterparty_iban": "Counterparty IBAN",
    "payer_reference": "Payer reference",
    "payment_message": "Payment message",
    "description": "Description",
}


class UiActions(Protocol):
    """Describe the cross-page operations supplied by the application."""

    def refresh_matching(self, advance_if_complete: bool = False) -> None:
        """Reapply matching rules while retaining the review position.

        Args:
            advance_if_complete: Whether a newly completed transaction may leave review.
        """
        ...

    def refresh_after_edit(self, transaction_id: str) -> None:
        """Refresh review while keeping an edited transaction visible.

        Args:
            transaction_id: Stable ID of the edited transaction.
        """
        ...

    def render_transactions(self) -> None:
        """Redraw the current transaction review controls."""
        ...

    def render_configuration(self) -> None:
        """Redraw the Review page's entity creation forms."""
        ...

    def render_management(self) -> None:
        """Redraw management tables and forms."""
        ...

    def render_subscriptions(self) -> None:
        """Redraw subscription totals and tables."""
        ...
