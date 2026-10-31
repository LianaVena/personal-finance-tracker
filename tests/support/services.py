"""In-memory finance service fixtures and synthetic payment builders."""

from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src import categorization
from src.interface.manage import edits, tables
from src.interface.review import create, transactions
from src.interface.subscriptions import queries


class MemoryServiceTestCase(unittest.TestCase):
    """Provide synthetic payments and finance services backed by in-memory SQLite."""

    def setUp(self):
        """Create two in-memory schemas and patch services to use them exclusively."""
        self.finance = sqlite3.connect(":memory:")
        self.payments = sqlite3.connect(":memory:")
        self.addCleanup(self.finance.close)
        self.addCleanup(self.payments.close)
        sql_root = Path(__file__).resolve().parents[2] / "src" / "sql"
        self.finance.executescript((sql_root / "finance.sql").read_text(encoding="utf-8"))
        self.payments.executescript((sql_root / "transactions.sql").read_text(encoding="utf-8"))
        self.finance_path = Path("synthetic-finance")
        self.payment_path = Path("synthetic-payments")
        self.finance.execute("INSERT INTO categories(id, name) VALUES (1, 'Food')")
        self.finance.execute(
            "INSERT INTO colors(id, row_hex, pie_hex, name) "
            "VALUES (1, '#00FF00', '#00AA00', 'Service Green')",
        )
        self.finance.execute(
            "INSERT INTO subcategories(id, category_id, name, color_id) VALUES (1, 1, 'Meals', 1)",
        )
        self.finance.commit()
        self.connections = {}
        for path, connection in ((self.finance_path, self.finance), (self.payment_path, self.payments)):
            wrapper = MagicMock(wraps=connection)
            wrapper.__enter__.return_value = connection
            wrapper.__exit__.side_effect = connection.__exit__
            wrapper.close.return_value = None
            self.connections[path] = wrapper
        for module in (categorization, edits, tables, create, transactions, queries):
            self.enterContext(patch.dict(vars(module), {"connect_database": self.connections.__getitem__}))

    def add_payment(self, number: int, amount: int = -500, booking_date: str = "2026-01-01",
                    message: str = "SHOP", with_split: bool = True) -> str:
        """Insert a synthetic payment with metadata and an optional split.

        Args:
            number: Distinct integer used to generate a 64-character identifier.
            amount: Signed payment amount in minor units.
            booking_date: Booking date used by subscription matching.
            message: Synthetic payment message used by text rules.
            with_split: Whether to create the initial nonzero split.

        Returns:
            Identifier of the inserted payment.
        """
        transaction_id = f"{number:064x}"
        self.payments.execute(
            "INSERT INTO transactions(id, source_bank, booking_date, amount, currency, payment_message) "
            "VALUES (?, 'TB', ?, ?, 'EUR', ?)", (transaction_id, booking_date, amount, message),
        )
        self.payments.commit()
        self.finance.execute("INSERT INTO transaction_metadata(transaction_id) VALUES (?)", (transaction_id,))
        if with_split and amount:
            self.finance.execute("INSERT INTO transaction_splits(transaction_id, amount) VALUES (?, ?)",
                                 (transaction_id, amount))
        self.finance.commit()
        return transaction_id

    def split_rows(self, transaction_id: str) -> list[tuple]:
        """Read split IDs and amounts for a synthetic payment.

        Args:
            transaction_id: Payment whose splits are requested.

        Returns:
            Split ID and amount pairs in ID order.
        """
        return self.finance.execute("SELECT id, amount FROM transaction_splits WHERE transaction_id = ? ORDER BY id",
                                    (transaction_id,)).fetchall()
