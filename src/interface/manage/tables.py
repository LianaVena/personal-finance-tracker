"""Read-only data queries used by the Manage and Review panels."""

from contextlib import closing
from pathlib import Path

from ...database import connect_database


def categories(finance_db_path: Path) -> dict[int, str]:
    """Load categories keyed by ID in case-insensitive display order.

    Args:
        finance_db_path: Path to the finance database.

    Returns:
        Category IDs mapped to names in display order.
    """
    with closing(connect_database(finance_db_path)) as connection:
        rows = connection.execute("SELECT id, name FROM categories ORDER BY name COLLATE NOCASE")
        return {row[0]: row[1] for row in rows}


def subcategories(finance_db_path: Path) -> dict[int | None, str]:
    """Load subcategories with their parent names and an Unassigned option.

    Args:
        finance_db_path: Path to the finance database.

    Returns:
        Subcategory IDs mapped to ``Category / Subcategory`` labels, with
        ``None`` mapped to ``Unassigned``.
    """
    with closing(connect_database(finance_db_path)) as connection:
        rows = connection.execute(
            "SELECT s.id, c.name, s.name FROM subcategories AS s "
            "JOIN categories AS c ON c.id = s.category_id "
            "ORDER BY c.name COLLATE NOCASE, s.name COLLATE NOCASE"
        ).fetchall()
    return {None: "Unassigned", **{row[0]: f"{row[1]} / {row[2]}" for row in rows}}


def counterparties(finance_db_path: Path) -> list[dict]:
    """Load counterparties with their default categorization settings.

    Args:
        finance_db_path: Path to the finance database.

    Returns:
        Counterparty records ordered by name.
    """
    with closing(connect_database(finance_db_path)) as connection:
        rows = connection.execute(
            "SELECT id, name, default_subcategory_id, default_is_subscription "
            "FROM counterparties ORDER BY name COLLATE NOCASE"
        ).fetchall()
    keys = ("id", "name", "default_subcategory_id", "default_is_subscription")
    return [dict(zip(keys, row)) for row in rows]


def subscriptions(finance_db_path: Path) -> list[dict]:
    """Load subscriptions together with the display name of each counterparty.

    Args:
        finance_db_path: Path to the finance database.

    Returns:
        Subscription records ordered by name.
    """
    with closing(connect_database(finance_db_path)) as connection:
        rows = connection.execute(
            "SELECT s.id, s.name, s.counterparty_id, c.name, s.billing_period, "
            "s.expected_amount, s.currency, s.is_active "
            "FROM subscriptions AS s LEFT JOIN counterparties AS c ON c.id = s.counterparty_id "
            "ORDER BY s.name COLLATE NOCASE"
        ).fetchall()
    keys = ("id", "name", "counterparty_id", "counterparty_name", "billing_period",
            "expected_amount", "currency", "is_active")
    return [dict(zip(keys, row)) for row in rows]


def rules(finance_db_path: Path, table: str, owner_column: str, owner_id: int) -> list[tuple]:
    """Load validated match rules for one counterparty or subscription.

    Args:
        finance_db_path: Path to the finance database.
        table: Counterparty or subscription rule table.
        owner_column: Foreign-key column identifying the rule owner.
        owner_id: Counterparty or subscription ID.

    Returns:
        Rule rows containing ID, source field, and pattern.

    Raises:
        ValueError: The table and owner column are not a supported pair.
    """
    if (table, owner_column) not in {
        ("counterparties_match_rules", "counterparty_id"),
        ("subscription_match_rules", "subscription_id"),
    }:
        raise ValueError("Unexpected match-rule table")
    with closing(connect_database(finance_db_path)) as connection:
        return connection.execute(
            f"SELECT id, source_field, pattern FROM {table} WHERE {owner_column} = ? "
            "ORDER BY source_field, pattern COLLATE NOCASE", (owner_id,),
        ).fetchall()
