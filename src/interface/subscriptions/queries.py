"""Subscription-specific queries and display calculations."""

from contextlib import closing
from pathlib import Path

from ...database import connect_database


def subscription_categories(transaction_db_path: Path, finance_db_path: Path) -> dict[int, str]:
    """Derive each subscription's displayed category from its latest payment.

    Args:
        transaction_db_path: Path to the imported transactions' database.
        finance_db_path: Path to the finance database containing subscription links.

    Returns:
        Subscription IDs mapped to category and subcategory labels from their
        latest linked payment.
    """
    return {subscription_id: label for subscription_id, (label, _) in
            subscription_category_details(transaction_db_path, finance_db_path).items()}


def subscription_category_details(transaction_db_path: Path, finance_db_path: Path) -> dict[
    int, tuple[str, str | None]]:
    """Return latest-payment category labels and their shared subcategory color.

    Args:
        transaction_db_path: Database containing payment booking dates.
        finance_db_path: Database containing subscription splits and subcategories.

    Returns:
        Labels and colors by subscription ID. Payments with mixed subcategory
        colors or an uncolored split have no shared row color.
    """
    with closing(connect_database(finance_db_path)) as connection:
        rows = connection.execute(
            "SELECT sp.subscription_id, sp.transaction_id, c.name, sc.name, colors.row_hex "
            "FROM transaction_splits AS sp "
            "LEFT JOIN subcategories AS sc ON sc.id = sp.subcategory_id "
            "LEFT JOIN colors ON colors.id = sc.color_id "
            "LEFT JOIN categories AS c ON c.id = sc.category_id "
            "WHERE sp.subscription_id IS NOT NULL"
        ).fetchall()
    categories_by_transaction: dict[int, dict[str, set[str]]] = {}
    colors_by_transaction: dict[int, dict[str, set[str | None]]] = {}
    transaction_ids: set[str] = set()
    for subscription_id, transaction_id, category, subcategory, color in rows:
        transaction_ids.add(transaction_id)
        payments = categories_by_transaction.setdefault(subscription_id, {})
        payments.setdefault(transaction_id, set())
        colors_by_transaction.setdefault(subscription_id, {}).setdefault(transaction_id, set()).add(color)
        if category and subcategory:
            payments[transaction_id].add(f"{category} / {subcategory}")

    booking_dates: dict[str, str] = {}
    if transaction_ids:
        with closing(connect_database(transaction_db_path)) as connection:
            for transaction_id, booking_date in connection.execute(
                    "SELECT id, booking_date FROM transactions"
            ):
                if transaction_id in transaction_ids:
                    booking_dates[transaction_id] = booking_date or ""

    result = {}
    for subscription_id, payments in categories_by_transaction.items():
        latest = max(payments, key=lambda key: (booking_dates.get(key, ""), key))
        colors = colors_by_transaction[subscription_id][latest]
        color = next(iter(colors)) if len(colors) == 1 else None
        result[subscription_id] = (", ".join(sorted(payments[latest])) or "—", color)
    return result
