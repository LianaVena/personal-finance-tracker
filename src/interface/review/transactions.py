"""Transaction review queries and persistence operations."""

from contextlib import closing
from datetime import date
from pathlib import Path

from ...database import connect_database
from ...transaction_types import TRANSACTION_TYPE_LABELS


def format_transaction_field(column_name: str, value, transaction: dict) -> tuple[str, str]:
    """Return a readable label and display value for an imported field.

    Args:
        column_name: Name of the imported transaction column.
        value: Field value to display.
        transaction: Full transaction mapping used for currency context.

    Returns:
        A pair containing the display label and formatted value.
    """
    from ..common import format_money

    label = column_name.replace("_", " ").capitalize()
    if column_name == "amount":
        return label, format_money(value, transaction.get("currency"))
    if column_name == "amount_related":
        return label, format_money(value, transaction.get("currency_related"))
    if column_name == "source_bank":
        return label, {"TB": "Tatra Banka", "FIO": "Fio"}.get(value, str(value))
    if column_name == "transaction_type":
        return label, TRANSACTION_TYPE_LABELS.get(value, str(value))
    if column_name.endswith("date"):
        try:
            value = date.fromisoformat(value).strftime("%d.%m.%Y")
        except (TypeError, ValueError):
            pass
    return label, str(value)


def review_transactions(transaction_db_path: Path, finance_db_path: Path) -> list[dict]:
    """Join transactions to finance metadata, splits, and review requirements.

    Args:
        transaction_db_path: Path to the imported transactions' database.
        finance_db_path: Path to the finance database.

    Returns:
        Transactions ordered newest first with their metadata, splits, and
        outstanding review reasons.

    Raises:
        RuntimeError: The transaction query returns no column metadata.
    """
    with closing(connect_database(transaction_db_path)) as connection:
        cursor = connection.execute("SELECT * FROM transactions ORDER BY booking_date DESC, id DESC")
        description = cursor.description
        if description is None:
            raise RuntimeError("Transaction query returned no column metadata")
        columns = [column[0] for column in description]
        transactions = [dict(zip(columns, row)) for row in cursor.fetchall()]

    with closing(connect_database(finance_db_path)) as connection:
        metadata = {
            row[0]: {"note": row[1], "counterparty_id": row[2], "counterparty_is_manual": row[3]}
            for row in connection.execute(
                "SELECT transaction_id, note, counterparty_id, counterparty_is_manual "
                "FROM transaction_metadata"
            )
        }
        split_rows = connection.execute(
            "SELECT sp.id, sp.transaction_id, sp.amount, sp.subcategory_id, sp.subcategory_is_manual, "
            "sp.note, sp.is_subscription, sp.subscription_id, sp.subscription_is_manual, sp.excluded, "
            "sc.name, ca.name, su.name "
            "FROM transaction_splits AS sp "
            "LEFT JOIN subcategories AS sc ON sc.id = sp.subcategory_id "
            "LEFT JOIN categories AS ca ON ca.id = sc.category_id "
            "LEFT JOIN subscriptions AS su ON su.id = sp.subscription_id "
            "ORDER BY sp.id"
        ).fetchall()

    split_keys = ("id", "transaction_id", "amount", "subcategory_id", "subcategory_is_manual",
                  "note", "is_subscription", "subscription_id", "subscription_is_manual", "excluded",
                  "subcategory_name", "category_name", "subscription_name")
    splits_by_id: dict[str, list[dict]] = {}
    for row in split_rows:
        split = dict(zip(split_keys, row))
        splits_by_id.setdefault(split["transaction_id"], []).append(split)

    result = []
    for transaction in transactions:
        transaction_id = transaction["id"]
        meta = metadata.get(transaction_id)
        splits = splits_by_id.get(transaction_id, [])
        transaction.update(meta or {"note": None, "counterparty_id": None,
                                    "counterparty_is_manual": None})
        transaction["splits"] = splits
        reasons = []
        if meta is None:
            reasons.append("Finance metadata is missing")
        if transaction["amount"] == 0:
            reasons.append("Zero-amount transaction needs review")
        elif not splits:
            reasons.append("No split exists")
        if sum(split["amount"] for split in splits) != transaction["amount"]:
            reasons.append("Split amounts do not equal the transaction amount")
        for split in splits:
            if split["excluded"]:
                continue
            if split["subcategory_id"] is None:
                reasons.append("A split needs a subcategory")
            if split["is_subscription"] is None:
                reasons.append("A split needs a subscription answer")
            elif split["is_subscription"] == 1 and split["subscription_id"] is None:
                reasons.append("A subscription split needs a linked subscription")
        transaction["review_reasons"] = list(dict.fromkeys(reasons))
        result.append(transaction)
    return result


