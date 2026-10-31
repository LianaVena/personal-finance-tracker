"""Matching ambiguity, calendar boundaries, and stale subscription behavior."""

from __future__ import annotations

import contextlib
import io
from datetime import date

from src import categorization
from src.interface.manage import edits, tables
from src.interface.review import create, transactions
from tests.support.services import MemoryServiceTestCase


class MatchingEdgeCaseTests(MemoryServiceTestCase):
    """Matching ambiguity, calendar boundaries, and stale subscription behavior."""

    def test_text_and_date_boundaries_handle_blank_invalid_and_month_end_inputs(self):
        """Reject missing match evidence and clamp calendar periods at month and year ends."""
        for text, pattern in ((None, "x"), ("", "x"), ("x", ""), ("x", "  ")):
            self.assertFalse(categorization._contains(text, pattern))
        for booking_date in (None, "", "not a date"):
            self.assertIsNone(categorization._period_key(booking_date, "monthly"))
        self.assertEqual(categorization._add_billing_period(date(2024, 2, 29), "yearly"), date(2025, 2, 28))
        self.assertEqual(categorization._add_billing_period(date(2026, 12, 31), "monthly"), date(2027, 1, 31))

    def test_removed_matching_rules_clear_only_automatic_assignments(self):
        """Recompute automatic choices after a rule changes while retaining notes and split IDs."""
        payment = self.add_payment(70)
        owner = create.create_counterparty(self.finance_path, "Shop", 1, 0, "payment_message", "SHOP")
        categorization.apply_matching_rules(self.payment_path, self.finance_path)
        before = self.split_rows(payment)
        transactions.save_transaction_note(self.finance_path, payment, "Keep note")
        rule_id = tables.rules(self.finance_path, "counterparties_match_rules", "counterparty_id", owner)[0][0]
        edits.update_rule(self.finance_path, "counterparties_match_rules", "counterparty_id", owner,
                          rule_id, "payment_message", "NO LONGER MATCHES")
        self.assertEqual(categorization.apply_matching_rules(self.payment_path, self.finance_path), 1)
        self.assertEqual(self.finance.execute(
            "SELECT counterparty_id, counterparty_is_manual, note FROM transaction_metadata WHERE transaction_id = ?",
            (payment,),
        ).fetchone(), (None, None, "Keep note"))
        self.assertEqual(self.finance.execute(
            "SELECT subcategory_id, subcategory_is_manual, is_subscription, subscription_is_manual "
            "FROM transaction_splits WHERE transaction_id = ?", (payment,),
        ).fetchone(), (None, None, None, None))
        self.assertEqual(self.split_rows(payment), before)
        self.assertEqual(categorization.apply_matching_rules(self.payment_path, self.finance_path), 0)

    def test_subscription_becomes_stale_only_after_exact_calendar_due_date(self):
        """Keep a month-end subscription active on its due date and expire it the next day."""
        payment = self.add_payment(71, booking_date="2026-01-31")
        subscription = create.create_subscription(self.finance_path, "Month end", None, "monthly", None, None, None)
        split_id = self.split_rows(payment)[0][0]
        transactions.save_subscription_decision(self.finance_path, split_id, "yes", subscription)
        self.assertEqual(categorization.inactivate_stale_subscriptions(self.payment_path, self.finance_path,
                                                                       date(2026, 2, 28)), 0)
        self.assertEqual(categorization.inactivate_stale_subscriptions(self.payment_path, self.finance_path,
                                                                       date(2026, 3, 1)), 1)
        self.assertEqual(categorization.inactivate_stale_subscriptions(self.payment_path, self.finance_path,
                                                                       date(2026, 3, 1)), 0)

    def test_subscription_without_counterparty_can_match_a_text_rule(self):
        """Match rule-only subscriptions while rejecting unrelated messages and currencies."""
        matching = self.add_payment(40, message="MUSIC", booking_date="2026-01-01")
        unrelated = self.add_payment(41, message="OTHER", booking_date="2026-02-01")
        invalid_date = self.add_payment(42, message="MUSIC", booking_date="invalid")
        subscription = create.create_subscription(self.finance_path, "Music", None, "monthly", -500, "EUR",
                                                  ("payment_message", "MUSIC"))
        categorization.apply_matching_rules(self.payment_path, self.finance_path)
        linked = dict(self.finance.execute("SELECT transaction_id, subscription_id FROM transaction_splits"))
        self.assertEqual(linked[matching], subscription)
        self.assertIsNone(linked[unrelated])
        self.assertIsNone(linked[invalid_date])
        self.payments.execute("UPDATE transactions SET currency = 'USD' WHERE id = ?", (matching,))
        self.payments.commit()
        categorization.apply_matching_rules(self.payment_path, self.finance_path)
        self.assertIsNone(
            self.finance.execute("SELECT subscription_id FROM transaction_splits WHERE transaction_id = ?",
                                 (matching,)).fetchone()[0])

    def test_multiple_subscription_matches_leave_payment_ambiguous(self):
        """Keep a payment unresolved when two subscriptions match the same evidence."""
        payment = self.add_payment(50, message="MUSIC")
        for name in ("First", "Second"):
            create.create_subscription(self.finance_path, name, None, "monthly", None, None,
                                       ("payment_message", "MUSIC"))
        categorization.apply_matching_rules(self.payment_path, self.finance_path)
        self.assertEqual(self.finance.execute(
            "SELECT is_subscription, subscription_id, subscription_is_manual FROM transaction_splits WHERE transaction_id = ?",
            (payment,),
        ).fetchone(), (None, None, None))

    def test_counterparty_only_subscription_without_signature_stays_unresolved(self):
        """Require text or amount evidence in addition to a linked counterparty."""
        payment = self.add_payment(51)
        owner = create.create_counterparty(self.finance_path, "Shop", None, None, "payment_message", "SHOP")
        create.create_subscription(self.finance_path, "No signature", owner, "monthly", None, None, None)
        categorization.apply_matching_rules(self.payment_path, self.finance_path)
        self.assertIsNone(self.finance.execute(
            "SELECT subscription_id FROM transaction_splits WHERE transaction_id = ?", (payment,),
        ).fetchone()[0])

    def test_orphan_metadata_is_reported_and_preserved(self):
        """Warn about orphan metadata without deleting notes or classifications."""
        orphan = "f" * 64
        self.finance.execute("INSERT INTO transaction_metadata(transaction_id, note) VALUES (?, 'Keep')", (orphan,))
        self.finance.commit()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(categorization.apply_matching_rules(self.payment_path, self.finance_path), 0)
        self.assertIn("1 metadata row(s) for missing transactions", output.getvalue())
        self.assertEqual(self.finance.execute("SELECT note FROM transaction_metadata").fetchone(), ("Keep",))

    def test_stale_subscription_skips_invalid_unlinked_and_inactive_payments(self):
        """Leave subscriptions active when no valid linked date establishes an overdue period."""
        invalid = self.add_payment(60, booking_date="invalid")
        self.add_payment(61, booking_date="2020-01-01")
        active = create.create_subscription(self.finance_path, "Active", None, "monthly", None, None, None)
        inactive = create.create_subscription(self.finance_path, "Inactive", None, "monthly", None, None, None)
        self.finance.execute("UPDATE subscriptions SET is_active = 0 WHERE id = ?", (inactive,))
        self.finance.execute("UPDATE transaction_splits SET is_subscription = 1, subscription_id = ?, "
                             "subscription_is_manual = 1 WHERE transaction_id = ?", (active, invalid))
        self.finance.commit()
        self.assertEqual(categorization.inactivate_stale_subscriptions(self.payment_path, self.finance_path,
                                                                       date(2026, 10, 26)), 0)
        self.assertEqual(self.finance.execute("SELECT is_active FROM subscriptions WHERE id = ?", (active,)).fetchone(),
                         (1,))
