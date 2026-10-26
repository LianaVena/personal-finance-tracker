"""Idempotent counterparty and subscription matching for finance.db."""

import calendar
from collections import defaultdict
from contextlib import closing
from datetime import date
from pathlib import Path

from .database import connect_database

MATCH_FIELDS = (
    "counterparty_name", "counterparty_iban", "payer_reference",
    "payment_message", "description",
)


def _contains(value, pattern: str) -> bool:
    """Apply the required Unicode-aware contains match, skipping empty input.

    Args:
        value: Source-field value to search, or ``None`` when unavailable.
        pattern: Non-empty text pattern to find within the source value.

    Returns:
        Whether the pattern occurs in the source value after case folding.
    """
    if value is None or not pattern or not pattern.strip():
        return False
    text = str(value).strip()
    return bool(text) and pattern.strip().casefold() in text.casefold()


def _matched_rules(transaction: dict, rules: list[tuple]) -> set[int]:
    """Return distinct owners whose configured source fields match a transaction.

    Args:
        transaction: Imported transaction keyed by source-field name.
        rules: Rule tuples containing owner ID, source field, and pattern.

    Returns:
        The set of matching owner IDs.
    """
    return {
        owner_id for owner_id, source_field, pattern in rules
        if source_field in MATCH_FIELDS and _contains(transaction.get(source_field), pattern)
    }


def _period_key(booking_date: str | None, billing_period: str) -> str | None:
    """Normalize a booking date to its monthly or yearly matching period.

    Args:
        booking_date: ISO-formatted booking date, or ``None`` if unavailable.
        billing_period: Subscription period, either ``monthly`` or ``yearly``.

    Returns:
        A ``YYYY-MM`` or ``YYYY`` period key, or ``None`` for an invalid date.
    """
    if not booking_date:
        return None
    try:
        parsed = date.fromisoformat(booking_date)
    except ValueError:
        return None
    return parsed.strftime("%Y-%m" if billing_period == "monthly" else "%Y")


def _add_billing_period(value: date, billing_period: str) -> date:
    """Add one calendar month/year, clamping month-end dates when needed.

    Args:
        value: Starting calendar date.
        billing_period: Subscription period, either ``monthly`` or ``yearly``.

    Returns:
        The date one billing period later, clamped to the target month's end.
    """
    if billing_period == "yearly":
        year = value.year + 1
        month = value.month
    else:
        month_index = value.year * 12 + value.month
        year, month_index = divmod(month_index, 12)
        month = month_index + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def inactivate_stale_subscriptions(transaction_db_path: str | Path,
                                   finance_db_path: str | Path,
                                   today: date | None = None) -> int:
    """Inactivate subscriptions whose latest linked payment is past its period.

    Transactions and finance data are stored separately, so transaction dates
    are read from the imported database and linked through split IDs in Python.
    Subscriptions without a valid linked booking date are left unchanged.

    Args:
        transaction_db_path: Path to the imported transactions' database.
        finance_db_path: Path to the persistent finance database.
        today: Date used for comparison; defaults to the current local date.

    Returns:
        Number of active subscriptions changed to inactive.
    """
    today = today or date.today()
    with closing(connect_database(finance_db_path)) as connection:
        subscriptions = connection.execute(
            "SELECT id, billing_period FROM subscriptions WHERE is_active = 1"
        ).fetchall()
        linked_transactions: dict[int, set[str]] = {row[0]: set() for row in subscriptions}
        for subscription_id, transaction_id in connection.execute(
                "SELECT DISTINCT sp.subscription_id, sp.transaction_id "
                "FROM transaction_splits AS sp "
                "JOIN transaction_metadata AS tm ON tm.transaction_id = sp.transaction_id "
                "WHERE sp.subscription_id IS NOT NULL"
        ):
            if subscription_id in linked_transactions:
                linked_transactions[subscription_id].add(transaction_id)

    all_ids = set().union(*linked_transactions.values()) if linked_transactions else set()
    dates_by_id: dict[str, date] = {}
    if all_ids:
        with closing(connect_database(transaction_db_path)) as connection:
            cursor = connection.execute("SELECT id, booking_date FROM transactions")
            wanted = all_ids
            for transaction_id, booking_date in cursor:
                if transaction_id not in wanted:
                    continue
                try:
                    dates_by_id[transaction_id] = date.fromisoformat(booking_date)
                except (TypeError, ValueError):
                    continue

    stale_ids = []
    for subscription_id, billing_period in subscriptions:
        booking_dates = [dates_by_id[transaction_id]
                         for transaction_id in linked_transactions[subscription_id]
                         if transaction_id in dates_by_id]
        if booking_dates and today > _add_billing_period(max(booking_dates), billing_period):
            stale_ids.append(subscription_id)

    if stale_ids:
        with closing(connect_database(finance_db_path)) as connection, connection:
            connection.executemany(
                "UPDATE subscriptions SET is_active = 0 WHERE id = ? AND is_active = 1",
                ((subscription_id,) for subscription_id in stale_ids),
            )
    return len(stale_ids)


