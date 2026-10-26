"""Persistence operations for Manage-page rules and counterparty defaults."""

import sqlite3
from contextlib import closing
from pathlib import Path

from ...categorization import MATCH_FIELDS
from ...database import connect_database


def save_counterparty_defaults(finance_db_path: Path, counterparty_id: int,
                               subcategory_id: int | None = None,
                               subscription_default: int | None = None) -> None:
    """Persist a counterparty's default subcategory and subscription answer.

    Args:
        finance_db_path: Path to the finance database.
        counterparty_id: ID of the counterparty to update.
        subcategory_id: Default subcategory ID, or ``None`` if unset.
        subscription_default: Default Yes/No answer, or ``None`` if unset.
    """
    with closing(connect_database(finance_db_path)) as connection, connection:
        connection.execute(
            "UPDATE counterparties SET default_subcategory_id = ?, default_is_subscription = ? WHERE id = ?",
            (subcategory_id, subscription_default, counterparty_id),
        )


def _validate_rule_duplicate(connection: sqlite3.Connection, table: str,
                             owner_id: int | None, source_field: str,
                             pattern: str, rule_id: int | None = None) -> None:
    """Reject invalid fields, empty patterns, and case-folded duplicate rules.

    Args:
        connection: Open finance database connection.
        table: Supported counterparty or subscription rule table.
        owner_id: Rule owner's ID for subscription rules.
        source_field: Transaction field used by the rule.
        pattern: Text pattern used by the rule.
        rule_id: Rule being updated, if any, so it is excluded from checking.

    Raises:
        ValueError: The table, field, or pattern is invalid or duplicates a rule.
    """
    if source_field not in MATCH_FIELDS or not pattern.strip():
        raise ValueError("Choose a match field and enter a non-empty pattern")
    if table == "counterparties_match_rules":
        rows = connection.execute(
            "SELECT id, source_field, pattern FROM counterparties_match_rules WHERE id <> ?",
            (rule_id or -1,),
        ).fetchall()
    elif table == "subscription_match_rules":
        rows = connection.execute(
            "SELECT id, source_field, pattern FROM subscription_match_rules "
            "WHERE subscription_id = ? AND id <> ?", (owner_id, rule_id or -1),
        ).fetchall()
    else:
        raise ValueError("Unexpected match-rule table")
    if any(field == source_field and value.casefold() == pattern.casefold()
           for _, field, value in rows):
        raise ValueError("A case-insensitive rule with that field and pattern already exists")


def add_rule(finance_db_path: Path, table: str, owner_column: str, owner_id: int,
             source_field: str, pattern: str) -> None:
    """Validate and insert a counterparty or subscription match rule.

    Args:
        finance_db_path: Path to the finance database.
        table: Counterparty or subscription rule table.
        owner_column: Foreign-key column identifying the rule owner.
        owner_id: Counterparty or subscription ID.
        source_field: Imported transaction field to inspect.
        pattern: Non-empty contains-match pattern.

    Raises:
        ValueError: The owner mapping or rule contents are invalid or duplicate.
    """
    if (table, owner_column) not in {
        ("counterparties_match_rules", "counterparty_id"),
        ("subscription_match_rules", "subscription_id"),
    }:
        raise ValueError("Unexpected match-rule table")
    pattern = pattern.strip()
    with closing(connect_database(finance_db_path)) as connection, connection:
        _validate_rule_duplicate(connection, table, owner_id, source_field, pattern)
        connection.execute(
            f"INSERT INTO {table}({owner_column}, source_field, pattern) VALUES (?, ?, ?)",
            (owner_id, source_field, pattern),
        )


def update_rule(finance_db_path: Path, table: str, owner_column: str, owner_id: int,
                rule_id: int, source_field: str, pattern: str) -> None:
    """Validate and update a match rule owned by the selected item.

    Args:
        finance_db_path: Path to the finance database.
        table: Counterparty or subscription rule table.
        owner_column: Foreign-key column identifying the rule owner.
        owner_id: Counterparty or subscription ID.
        rule_id: ID of the rule to update.
        source_field: Imported transaction field to inspect.
        pattern: Non-empty contains-match pattern.

    Raises:
        ValueError: The owner mapping or rule contents are invalid or duplicate.
    """
    if (table, owner_column) not in {
        ("counterparties_match_rules", "counterparty_id"),
        ("subscription_match_rules", "subscription_id"),
    }:
        raise ValueError("Unexpected match-rule table")
    pattern = pattern.strip()
    with closing(connect_database(finance_db_path)) as connection, connection:
        _validate_rule_duplicate(connection, table, owner_id, source_field, pattern, rule_id)
        connection.execute(
            f"UPDATE {table} SET source_field = ?, pattern = ? WHERE id = ? AND {owner_column} = ?",
            (source_field, pattern, rule_id, owner_id),
        )


def delete_rule(finance_db_path: Path, table: str, rule_id: int) -> None:
    """Delete a rule from one of the supported match-rule tables.

    Args:
        finance_db_path: Path to the finance database.
        table: Counterparty or subscription rule table.
        rule_id: ID of the rule to delete.

    Raises:
        ValueError: The table is not a supported match-rule table.
    """
    if table not in {"counterparties_match_rules", "subscription_match_rules"}:
        raise ValueError("Unexpected match-rule table")
    with closing(connect_database(finance_db_path)) as connection, connection:
        connection.execute(f"DELETE FROM {table} WHERE id = ?", (rule_id,))