def save_counterparty(finance_db_path: Path, transaction_id: str, counterparty_id: int | None) -> None:
    """Save a user's counterparty assignment for one transaction.

    Args:
        finance_db_path: Path to the finance database.
        transaction_id: Stable hash ID of the transaction.
        counterparty_id: Selected counterparty ID, or ``None`` to clear it.
    """
    manual = 1 if counterparty_id is not None else None
    with closing(connect_database(finance_db_path)) as connection, connection:
        connection.execute(
            "INSERT INTO transaction_metadata(transaction_id, counterparty_id, counterparty_is_manual) "
            "VALUES (?, ?, ?) ON CONFLICT(transaction_id) DO UPDATE SET "
            "counterparty_id = excluded.counterparty_id, counterparty_is_manual = excluded.counterparty_is_manual",
            (transaction_id, counterparty_id, manual),
        )


def save_transaction_note(finance_db_path: Path, transaction_id: str, note: str | None) -> None:
    """Save or clear the note shared by all splits of a transaction.

    Args:
        finance_db_path: Path to the finance database.
        transaction_id: Stable hash ID of the transaction.
        note: Note text, or ``None`` to clear the note.
    """
    with closing(connect_database(finance_db_path)) as connection, connection:
        connection.execute(
            "INSERT INTO transaction_metadata(transaction_id, note) VALUES (?, ?) "
            "ON CONFLICT(transaction_id) DO UPDATE SET note = excluded.note", (transaction_id, note),
        )


def save_subcategory(finance_db_path: Path, split_id: int, subcategory_id: int | None) -> None:
    """Save a manual subcategory choice on one transaction split.

    Args:
        finance_db_path: Path to the finance database.
        split_id: ID of the transaction split to update.
        subcategory_id: Selected subcategory ID, or ``None`` to clear it.
    """
    with closing(connect_database(finance_db_path)) as connection, connection:
        connection.execute(
            "UPDATE transaction_splits SET subcategory_id = ?, subcategory_is_manual = ? WHERE id = ?",
            (subcategory_id, 1 if subcategory_id is not None else None, split_id),
        )


def save_split_amount(finance_db_path: Path, split_id: int, amount: int) -> None:
    """Save a nonzero signed amount for one transaction split.

    Args:
        finance_db_path: Path to the finance database.
        split_id: ID of the transaction split to update.
        amount: New signed amount in integer minor units.

    Raises:
        ValueError: The amount is zero.
    """
    if amount == 0:
        raise ValueError("A split amount cannot be zero")
    with closing(connect_database(finance_db_path)) as connection, connection:
        connection.execute("UPDATE transaction_splits SET amount = ? WHERE id = ?", (amount, split_id))


def save_split_note(finance_db_path: Path, split_id: int, note: str | None) -> None:
    """Save or clear the note attached to one transaction split.

    Args:
        finance_db_path: Path to the finance database.
        split_id: ID of the transaction split to update.
        note: Note text, or ``None`` to clear the note.
    """
    with closing(connect_database(finance_db_path)) as connection, connection:
        connection.execute("UPDATE transaction_splits SET note = ? WHERE id = ?", (note, split_id))