def apply_matching_rules(transaction_db_path: str | Path,
                         finance_db_path: str | Path) -> int:
    """Refresh automatic assignments while preserving all manual split edits.

    The return value is the number of transaction IDs whose finance metadata
    or split state changed. Imported transactions are initialized exactly
    once; zero-amount payments receive metadata but no zero-value split.

    Args:
        transaction_db_path: Path to the imported transactions' database.
        finance_db_path: Path to the persistent finance database.

    Returns:
        Number of transaction IDs whose metadata or split state changed.
    """
    with closing(connect_database(transaction_db_path)) as tx_connection:
        cursor = tx_connection.execute("SELECT * FROM transactions")
        tx_columns = [column[0] for column in cursor.description]
        transactions = [dict(zip(tx_columns, row)) for row in cursor.fetchall()]

    changed: set[str] = set()
    with closing(connect_database(finance_db_path)) as connection:
        with connection:
            imported_ids = {transaction["id"] for transaction in transactions}
            orphan_count = sum(
                1 for (transaction_id,) in connection.execute(
                    "SELECT transaction_id FROM transaction_metadata"
                ) if transaction_id not in imported_ids
            )
            if orphan_count:
                print(f"Warning: finance.db contains {orphan_count} metadata row(s) for missing transactions")

            counterparties = {
                row[0]: {"subcategory": row[1], "subscription": row[2]}
                for row in connection.execute(
                    "SELECT id, default_subcategory_id, default_is_subscription FROM counterparties"
                )
            }
            counterparty_rules = connection.execute(
                "SELECT counterparty_id, source_field, pattern FROM counterparties_match_rules"
            ).fetchall()

            resolved_by_id: dict[str, int | None] = {}
            transaction_by_id = {transaction["id"]: transaction for transaction in transactions}
            for transaction in transactions:
                transaction_id = transaction["id"]
                inserted_metadata = connection.execute(
                    "INSERT OR IGNORE INTO transaction_metadata(transaction_id) VALUES (?)",
                    (transaction_id,),
                ).rowcount
                if inserted_metadata:
                    changed.add(transaction_id)

                metadata = connection.execute(
                    "SELECT counterparty_id, counterparty_is_manual FROM transaction_metadata "
                    "WHERE transaction_id = ?",
                    (transaction_id,),
                ).fetchone()
                split_count = connection.execute(
                    "SELECT COUNT(*) FROM transaction_splits WHERE transaction_id = ?",
                    (transaction_id,),
                ).fetchone()[0]
                amount = transaction.get("amount")
                if split_count == 0 and amount:
                    connection.execute(
                        "INSERT INTO transaction_splits(transaction_id, amount) VALUES (?, ?)",
                        (transaction_id, amount),
                    )
                    changed.add(transaction_id)

                current_counterparty, is_manual = metadata
                if is_manual == 1:
                    counterparty_id = current_counterparty
                else:
                    candidates = _matched_rules(transaction, counterparty_rules)
                    counterparty_id = next(iter(candidates)) if len(candidates) == 1 else None
                    if (current_counterparty, is_manual) != (
                            counterparty_id, 0 if counterparty_id is not None else None,
                    ):
                        connection.execute(
                            "UPDATE transaction_metadata SET counterparty_id = ?, "
                            "counterparty_is_manual = ? WHERE transaction_id = ?",
                            (counterparty_id, 0 if counterparty_id is not None else None, transaction_id),
                        )
                        changed.add(transaction_id)
                resolved_by_id[transaction_id] = counterparty_id

                default_subcategory = (
                    counterparties.get(counterparty_id, {}).get("subcategory")
                    if counterparty_id is not None else None
                )
                splits = connection.execute(
                    "SELECT id, subcategory_id, subcategory_is_manual FROM transaction_splits "
                    "WHERE transaction_id = ?",
                    (transaction_id,),
                ).fetchall()
                for split_id, subcategory_id, category_manual in splits:
                    if category_manual == 1:
                        continue
                    next_manual = 0 if default_subcategory is not None else None
                    if (subcategory_id, category_manual) != (default_subcategory, next_manual):
                        connection.execute(
                            "UPDATE transaction_splits SET subcategory_id = ?, "
                            "subcategory_is_manual = ? WHERE id = ?",
                            (default_subcategory, next_manual, split_id),
                        )
                        changed.add(transaction_id)

            subscriptions = {
                row[0]: {
                    "counterparty_id": row[1], "period": row[2],
                    "expected_amount": row[3], "currency": row[4],
                }
                for row in connection.execute(
                    "SELECT id, counterparty_id, billing_period, expected_amount, currency "
                    "FROM subscriptions"
                )
            }
            subscription_rules = connection.execute(
                "SELECT subscription_id, source_field, pattern FROM subscription_match_rules"
            ).fetchall()
            rules_by_subscription: dict[int, list[tuple[str, str]]] = defaultdict(list)
            for subscription_id, source_field, pattern in subscription_rules:
                rules_by_subscription[subscription_id].append((source_field, pattern))

            candidates: dict[tuple[int, str], list[tuple[str, int]]] = defaultdict(list)
            candidate_subscriptions_by_transaction: dict[str, set[int]] = defaultdict(set)
            all_splits: list[tuple] = []
            for transaction_id, transaction in transaction_by_id.items():
                current_counterparty = resolved_by_id.get(transaction_id)
                for split in connection.execute(
                        "SELECT id, amount, is_subscription, subscription_id, subscription_is_manual "
                        "FROM transaction_splits WHERE transaction_id = ?",
                        (transaction_id,),
                ):
                    split_id, amount, is_subscription, subscription_id, subscription_manual = split
                    all_splits.append((transaction_id, split_id, amount, subscription_manual))
                    matched_subscriptions: set[int] = set()
                    for candidate_id, subscription in subscriptions.items():
                        linked_counterparty = subscription["counterparty_id"]
                        text_rules = rules_by_subscription[candidate_id]
                        text_match = any(
                            _contains(transaction.get(source_field), pattern)
                            for source_field, pattern in text_rules
                        )
                        if linked_counterparty is not None:
                            if current_counterparty != linked_counterparty:
                                continue
                        elif not text_match:
                            continue
                        if text_rules and not text_match:
                            continue
                        expected_amount = subscription["expected_amount"]
                        expected_currency = subscription["currency"]
                        if expected_amount is not None and (
                                abs(amount) != abs(expected_amount)
                                or transaction.get("currency") != expected_currency
                        ):
                            continue
                        if not text_rules and expected_amount is None:
                            continue
                        period = _period_key(transaction.get("booking_date"), subscription["period"])
                        if period is None:
                            continue
                        candidates[(candidate_id, period)].append((transaction_id, split_id))
                        matched_subscriptions.add(candidate_id)
                    candidate_subscriptions_by_transaction[transaction_id].update(matched_subscriptions)

            unique_subscription_split: dict[int, int] = {}
            ambiguous_transactions: set[str] = set()
            for (subscription_id, _period), rows in candidates.items():
                distinct_transactions = {transaction_id for transaction_id, _ in rows}
                # More than one matching split in a payment is also ambiguous:
                # it is unclear which split represents the recurring charge.
                if len(distinct_transactions) != 1 or len(rows) != 1:
                    ambiguous_transactions.update(distinct_transactions)
                    continue
                transaction_id, split_id = rows[0]
                if len(candidate_subscriptions_by_transaction[transaction_id]) != 1:
                    ambiguous_transactions.add(transaction_id)
                    continue
                unique_subscription_split[split_id] = subscription_id

            for transaction_id, split_id, _amount, subscription_manual in all_splits:
                if subscription_manual == 1:
                    continue
                if split_id in unique_subscription_split:
                    next_state = (1, unique_subscription_split[split_id], 0)
                elif transaction_id in ambiguous_transactions:
                    next_state = (None, None, None)
                else:
                    default = counterparties.get(resolved_by_id.get(transaction_id), {}).get("subscription")
                    next_state = (default, None, 0) if default is not None else (None, None, None)
                current = connection.execute(
                    "SELECT is_subscription, subscription_id, subscription_is_manual "
                    "FROM transaction_splits WHERE id = ?",
                    (split_id,),
                ).fetchone()
                if current != next_state:
                    connection.execute(
                        "UPDATE transaction_splits SET is_subscription = ?, subscription_id = ?, "
                        "subscription_is_manual = ? WHERE id = ?",
                        (*next_state, split_id),
                    )
                    changed.add(transaction_id)

    return len(changed)
