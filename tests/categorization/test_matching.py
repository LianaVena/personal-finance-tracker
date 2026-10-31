"""Synthetic acceptance tests for automatic counterparty and subscription matching."""

import hashlib
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path

from src.categorization import apply_matching_rules, inactivate_stale_subscriptions
from src.database import connect_database, create_finance_tables, create_transactions_table


class MatchingRuleTests(unittest.TestCase):
    """Exercise automatic matching with isolated synthetic SQLite data."""

    def setUp(self):
        """Create temporary databases and the test category hierarchy."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.transactions_path = root / "transactions.db"
        self.finance_path = root / "finance.db"
        create_transactions_table(self.transactions_path)
        create_finance_tables(self.finance_path)
        with closing(connect_database(self.finance_path)) as connection, connection:
            category = connection.execute("INSERT INTO categories(name) VALUES ('Essentials')")
            self.category_id = category.lastrowid
            self.food_id = connection.execute(
                "INSERT INTO subcategories(category_id, name) VALUES (?, 'Food')",
                (self.category_id,),
            ).lastrowid
            self.other_subcategory_id = connection.execute(
                "INSERT INTO subcategories(category_id, name) VALUES (?, 'Other')",
                (self.category_id,),
            ).lastrowid

    def add_transaction(self, number, *, message=None, description=None, amount=-1250,
                        booking_date="2026-10-01", currency="EUR", counterparty_name=None):
        """Insert a synthetic transaction with a deterministic test ID.

        Args:
            number: Unique test value used to derive the transaction ID.
            message: Optional payment message.
            description: Optional transaction description.
            amount: Signed amount in integer minor units.
            booking_date: ISO-formatted booking date.
            currency: Transaction currency code.
            counterparty_name: Optional bank-provided counterparty name.

        Returns:
            Stable SHA-256 ID of the inserted synthetic transaction.
        """
        transaction_id = hashlib.sha256(str(number).encode()).hexdigest()
        with closing(connect_database(self.transactions_path)) as connection, connection:
            connection.execute(
                "INSERT INTO transactions (id, source_bank, booking_date, amount, currency, "
                "counterparty_name, description, payment_message) VALUES (?, 'TB', ?, ?, ?, ?, ?, ?)",
                (transaction_id, booking_date, amount, currency, counterparty_name, description, message),
            )
        return transaction_id

    def add_counterparty(self, name, *, field="payment_message", pattern=None,
                         subcategory_id=None, subscription_default=None):
        """Insert a counterparty and optionally one matching rule.

        Args:
            name: Counterparty name.
            field: Transaction field inspected by the optional rule.
            pattern: Optional contains-match pattern.
            subcategory_id: Optional default subcategory ID.
            subscription_default: Optional default subscription answer.

        Returns:
            ID of the inserted counterparty.
        """
        with closing(connect_database(self.finance_path)) as connection, connection:
            counterparty_id = connection.execute(
                "INSERT INTO counterparties(name, default_subcategory_id, default_is_subscription) "
                "VALUES (?, ?, ?)", (name, subcategory_id, subscription_default),
            ).lastrowid
            if pattern is not None:
                connection.execute(
                    "INSERT INTO counterparties_match_rules(counterparty_id, source_field, pattern) "
                    "VALUES (?, ?, ?)", (counterparty_id, field, pattern),
                )
        return counterparty_id

    def add_counterparty_rule(self, counterparty_id, field, pattern):
        """Add a matching rule to an existing synthetic counterparty.

        Args:
            counterparty_id: ID of the counterparty receiving the rule.
            field: Transaction field inspected by the rule.
            pattern: Contains-match text pattern.
        """
        with closing(connect_database(self.finance_path)) as connection, connection:
            connection.execute(
                "INSERT INTO counterparties_match_rules(counterparty_id, source_field, pattern) "
                "VALUES (?, ?, ?)", (counterparty_id, field, pattern),
            )

    def add_subscription(self, name, counterparty_id, *, amount=None, currency=None,
                         period="monthly", active=1, rule=None):
        """Insert a subscription and optionally its identifying text rule.

        Args:
            name: Subscription name.
            counterparty_id: Associated counterparty ID, if any.
            amount: Optional expected amount in minor units.
            currency: Currency paired with the expected amount.
            period: Billing period, either monthly or yearly.
            active: Initial active state.
            rule: Optional source-field and pattern pair.

        Returns:
            ID of the inserted subscription.
        """
        with closing(connect_database(self.finance_path)) as connection, connection:
            subscription_id = connection.execute(
                "INSERT INTO subscriptions(name, counterparty_id, billing_period, expected_amount, "
                "currency, is_active) VALUES (?, ?, ?, ?, ?, ?)",
                (name, counterparty_id, period, amount, currency, active),
            ).lastrowid
            if rule:
                connection.execute(
                    "INSERT INTO subscription_match_rules(subscription_id, source_field, pattern) "
                    "VALUES (?, ?, ?)", (subscription_id, rule[0], rule[1]),
                )
        return subscription_id

    def split(self, transaction_id):
        """Return the transaction's single split for concise assertions.

        Args:
            transaction_id: Stable hash ID of the parent transaction.

        Returns:
            The split row containing amount, category, subscription, and note values.
        """
        with closing(connect_database(self.finance_path)) as connection:
            return connection.execute(
                "SELECT amount, subcategory_id, subcategory_is_manual, is_subscription, "
                "subscription_id, subscription_is_manual, excluded, note "
                "FROM transaction_splits WHERE transaction_id = ?",
                (transaction_id,),
            ).fetchone()

    def test_wolt_ordinary_payment_and_specific_wolt_plus_signature(self):
        """Classify ordinary Wolt purchases separately from Wolt+ renewals."""
        ordinary = self.add_transaction(1, message="Wolt food order", amount=-1290)
        plus = self.add_transaction(2, message="Wolt+ monthly membership", amount=-500)
        wolt_id = self.add_counterparty(
            "Wolt", pattern="Wolt", subcategory_id=self.food_id, subscription_default=0,
        )
        wolt_plus_id = self.add_subscription(
            "Wolt+", wolt_id, amount=-500, currency="EUR", rule=("payment_message", "Wolt+"),
        )

        apply_matching_rules(self.transactions_path, self.finance_path)

        ordinary_split = self.split(ordinary)
        plus_split = self.split(plus)
        self.assertEqual(ordinary_split[1:6], (self.food_id, 0, 0, None, 0))
        self.assertEqual(plus_split[1:6], (self.food_id, 0, 1, wolt_plus_id, 0))

    def test_ambiguous_same_period_subscription_candidates_stay_unknown(self):
        """Leave multiple same-period candidate payments unresolved."""
        first = self.add_transaction(10, message="Wolt+ renewal one", amount=-500)
        second = self.add_transaction(11, message="Wolt+ renewal two", amount=-500,
                                      booking_date="2026-10-22")
        wolt_id = self.add_counterparty(
            "Wolt", pattern="Wolt", subcategory_id=self.food_id, subscription_default=0,
        )
        self.add_subscription("Wolt+", wolt_id, amount=-500, currency="EUR",
                              rule=("payment_message", "Wolt+"))

        apply_matching_rules(self.transactions_path, self.finance_path)

        for transaction_id in (first, second):
            split = self.split(transaction_id)
            self.assertEqual(split[1], self.food_id)
            self.assertEqual(split[3:6], (None, None, None))

    def test_two_matching_rules_for_one_counterparty_are_one_match(self):
        """Treat multiple matching rules for one merchant as one candidate."""
        transaction_id = self.add_transaction(20, message="shop direct payment", description="Wolt")
        wolt_id = self.add_counterparty("Wolt", field="payment_message", pattern="shop",
                                        subcategory_id=self.food_id, subscription_default=0)
        self.add_counterparty_rule(wolt_id, "description", "wolt")

        apply_matching_rules(self.transactions_path, self.finance_path)

        with closing(connect_database(self.finance_path)) as connection:
            metadata = connection.execute(
                "SELECT counterparty_id, counterparty_is_manual FROM transaction_metadata "
                "WHERE transaction_id = ?", (transaction_id,),
            ).fetchone()
        self.assertEqual(metadata, (wolt_id, 0))
        self.assertEqual(self.split(transaction_id)[1], self.food_id)

    def test_different_matching_counterparties_are_unresolved(self):
        """Avoid choosing arbitrarily when different merchants match."""
        transaction_id = self.add_transaction(30, message="shop pharmacy")
        self.add_counterparty("Shop", pattern="shop", subcategory_id=self.food_id,
                              subscription_default=0)
        self.add_counterparty("Pharmacy", pattern="pharmacy", subcategory_id=self.other_subcategory_id,
                              subscription_default=1)

        apply_matching_rules(self.transactions_path, self.finance_path)

        with closing(connect_database(self.finance_path)) as connection:
            metadata = connection.execute(
                "SELECT counterparty_id, counterparty_is_manual FROM transaction_metadata "
                "WHERE transaction_id = ?", (transaction_id,),
            ).fetchone()
        self.assertEqual(metadata, (None, None))
        self.assertEqual(self.split(transaction_id)[1:6], (None, None, None, None, None))

    def test_unicode_casefold_contains_matching(self):
        """Match Slovak text with Unicode-aware case folding."""
        transaction_id = self.add_transaction(40, message="Platba za ŽLTÝ čaj")
        self.add_counterparty("Tea", pattern="žltý ČAJ", subcategory_id=self.food_id,
                              subscription_default=0)

        apply_matching_rules(self.transactions_path, self.finance_path)

        self.assertEqual(self.split(transaction_id)[1:6], (self.food_id, 0, 0, None, 0))

    def test_manual_counterparty_category_subscription_note_and_exclusion_survive_refresh(self):
        """Preserve manual metadata and split decisions during rematching."""
        transaction_id = self.add_transaction(50, message="Wolt order")
        wolt_id = self.add_counterparty("Wolt", pattern="Wolt", subcategory_id=self.food_id,
                                        subscription_default=0)
        other_id = self.add_counterparty("Other", pattern="never", subcategory_id=self.other_subcategory_id,
                                         subscription_default=1)
        apply_matching_rules(self.transactions_path, self.finance_path)
        with closing(connect_database(self.finance_path)) as connection, connection:
            connection.execute(
                "UPDATE transaction_metadata SET counterparty_id = ?, counterparty_is_manual = 1 "
                "WHERE transaction_id = ?", (other_id, transaction_id),
            )
            connection.execute(
                "UPDATE transaction_splits SET subcategory_id = ?, subcategory_is_manual = 1, "
                "is_subscription = 0, subscription_id = NULL, subscription_is_manual = 1, "
                "excluded = 1, note = 'manual note' WHERE transaction_id = ?",
                (self.food_id, transaction_id),
            )

        apply_matching_rules(self.transactions_path, self.finance_path)

        with closing(connect_database(self.finance_path)) as connection:
            metadata = connection.execute(
                "SELECT counterparty_id, counterparty_is_manual FROM transaction_metadata "
                "WHERE transaction_id = ?", (transaction_id,),
            ).fetchone()
        self.assertEqual(metadata, (other_id, 1))
        self.assertEqual(self.split(transaction_id),
                         (-1250, self.food_id, 1, 0, None, 1, 1, "manual note"))
        self.assertNotEqual(other_id, wolt_id)

    def test_reapplication_is_idempotent_and_does_not_duplicate_splits(self):
        """Ensure repeated matching creates no duplicate metadata or splits."""
        transaction_id = self.add_transaction(60, message="Wolt order")
        self.add_counterparty("Wolt", pattern="Wolt", subcategory_id=self.food_id,
                              subscription_default=0)
        self.assertGreater(apply_matching_rules(self.transactions_path, self.finance_path), 0)
        self.assertEqual(apply_matching_rules(self.transactions_path, self.finance_path), 0)
        with closing(connect_database(self.finance_path)) as connection:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM transaction_metadata WHERE transaction_id = ?", (transaction_id,)
            ).fetchone()[0], 1)
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM transaction_splits WHERE transaction_id = ?", (transaction_id,)
            ).fetchone()[0], 1)

    def test_inactive_subscription_still_matches_historical_transactions(self):
        """Keep inactive subscriptions eligible for historical recognition."""
        transaction_id = self.add_transaction(70, message="Netflix subscription", amount=-1599)
        netflix = self.add_counterparty("Netflix", pattern="Netflix", subcategory_id=self.food_id,
                                        subscription_default=1)
        subscription_id = self.add_subscription("Netflix", netflix, amount=-1599,
                                                currency="EUR", active=0)

        apply_matching_rules(self.transactions_path, self.finance_path)

        self.assertEqual(self.split(transaction_id)[3:6], (1, subscription_id, 0))

    def test_subscription_expected_amount_ignores_sign(self):
        """Match recurring signatures regardless of the imported amount sign."""
        debit = self.add_transaction(71, message="Membership", amount=-500,
                                     booking_date="2026-10-02")
        credit = self.add_transaction(72, message="Membership", amount=500,
                                      booking_date="2026-11-02")
        counterparty_id = self.add_counterparty(
            "Service", pattern="Membership", subcategory_id=self.food_id,
            subscription_default=0,
        )
        subscription_id = self.add_subscription(
            "Membership", counterparty_id, amount=500, currency="EUR",
            rule=("payment_message", "Membership"),
        )

        apply_matching_rules(self.transactions_path, self.finance_path)

        for transaction_id in (debit, credit):
            self.assertEqual(self.split(transaction_id)[3:6], (1, subscription_id, 0))

    def test_amount_alone_never_matches_subscription_for_an_unrelated_merchant(self):
        """Prevent an amount-only match from linking another merchant's payment."""
        transaction_id = self.add_transaction(80, message="A different shop", amount=-500)
        self.add_counterparty("Other shop", pattern="different shop", subscription_default=None)
        wolt = self.add_counterparty("Wolt", pattern="Wolt", subscription_default=0)
        self.add_subscription("Wolt+", wolt, amount=-500, currency="EUR")

        apply_matching_rules(self.transactions_path, self.finance_path)

        self.assertEqual(self.split(transaction_id)[3:6], (None, None, None))

    def test_stale_subscription_uses_latest_payment_and_calendar_period(self):
        """Inactivate overdue subscriptions while keeping recent and unpaid ones active."""
        older_id = self.add_transaction(90, booking_date="2026-01-01", amount=-100)
        latest_id = self.add_transaction(91, booking_date="2026-09-30", amount=-100)
        with closing(connect_database(self.finance_path)) as connection, connection:
            monthly_id = connection.execute(
                "INSERT INTO subscriptions(name, billing_period) VALUES ('Monthly', 'monthly')"
            ).lastrowid
            yearly_id = connection.execute(
                "INSERT INTO subscriptions(name, billing_period) VALUES ('Yearly', 'yearly')"
            ).lastrowid
            unpaid_id = connection.execute(
                "INSERT INTO subscriptions(name, billing_period) VALUES ('No payment', 'monthly')"
            ).lastrowid
            for transaction_id, subscription_id in ((older_id, monthly_id), (latest_id, monthly_id),
                                                    (latest_id, yearly_id)):
                connection.execute(
                    "INSERT OR IGNORE INTO transaction_metadata(transaction_id) VALUES (?)",
                    (transaction_id,),
                )
                connection.execute(
                    "INSERT INTO transaction_splits(transaction_id, amount, is_subscription, "
                    "subscription_id, subscription_is_manual) VALUES (?, -100, 1, ?, 1)",
                    (transaction_id, subscription_id),
                )

        changed = inactivate_stale_subscriptions(
            self.transactions_path, self.finance_path, today=date(2026, 11, 1),
        )

        self.assertEqual(changed, 1)
        with closing(connect_database(self.finance_path)) as connection:
            active_by_id = dict(connection.execute("SELECT id, is_active FROM subscriptions"))
        self.assertEqual(active_by_id, {monthly_id: 0, yearly_id: 1, unpaid_id: 1})


if __name__ == "__main__":
    unittest.main()
