"""Review persistence, rule validation, rollback, and formatting boundaries."""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

from src.interface import common
from src.interface.manage import edits, tables
from src.interface.review import create, transactions
from src.transaction_types import TRANSACTION_TYPE_LABELS
from tests.support.services import MemoryServiceTestCase


class InterfaceServiceEdgeTests(MemoryServiceTestCase):
    """Review persistence, rule validation, rollback, and formatting boundaries."""

    def test_clear_manual_counterparty_category_and_notes(self):
        """Clear manual choices and provenance without losing unrelated metadata."""
        payment = self.add_payment(1)
        split_id = self.split_rows(payment)[0][0]
        owner = create.create_counterparty(self.finance_path, "Market", 1, 0, "", "")
        transactions.save_counterparty(self.finance_path, payment, owner)
        transactions.save_transaction_note(self.finance_path, payment, "Keep until cleared")
        transactions.save_subcategory(self.finance_path, split_id, 1)
        transactions.save_split_note(self.finance_path, split_id, "Split note")
        transactions.save_counterparty(self.finance_path, payment, None)
        transactions.save_subcategory(self.finance_path, split_id, None)
        self.assertEqual(self.finance.execute(
            "SELECT counterparty_id, counterparty_is_manual, note FROM transaction_metadata",
        ).fetchone(), (None, None, "Keep until cleared"))
        self.assertEqual(self.finance.execute(
            "SELECT subcategory_id, subcategory_is_manual, note FROM transaction_splits",
        ).fetchone(), (None, None, "Split note"))
        transactions.save_transaction_note(self.finance_path, payment, None)
        transactions.save_split_note(self.finance_path, split_id, None)
        self.assertIsNone(self.finance.execute("SELECT note FROM transaction_metadata").fetchone()[0])
        self.assertIsNone(self.finance.execute("SELECT note FROM transaction_splits").fetchone()[0])

    def test_subscription_decisions_clear_incompatible_links_and_provenance(self):
        """Reset linked IDs for No and Unknown decisions and preserve manual Yes."""
        payment = self.add_payment(2)
        split_id = self.split_rows(payment)[0][0]
        subscription = create.create_subscription(self.finance_path, "Music", None, "monthly", None, None, None)
        for decision, linked, expected in (("yes", subscription, (1, subscription, 1)),
                                           ("no", subscription, (0, None, 1)),
                                           ("unknown", subscription, (None, None, None))):
            with self.subTest(decision=decision):
                transactions.save_subscription_decision(self.finance_path, split_id, decision, linked)
                self.assertEqual(self.finance.execute(
                    "SELECT is_subscription, subscription_id, subscription_is_manual FROM transaction_splits",
                ).fetchone(), expected)

    def test_review_zero_missing_excluded_and_unlinked_subscription_states(self):
        """Report zero and missing splits while excluding intentionally ignored spending."""
        zero = self.add_payment(10, 0)
        missing = self.add_payment(11, with_split=False)
        excluded = self.add_payment(12)
        linked = self.add_payment(13)
        self.finance.execute("UPDATE transaction_splits SET excluded = 1 WHERE transaction_id = ?", (excluded,))
        self.finance.execute("UPDATE transaction_splits SET subcategory_id = 1, subcategory_is_manual = 1, "
                             "is_subscription = 1, subscription_is_manual = 1 WHERE transaction_id = ?", (linked,))
        self.finance.commit()
        rows = {row["id"]: row for row in transactions.review_transactions(self.payment_path, self.finance_path)}
        self.assertEqual(rows[zero]["review_reasons"], ["Zero-amount transaction needs review"])
        self.assertIn("No split exists", rows[missing]["review_reasons"])
        self.assertEqual(rows[excluded]["review_reasons"], [])
        self.assertEqual(rows[linked]["review_reasons"], ["A subscription split needs a linked subscription"])

    def test_add_split_rejects_missing_or_indivisible_amount_without_changes(self):
        """Refuse absent and one-cent splits while leaving saved amounts unchanged."""
        for number, amount, with_split in ((20, -1, True), (21, 1, True), (22, -500, False)):
            payment = self.add_payment(number, amount, with_split=with_split)
            before = self.split_rows(payment)
            with self.subTest(amount=amount, with_split=with_split), self.assertRaises(ValueError):
                transactions.add_split(self.finance_path, payment)
            self.assertEqual(self.split_rows(payment), before)

    def test_positive_split_lifecycle_preserves_total_and_minimum_amount(self):
        """Split a positive two-cent payment and merge it back without changing its total."""
        payment = self.add_payment(23, 2)
        transactions.add_split(self.finance_path, payment)
        rows = self.split_rows(payment)
        self.assertEqual([amount for _, amount in rows], [1, 1])
        with self.assertRaises(ValueError):
            transactions.add_split(self.finance_path, payment)
        transactions.delete_split(self.finance_path, payment, rows[1][0])
        self.assertEqual(self.split_rows(payment), [(rows[0][0], 2)])

    def test_delete_rejects_foreign_split_zero_merge_and_sign_flip(self):
        """Keep both splits unchanged when deletion would merge an invalid amount."""
        for number, amounts in ((30, (-100, 100)), (31, (-100, 200)), (32, (-100, -200))):
            payment = self.add_payment(number, sum(amounts), with_split=False)
            self.finance.executemany("INSERT INTO transaction_splits(transaction_id, amount) VALUES (?, ?)",
                                     [(payment, amount) for amount in amounts])
            self.finance.commit()
            before = self.split_rows(payment)
            target = before[1][0] if number != 32 else 999999
            with self.subTest(amounts=amounts), self.assertRaises(ValueError):
                transactions.delete_split(self.finance_path, payment, target)
            self.assertEqual(self.split_rows(payment), before)

    def test_creation_rejects_blank_names_and_rolls_back_invalid_subscription_rule(self):
        """Reject empty names and roll back subscriptions whose initial rule is invalid."""
        with self.assertRaises(ValueError):
            create.create_counterparty(self.finance_path, "  ", None, None, "", "")
        with self.assertRaises(ValueError):
            create.create_subscription(self.finance_path, "  ", None, "monthly", None, None, None)
        with self.assertRaises(ValueError):
            create.create_subscription(self.finance_path, "Invalid rule", None, "monthly", None, None,
                                       ("amount", "100"))
        self.assertEqual(self.finance.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0], 0)

    def test_duplicate_counterparty_rule_does_not_create_partial_entity(self):
        """Reject Unicode-equivalent initial rules without creating another counterparty."""
        # noinspection SpellCheckingInspection
        create.create_counterparty(self.finance_path, "Original", None, None, "description", "Straße")
        with self.assertRaises(ValueError):
            create.create_counterparty(self.finance_path, "Duplicate", None, None, "description", "STRASSE")
        self.assertEqual([row["name"] for row in tables.counterparties(self.finance_path)], ["Original"])

    def test_subscription_rule_uniqueness_is_scoped_and_updates_require_correct_owner(self):
        """Allow shared patterns across subscriptions while protecting each owner's rules."""
        first = create.create_subscription(self.finance_path, "First", None, "monthly", None, None, None)
        second = create.create_subscription(self.finance_path, "Second", None, "monthly", None, None, None)
        for owner in (first, second):
            edits.add_rule(self.finance_path, "subscription_match_rules", "subscription_id", owner,
                           "description", "MUSIC")
        rule_id = tables.rules(self.finance_path, "subscription_match_rules", "subscription_id", first)[0][0]
        with self.assertRaises(ValueError):
            edits.add_rule(self.finance_path, "subscription_match_rules", "subscription_id", first,
                           "description", "music")
        edits.update_rule(self.finance_path, "subscription_match_rules", "subscription_id", first,
                          rule_id, "description", "MUSIC")
        edits.update_rule(self.finance_path, "subscription_match_rules", "subscription_id", second,
                          rule_id, "description", "WRONG OWNER")
        self.assertEqual(tables.rules(self.finance_path, "subscription_match_rules", "subscription_id", first)[0][2],
                         "MUSIC")

    def test_rule_services_reject_invalid_identifiers_fields_and_blank_patterns(self):
        """Reject unsupported SQL identifiers and invalid rule inputs before storing them."""
        for operation in (
                lambda: edits.add_rule(self.finance_path, "counterparties_match_rules", "subscription_id", 1,
                                       "description", "x"),
                lambda: edits.update_rule(self.finance_path, "transactions", "counterparty_id", 1, 1, "description",
                                          "x"),
                lambda: edits.delete_rule(self.finance_path, "transactions", 1),
                lambda: edits._validate_rule_duplicate(self.finance, "transactions", None, "description", "x"),
                lambda: tables.rules(self.finance_path, "transactions", "counterparty_id", 1),
                lambda: edits.add_rule(self.finance_path, "counterparties_match_rules", "counterparty_id", 1, "amount",
                                       "x"),
                lambda: edits.add_rule(self.finance_path, "counterparties_match_rules", "counterparty_id", 1,
                                       "description", " "),
        ):
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                operation()
        self.assertEqual(self.finance.execute("SELECT COUNT(*) FROM counterparties_match_rules").fetchone()[0], 0)

    def test_review_deduplicates_reasons_and_keeps_balance_checks_for_excluded_splits(self):
        """Show one warning per missing decision and retain balance validation for excluded splits."""
        payment = self.add_payment(72)
        transactions.add_split(self.finance_path, payment)
        row = transactions.review_transactions(self.payment_path, self.finance_path)[0]
        self.assertEqual(row["review_reasons"].count("A split needs a subcategory"), 1)
        self.assertEqual(row["review_reasons"].count("A split needs a subscription answer"), 1)
        self.finance.execute("UPDATE transaction_splits SET excluded = 1, amount = -1")
        self.finance.commit()
        row = transactions.review_transactions(self.payment_path, self.finance_path)[0]
        self.assertEqual(row["review_reasons"], ["Split amounts do not equal the transaction amount"])

    def test_missing_insert_ids_and_query_metadata_raise_explicit_failures(self):
        """Fail clearly when a database driver does not return required insert or query metadata."""
        connection = MagicMock()
        connection.__enter__.return_value = connection
        # noinspection SpellCheckingInspection
        connection.execute.return_value.lastrowid = None
        connection.execute.return_value.description = None
        for module, operation in (
                (create, lambda: create.create_counterparty(self.finance_path, "Shop", None, None, "", "")),
                (create,
                 lambda: create.create_subscription(self.finance_path, "Music", None, "monthly", None, None, None)),
                (transactions, lambda: transactions.review_transactions(self.payment_path, self.finance_path)),
        ):
            with self.subTest(operation=operation), patch.dict(vars(module),
                                                               {"connect_database": Mock(return_value=connection)}):
                with self.assertRaises(RuntimeError):
                    operation()

    def test_field_formatting_handles_related_currency_unknown_types_and_invalid_dates(self):
        """Use related currency and preserve readable fallbacks for unknown imported fields."""
        transaction = {"currency": "EUR", "currency_related": "USD"}
        self.assertEqual(common.format_money(-1234, "USD"), "-$12.34")
        self.assertEqual(transactions.format_transaction_field("amount_related", 1234, transaction),
                         ("Amount related", "$12.34"))
        self.assertEqual(transactions.format_transaction_field("transaction_type", "CUSTOM", transaction),
                         ("Transaction type", "CUSTOM"))
        value, label = next(iter(TRANSACTION_TYPE_LABELS.items()))
        self.assertEqual(transactions.format_transaction_field("transaction_type", value, transaction)[1], label)
        self.assertEqual(transactions.format_transaction_field("booking_date", "invalid", transaction)[1], "invalid")
