"""SQLite connection helpers and schema initialization for separate databases.

transactions.db contains rebuildable bank data; finance.db contains user data.
All application connections must be opened with connect_database() so SQLite
foreign keys are enforced. SQLite cannot enforce references across databases.
"""

import sqlite3
from contextlib import closing
from pathlib import Path

SQL_DIR = Path(__file__).resolve().parent / "sql"


def connect_database(db_path: str | Path) -> sqlite3.Connection:
    """Open a connection with SQLite foreign-key enforcement enabled.

    Args:
        db_path: Filesystem path to the SQLite database.

    Returns:
        An open SQLite connection with foreign-key checks enabled.
    """
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise RuntimeError("Could not enable SQLite foreign-key enforcement")
        return connection
    except BaseException:
        connection.close()
        raise


def initialize_database(db_path: str | Path, schema_name: str) -> None:
    """Initialize a database using the packaged SQL schema file.

    finance.db is persistent and is initialized only when new. Existing files
    are checked for the current schema and are never migrated in place.

    Args:
        db_path: Filesystem path to the database to initialize.
        schema_name: Supported schema filename: ``transactions.sql`` or ``finance.sql``.

    Raises:
        ValueError: The requested schema filename is not supported.
        RuntimeError: An existing finance database has an incompatible schema.
    """
    if schema_name not in {"transactions.sql", "finance.sql"}:
        raise ValueError(f"Unexpected schema: {schema_name!r}")
    if schema_name == "finance.sql":
        create_finance_tables(db_path)
        return
    _execute_schema(db_path, schema_name)


def _execute_schema(db_path: str | Path, schema_name: str) -> None:
    """Execute a trusted schema file against the specified database.

    Args:
        db_path: Filesystem path to the database to initialize.
        schema_name: Schema filename located in the packaged SQL directory.
    """
    schema = (SQL_DIR / schema_name).read_text(encoding="utf-8")
    with closing(connect_database(db_path)) as connection:
        connection.executescript(schema)


def create_transactions_table(db_path: str | Path) -> None:
    """Initialize the rebuildable transactions database.

    Args:
        db_path: Filesystem path to the transactions' database.
    """
    initialize_database(db_path, "transactions.sql")


def create_finance_tables(db_path: str | Path) -> None:
    """Create a new finance database or accept the current schema.

    Older or unrelated nonempty databases are deliberately rejected: schema
    changes to persistent financial data require a separate data-preserving
    migration plan and must not happen during normal application startup.

    Args:
        db_path: Filesystem path to the persistent finance database.

    Raises:
        RuntimeError: An existing database has an incompatible schema, including
            a missing color lookup table or a subcategory color ID column.
    """
    path = Path(db_path)
    if not path.exists() or path.stat().st_size == 0:
        _execute_schema(path, "finance.sql")
        return

    expected_columns = {
        "categories": {"id", "name"},
        "colors": {"id", "row_hex", "pie_hex", "name"},
        "subcategories": {"id", "category_id", "name", "color_id"},
        "counterparties": {"id", "name", "default_subcategory_id", "default_is_subscription"},
        "counterparties_match_rules": {"id", "counterparty_id", "source_field", "pattern"},
        "subscriptions": {
            "id", "name", "counterparty_id", "billing_period", "expected_amount",
            "currency", "is_active",
        },
        "subscription_match_rules": {"id", "subscription_id", "source_field", "pattern"},
        "transaction_metadata": {"transaction_id", "note", "counterparty_id", "counterparty_is_manual"},
        "transaction_splits": {
            "id", "transaction_id", "amount", "subcategory_id", "subcategory_is_manual",
            "note", "is_subscription", "subscription_id", "subscription_is_manual", "excluded",
        },
    }
    with closing(connect_database(path)) as connection:
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        if not tables:
            initialize_empty = True
        elif tables == set(expected_columns):
            actual_columns = {
                table: {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
                for table in expected_columns
            }
            if actual_columns == expected_columns:
                return
            legacy_columns = {**expected_columns, "subcategories": {"id", "category_id", "name"}}
            if actual_columns == legacy_columns:
                raise RuntimeError(
                    "Existing finance.db is missing subcategory colors. It was left unchanged; "
                    "its schema must be updated separately before restarting."
                )
            raise RuntimeError(
                "Existing finance.db is not the expected finance schema. It was left unchanged; "
                "an explicit, data-preserving migration plan is required."
            )
        else:
            raise RuntimeError(
                "Existing finance.db is not the expected finance schema. It was left unchanged; "
                "an explicit, data-preserving migration plan is required."
            )
    if initialize_empty:
        _execute_schema(path, "finance.sql")
