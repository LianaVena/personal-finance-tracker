"""Synthetic CSV builders and temporary-database fixtures for the tests."""

import csv
import io
import sqlite3
import tempfile
import unittest
from collections import defaultdict
from contextlib import closing
from pathlib import Path

from src.database import create_transactions_table
from src.importer import TB_HEADERS, import_csv_files, FIO_HEADERS


def tb_row(*, date="01.10.2026", value_date="02.10.2026", amount="10,00", currency="EUR",
           tx_type="Kredit", prefix="", account="", bank_code="1100",
           iban="SK3111000000001234567890", vs="", ss="", ks="",
           payer_reference="", message="", description="") -> list[str]:
    """Generate one Tatra banka CSV row in TB_HEADERS column order.

    Args:
        date: Booking date string. Defaults to "01.10.2026".
        value_date: Value date string. Defaults to "02.10.2026".
        amount: Amount text with decimal comma. Defaults to "10,00".
        currency: Three-letter currency code. Defaults to "EUR".
        tx_type: Transaction type label. Defaults to "Kredit".
        prefix: Account number prefix. Defaults to "".
        account: Account number. Defaults to "".
        bank_code: Bank identifier code. Defaults to "1100".
        iban: Account IBAN. Defaults to "SK3111000000001234567890".
        vs: Variable symbol. Defaults to "".
        ss: Specific symbol. Defaults to "".
        ks: Constant symbol. Defaults to "".
        payer_reference: Payer reference string. Defaults to "".
        message: Information for recipient. Defaults to "".
        description: Transaction description. Defaults to "".

    Returns:
        List of strings representing a single Tatra banka CSV row.
    """
    row = [date, value_date, amount, currency, tx_type, prefix, account, bank_code, iban,
           vs, ss, ks, payer_reference, message, description]
    assert len(row) == len(TB_HEADERS)
    return row


FIO_DEFAULTS = {
    "Dátum": "01.10.2026",
    "Objem": "-10,00",
    "Mena": "EUR",
    "Typ": "Bezhotovostná platba",
}


def fio_row(values: dict | None = None) -> list[str]:
    """Generate one FIO CSV row in FIO_HEADERS column order.

    Args:
        values: Mapping of header names to field values. FIO repeats the
            VS/SS/KS headers, so use ("VS", 2) for the second occurrence; a
            plain "VS" represents the first occurrence. Defaults to None.

    Returns:
        List of strings representing a single FIO CSV row.
    """
    positions: dict[str, list[int]] = defaultdict(list)
    for index, name in enumerate(FIO_HEADERS):
        positions[name].append(index)

    row = [""] * len(FIO_HEADERS)
    for key, value in {**FIO_DEFAULTS, **(values or {})}.items():
        name, occurrence = key if isinstance(key, tuple) else (key, 1)
        row[positions[name][occurrence - 1]] = value
    return row


def _csv_text(headers, rows, delimiter) -> str:
    """Format headers and rows into a CSV string.

    Args:
        headers: Sequence of column header names.
        rows: Sequence of rows, each containing string values.
        delimiter: Field delimiter character.

    Returns:
        Formatted CSV text content.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=delimiter)
    writer.writerow(headers)
    writer.writerows(rows)
    return buffer.getvalue()


def fio_bytes(rows) -> bytes:
    """Encode FIO CSV rows as UTF-8 with BOM and semicolon delimiter.

    Args:
        rows: Sequence of FIO CSV row values.

    Returns:
        Encoded bytes representing the CSV file content.
    """
    return _csv_text(FIO_HEADERS, rows, ";").encode("utf-8-sig")


def tb_bytes(rows) -> bytes:
    """Encode Tatra banka CSV rows as Windows-1250 with comma delimiter.

    Args:
        rows: Sequence of Tatra banka CSV row values.

    Returns:
        Encoded bytes representing the CSV file content.
    """
    return _csv_text(TB_HEADERS, rows, ",").encode("cp1250")


def write_fio_csv(path: Path, rows) -> Path:
    """Write FIO CSV rows to a file.

    Args:
        path: Target file path.
        rows: Sequence of FIO CSV row values.

    Returns:
        The path of the written file.
    """
    path.write_bytes(fio_bytes(rows))
    return path


def write_tb_csv(path: Path, rows) -> Path:
    """Write Tatra banka CSV rows to a file.

    Args:
        path: Target file path.
        rows: Sequence of Tatra banka CSV row values.

    Returns:
        The path of the written file.
    """
    path.write_bytes(tb_bytes(rows))
    return path


class BaseDatabaseTestCase(unittest.TestCase):
    """Gives each test a throwaway database (with the transactions table) and an imports dir."""

    def setUp(self):
        """Set up an isolated database, imports directory, and schema."""
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp_dir = Path(temp.name)
        self.db_path = self.temp_dir / "transactions.db"
        self.csv_dir = self.temp_dir / "imports"
        self.csv_dir.mkdir()
        create_transactions_table(self.db_path)

    def query(self, sql: str, params=()) -> list[dict]:
        """Execute a SQL query against the test database.

        Args:
            sql: SQL statement to execute.
            params: Parameters for SQL query placeholders. Defaults to ().

        Returns:
            List of row dictionaries mapping column names to values.
        """
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(sql, params)]

    def count_transactions(self) -> int:
        """Count the total number of records in the transactions table.

        Returns:
            Total transaction count as an integer.
        """
        return self.query("SELECT COUNT(*) AS n FROM transactions")[0]["n"]

    def run_import(self):
        """Run CSV import against the temporary database and imports directory.

        Returns:
            List of ImportResult objects for processed files.
        """
        return import_csv_files(self.db_path, self.csv_dir)
