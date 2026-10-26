"""Creation operations exposed by the Review page's side panel."""

from contextlib import closing
from pathlib import Path

from ...categorization import MATCH_FIELDS
from ...database import connect_database


def _check_rule_duplicate(connection, table: str, owner_id: int | None,
                          source_field: str, pattern: str) -> None:
    """Validate a new match rule against the selected rule collection.

    Args:
        connection: Open finance database connection.
        table: Counterparty or subscription rule table.
        owner_id: Subscription ID for a subscription rule, otherwise ``None``.
        source_field: Imported transaction field used by the rule.
        pattern: Non-empty contains-match pattern.

    Raises:
        ValueError: The field or pattern is invalid or duplicates an existing rule.
    """
    if source_field not in MATCH_FIELDS or not pattern.strip():
        raise ValueError("Choose a match field and enter a non-empty pattern")
    if table == "counterparties_match_rules":
        rows = connection.execute("SELECT source_field, pattern FROM counterparties_match_rules").fetchall()
    else:
        rows = connection.execute(
            "SELECT source_field, pattern FROM subscription_match_rules WHERE subscription_id = ?",
            (owner_id,),
        ).fetchall()
    if any(field == source_field and existing.casefold() == pattern.casefold()
           for field, existing in rows):
        raise ValueError("A case-insensitive rule with that field and pattern already exists")


def create_counterparty(finance_db_path: Path, name: str, subcategory_id: int | None,
                        subscription_default: int | None, source_field: str, pattern: str) -> int:
    """Create a counterparty and, when supplied, its initial match rule.

    Args:
        finance_db_path: Path to the finance database.
        name: Counterparty's display name.
        subcategory_id: Default subcategory ID, if configured.
        subscription_default: Default Yes/No answer, or ``None`` if unset.
        source_field: Imported transaction field for the optional rule.
        pattern: Optional contains-match pattern.

    Returns:
        ID of the newly created counterparty.

    Raises:
        ValueError: The name or optional matching rule is invalid.
    """
    name, pattern = name.strip(), pattern.strip()
    if not name:
        raise ValueError("Enter a counterparty name")
    with closing(connect_database(finance_db_path)) as connection, connection:
        if pattern:
            _check_rule_duplicate(connection, "counterparties_match_rules", None, source_field, pattern)
        cursor = connection.execute(
            "INSERT INTO counterparties(name, default_subcategory_id, default_is_subscription) "
            "VALUES (?, ?, ?)", (name, subcategory_id, subscription_default),
        )
        counterparty_id = cursor.lastrowid
        if counterparty_id is None:
            raise RuntimeError("Counterparty insert did not return an ID")
        if pattern:
            connection.execute(
                "INSERT INTO counterparties_match_rules(counterparty_id, source_field, pattern) "
                "VALUES (?, ?, ?)", (counterparty_id, source_field, pattern),
            )
        return counterparty_id


def create_subscription(finance_db_path: Path, name: str, counterparty_id: int | None,
                        billing_period: str, expected_amount: int | None,
                        currency: str | None, rule: tuple[str, str] | None) -> int:
    """Create a subscription and an optional initial text-matching rule.

    Args:
        finance_db_path: Path to the finance database.
        name: Subscription's display name.
        counterparty_id: Associated counterparty ID, if any.
        billing_period: Recurrence period, either ``monthly`` or ``yearly``.
        expected_amount: Expected amount in signed integer minor units, if known.
        currency: Three-letter currency code paired with the expected amount.
        rule: Optional source-field and pattern pair.

    Returns:
        ID of the newly created subscription.

    Raises:
        ValueError: The name or expected amount/currency pair is invalid.
    """
    name = name.strip()
    if not name:
        raise ValueError("Enter a subscription name")
    if (expected_amount is None) != (currency is None):
        raise ValueError("Expected amount and currency must either both be set or both be blank")
    with closing(connect_database(finance_db_path)) as connection, connection:
        cursor = connection.execute(
            "INSERT INTO subscriptions(name, counterparty_id, billing_period, expected_amount, currency) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, counterparty_id, billing_period, expected_amount, currency),
        )
        subscription_id = cursor.lastrowid
        if subscription_id is None:
            raise RuntimeError("Subscription insert did not return an ID")
        if rule and rule[1].strip():
            _check_rule_duplicate(connection, "subscription_match_rules", subscription_id,
                                  rule[0], rule[1])
            connection.execute(
                "INSERT INTO subscription_match_rules(subscription_id, source_field, pattern) "
                "VALUES (?, ?, ?)", (subscription_id, rule[0], rule[1].strip()),
            )
        return subscription_id
