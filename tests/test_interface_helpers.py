"""Tests for interface formatting, CRUD helpers, and review persistence."""

import hashlib
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from src.database import connect_database, create_finance_tables, create_transactions_table
from src.interface.common import currency_options, currency_symbol, format_money, money_to_minor_units
from src.interface.manage.edits import add_rule, delete_rule, save_counterparty_defaults, update_rule
from src.interface.manage.tables import categories, counterparties, rules, subcategories, subscriptions
from src.interface.review.create import create_counterparty, create_subscription
from src.interface.review.transactions import (
    add_split, delete_split, format_transaction_field, review_transactions,
    save_counterparty, save_excluded, save_split_amount, save_split_note,
    save_subcategory, save_subscription_decision, save_transaction_note,
)
from src.interface.subscriptions import subscription_categories


class InterfaceDatabaseTestCase(unittest.TestCase):
    """Provide isolated finance and transaction databases with synthetic records."""

    def setUp(self):
        """Create empty v2 databases in a temporary directory."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.finance_path = self.root / "finance.db"
        self.transactions_path = self.root / "transactions.db"
        create_finance_tables(self.finance_path)
        create_transactions_table(self.transactions_path)
        with closing(connect_database(self.finance_path)) as connection, connection:
            category_id = connection.execute(
                "INSERT INTO categories(name) VALUES ('Food')"
            ).lastrowid
            assert category_id is not None, "Category insert did not return an ID"
            self.category_id = category_id
            subcategory_id = connection.execute(
                "INSERT INTO subcategories(category_id, name) VALUES (?, 'Restaurants')",
                (self.category_id,),
            ).lastrowid
            assert subcategory_id is not None, "Subcategory insert did not return an ID"
            self.subcategory_id = subcategory_id

    def add_transaction(self, sequence, *, booking_date="2026-10-25", amount=-1250,
                        payment_message="Synthetic payment"):
        """Insert a dummy transaction and return its stable test hash.

        Args:
            sequence: Unique test value used to derive the transaction ID.
            booking_date: ISO-formatted booking date.
            amount: Signed amount in integer minor units.
            payment_message: Dummy payment description.

        Returns:
            Stable SHA-256 ID of the inserted synthetic transaction.
        """
        transaction_id = hashlib.sha256(f"dummy-{sequence}".encode()).hexdigest()
        with closing(connect_database(self.transactions_path)) as connection, connection:
            connection.execute(
                "INSERT INTO transactions(id, source_bank, booking_date, value_date, amount, "
                "currency, transaction_type, payment_message) "
                "VALUES (?, 'TB', ?, ?, ?, 'EUR', 'DEBIT', ?)",
                (transaction_id, booking_date, amount, booking_date, payment_message),
            )
        return transaction_id

    def add_metadata_and_split(self, transaction_id, amount=-1250) -> int:
        """Create initial review metadata and one synthetic transaction split.

        Args:
            transaction_id: Stable hash ID of the parent transaction.
            amount: Signed amount in integer minor units.

        Returns:
            ID of the created split.
        """
        with closing(connect_database(self.finance_path)) as connection, connection:
            connection.execute("INSERT INTO transaction_metadata(transaction_id) VALUES (?)", (transaction_id,))
            split_id = connection.execute(
                "INSERT INTO transaction_splits(transaction_id, amount) VALUES (?, ?)",
                (transaction_id, amount),
            ).lastrowid
            assert split_id is not None, "Split insert did not return an ID"
            return split_id


class InterfaceFormattingTests(unittest.TestCase):
    """Check money display and parsing without touching application databases."""

    def test_currency_helpers_handle_known_unknown_and_empty_codes(self):
        """Known currencies have symbols and unknown currencies remain visible."""
        self.assertTrue(currency_symbol("EUR"))
        self.assertEqual(currency_symbol("xyz"), "XYZ")
        self.assertEqual(currency_symbol(None), "")
        self.assertEqual(currency_options("xyz")["XYZ"], "XYZ")

    def test_format_money_preserves_sign_and_supports_absolute_display(self):
        """Money formatting keeps cents and can suppress a negative sign."""
        formatted = format_money(-1234, "EUR")
        self.assertIn("12.34", formatted)
        self.assertTrue(formatted.startswith("-"))
        self.assertNotIn("-", format_money(-1234, "EUR", absolute=True))
        self.assertEqual(format_money(500, None), "5.00")

    def test_money_parser_accepts_cents_and_rejects_invalid_values(self):
        """The parser returns integer minor units and rejects zero or fractions of cents."""
        self.assertIsNone(money_to_minor_units("  "))
        self.assertEqual(money_to_minor_units("-12.34"), -1234)
        for invalid in ("bad", "NaN", "Infinity", "0", "1.001"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                money_to_minor_units(invalid)


class InterfacePersistenceTests(InterfaceDatabaseTestCase):
    """Exercise interface service functions against disposable SQLite databases."""

    def test_create_counterparty_with_optional_rule_and_defaults(self):
        """Counterparties can be created alone or with a validated initial rule."""
        plain_id = create_counterparty(self.finance_path, "  Local Shop ", None, None,
                                       "payment_message", "")
        matched_id = create_counterparty(self.finance_path, "Cafe", self.subcategory_id, 0,
                                         "description", "coffee")
        self.assertEqual([item["name"] for item in counterparties(self.finance_path)],
                         ["Cafe", "Local Shop"])
        self.assertEqual(categories(self.finance_path), {self.category_id: "Food"})
        self.assertEqual(subcategories(self.finance_path)[self.subcategory_id], "Food / Restaurants")
        self.assertEqual(rules(self.finance_path, "counterparties_match_rules", "counterparty_id", matched_id)[0][2],
                         "coffee")
        self.assertEqual(rules(self.finance_path, "counterparties_match_rules", "counterparty_id", plain_id), [])
        with self.assertRaises(ValueError):
            create_counterparty(self.finance_path, "Another", None, None, "unknown", "x")

    def test_create_subscription_validates_amount_currency_pair_and_rule(self):
        """Subscription creation stores its fields and optional match evidence atomically."""
        counterparty_id = create_counterparty(self.finance_path, "Stream", None, 1, "", "")
        subscription_id = create_subscription(
            self.finance_path, " Stream Plus ", counterparty_id, "monthly", -999, "EUR",
            ("payment_message", "STREAM PLUS"),
        )
        row = next(item for item in subscriptions(self.finance_path) if item["id"] == subscription_id)
        self.assertEqual((row["name"], row["expected_amount"], row["currency"]),
                         ("Stream Plus", -999, "EUR"))
        self.assertEqual(rules(self.finance_path, "subscription_match_rules", "subscription_id", subscription_id)[0][2],
                         "STREAM PLUS")
        with self.assertRaises(ValueError):
            create_subscription(self.finance_path, "Broken", None, "monthly", -100, None, None)

    def test_manage_rules_validate_update_delete_and_defaults(self):
        """Manage operations persist defaults and enforce scoped casefold uniqueness."""
        owner = create_counterparty(self.finance_path, "Shop", None, None, "", "")
        add_rule(self.finance_path, "counterparties_match_rules", "counterparty_id", owner,
                 "payment_message", "Café")
        with self.assertRaises(ValueError):
            add_rule(self.finance_path, "counterparties_match_rules", "counterparty_id", owner,
                     "payment_message", "CAFÉ")
        rule_id = rules(self.finance_path, "counterparties_match_rules", "counterparty_id", owner)[0][0]
        update_rule(self.finance_path, "counterparties_match_rules", "counterparty_id", owner,
                    rule_id, "description", "market")
        self.assertEqual(rules(self.finance_path, "counterparties_match_rules", "counterparty_id", owner)[0][1:],
                         ("description", "market"))
        save_counterparty_defaults(self.finance_path, owner, self.subcategory_id, 0)
        self.assertEqual(counterparties(self.finance_path)[0]["default_subcategory_id"], self.subcategory_id)
        delete_rule(self.finance_path, "counterparties_match_rules", rule_id)
        self.assertEqual(rules(self.finance_path, "counterparties_match_rules", "counterparty_id", owner), [])
        with self.assertRaises(ValueError):
            add_rule(self.finance_path, "transactions", "counterparty_id", owner, "description", "bad")

    def test_review_queue_lists_newest_and_reports_incomplete_state(self):
        """Review joins synthetic rows in newest-first order and reports missing decisions."""
        older = self.add_transaction(1, booking_date="2026-10-20")
        newer = self.add_transaction(2, booking_date="2026-10-24")
        self.add_metadata_and_split(older)
        transactions = review_transactions(self.transactions_path, self.finance_path)
        self.assertEqual([item["id"] for item in transactions], [newer, older])
        self.assertIn("Finance metadata is missing", transactions[0]["review_reasons"])
        self.assertIn("A split needs a subcategory", transactions[1]["review_reasons"])
        self.assertIn("A split needs a subscription answer", transactions[1]["review_reasons"])

    def test_review_save_operations_and_split_lifecycle(self):
        """Save helpers persist decisions and split add/delete preserve signed totals."""
        transaction_id = self.add_transaction(3, amount=-500)
        split_id = self.add_metadata_and_split(transaction_id, -500)
        counterparty_id = create_counterparty(self.finance_path, "Shop", None, None, "", "")
        save_counterparty(self.finance_path, transaction_id, counterparty_id)
        save_transaction_note(self.finance_path, transaction_id, "Synthetic note")
        save_subcategory(self.finance_path, split_id, self.subcategory_id)
        save_subscription_decision(self.finance_path, split_id, "no")
        save_split_note(self.finance_path, split_id, "Split note")
        save_excluded(self.finance_path, split_id, True)
        add_split(self.finance_path, transaction_id)
        with closing(connect_database(self.finance_path)) as connection:
            rows = connection.execute(
                "SELECT amount, subcategory_id, is_subscription, subscription_is_manual, excluded "
                "FROM transaction_splits WHERE transaction_id = ? ORDER BY id", (transaction_id,),
            ).fetchall()
            self.assertEqual(sum(row[0] for row in rows), -500)
            self.assertEqual(rows[0], (-499, self.subcategory_id, 0, 1, 1))
            added_id = connection.execute(
                "SELECT id FROM transaction_splits WHERE transaction_id = ? ORDER BY id DESC LIMIT 1",
                (transaction_id,),
            ).fetchone()[0]
        save_split_amount(self.finance_path, added_id, -1)
        with self.assertRaises(ValueError):
            save_split_amount(self.finance_path, added_id, 0)
        delete_split(self.finance_path, transaction_id, added_id)
        with closing(connect_database(self.finance_path)) as connection:
            self.assertEqual(connection.execute(
                "SELECT amount, note FROM transaction_splits WHERE id = ?", (split_id,),
            ).fetchone(), (-500, "Split note"))
            self.assertEqual(connection.execute(
                "SELECT note, counterparty_id, counterparty_is_manual FROM transaction_metadata "
                "WHERE transaction_id = ?", (transaction_id,),
            ).fetchone(), ("Synthetic note", counterparty_id, 1))
        with self.assertRaises(ValueError):
            save_subscription_decision(self.finance_path, split_id, "maybe")
        with self.assertRaises(ValueError):
            delete_split(self.finance_path, transaction_id, split_id)

    def test_field_formatting_and_latest_subscription_category(self):
        """Display helpers format transaction labels and derive category from latest payment."""
        transaction = {"currency": "EUR", "currency_related": "USD"}
        self.assertEqual(format_transaction_field("source_bank", "TB", transaction),
                         ("Source bank", "Tatra Banka"))
        self.assertIn("31.12.2026", format_transaction_field("booking_date", "2026-12-31", transaction)[1])
        first = self.add_transaction(10, booking_date="2026-09-01")
        latest = self.add_transaction(11, booking_date="2026-10-01")
        subscription_id = create_subscription(self.finance_path, "Synthetic Sub", None,
                                              "monthly", None, None, None)
        for transaction_id, subcategory_id in ((first, self.subcategory_id), (latest, None)):
            with closing(connect_database(self.finance_path)) as connection, connection:
                connection.execute("INSERT INTO transaction_metadata(transaction_id) VALUES (?)", (transaction_id,))
                connection.execute(
                    "INSERT INTO transaction_splits(transaction_id, amount, subcategory_id, "
                    "subcategory_is_manual, is_subscription, subscription_id, subscription_is_manual) "
                    "VALUES (?, -100, ?, ?, 1, ?, 1)",
                    (transaction_id, subcategory_id, 1 if subcategory_id else None, subscription_id),
                )
        self.assertEqual(subscription_categories(self.transactions_path, self.finance_path)[subscription_id], "—")
