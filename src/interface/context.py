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

    def refresh_matching(self, advance_if_complete: bool = False) -> None: ...

    def refresh_after_edit(self, transaction_id: str) -> None: ...

    def render_transactions(self) -> None: ...

    def render_configuration(self) -> None: ...

    def render_management(self) -> None: ...

    def render_subscriptions(self) -> None: ...