def save_subscription_decision(finance_db_path: Path, split_id: int, decision: str,
                               subscription_id: int | None = None) -> None:
    """Save a manual yes, no, or unknown subscription decision for a split.

    Args:
        finance_db_path: Path to the finance database.
        split_id: ID of the transaction split to update.
        decision: ``unknown``, ``no``, or ``yes``.
        subscription_id: Linked subscription ID for a Yes answer, if selected.

    Raises:
        ValueError: The decision is not one of the supported values.
    """
    states = {"unknown": (None, None, None), "no": (0, None, 1),
              "yes": (1, subscription_id, 1)}
    if decision not in states:
        raise ValueError("Unknown subscription decision")
    with closing(connect_database(finance_db_path)) as connection, connection:
        connection.execute(
            "UPDATE transaction_splits SET is_subscription = ?, subscription_id = ?, "
            "subscription_is_manual = ? WHERE id = ?", (*states[decision], split_id),
        )


def save_excluded(finance_db_path: Path, split_id: int, excluded: bool) -> None:
    """Set whether a split is excluded from spending summaries.

    Args:
        finance_db_path: Path to the finance database.
        split_id: ID of the transaction split to update.
        excluded: Whether the split is excluded from spending totals.
    """
    with closing(connect_database(finance_db_path)) as connection, connection:
        connection.execute("UPDATE transaction_splits SET excluded = ? WHERE id = ?", (int(excluded), split_id))


def add_split(finance_db_path: Path, transaction_id: str) -> None:
    """Add a one-cent split while preserving the current signed total.

    Args:
        finance_db_path: Path to the finance database.
        transaction_id: Stable hash ID of the transaction.

    Raises:
        ValueError: No initial split exists or no amount is available to split.
    """
    with closing(connect_database(finance_db_path)) as connection, connection:
        rows = connection.execute(
            "SELECT id, amount FROM transaction_splits WHERE transaction_id = ? ORDER BY id",
            (transaction_id,),
        ).fetchall()
        if not rows:
            raise ValueError("A split cannot be added before the initial split exists")
        sign = 1 if rows[0][1] > 0 else -1
        target = next(((split_id, amount) for split_id, amount in rows if amount * sign > 1), None)
        if target is None:
            raise ValueError("At least two cents are needed to create another non-zero split")
        split_id, amount = target
        connection.execute("UPDATE transaction_splits SET amount = ? WHERE id = ?", (amount - sign, split_id))
        connection.execute("INSERT INTO transaction_splits(transaction_id, amount) VALUES (?, ?)",
                           (transaction_id, sign))


def delete_split(finance_db_path: Path, transaction_id: str, split_id: int) -> None:
    """Delete a split and merge its amount into another split safely.

    Args:
        finance_db_path: Path to the finance database.
        transaction_id: Stable hash ID of the parent transaction.
        split_id: ID of the split to delete.

    Raises:
        ValueError: The transaction would have no split, the split does not
            belong to it, or the merge violates signed amount constraints.
    """
    with closing(connect_database(finance_db_path)) as connection, connection:
        rows: list[tuple[int, int]] = connection.execute(
            "SELECT id, amount FROM transaction_splits WHERE transaction_id = ? ORDER BY id",
            (transaction_id,),
        ).fetchall()
        if len(rows) <= 1:
            raise ValueError("A transaction must keep at least one split")
        deleted = next((row for row in rows if row[0] == split_id), None)
        if deleted is None:
            raise ValueError("Split does not belong to this transaction")
        remaining = next(row for row in rows if row[0] != split_id)
        merged_amount = remaining[1] + deleted[1]
        if merged_amount == 0 or merged_amount * remaining[1] < 0:
            raise ValueError("Deleting this split would violate the signed split amounts")
        connection.execute("UPDATE transaction_splits SET amount = ? WHERE id = ?",
                           (merged_amount, remaining[0]))
        connection.execute("DELETE FROM transaction_splits WHERE id = ?", (split_id,))
