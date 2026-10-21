"""Parse FIO and TB CSV exports and import their transactions into SQLite."""

import csv
import hashlib
import io
import re
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from transaction_types import translate_transaction_type

IMPORTS_DIR = Path(__file__).resolve().parent.parent / "imports"

FIO_HEADERS = [
    "Dátum", "Objem", "Mena", "Protiúčet", "Kód banky",
    "Správa pre príjemcu", "Poznámka", "Typ", "ID operácie",
    "ID pokynu", "KS", "Názov banky", "Názov protiúčtu",
    "Referencia platiteľa", "SS", "KS", "VS", "SS",
    "Upresnenie - objem", "Upresnenie - mena", "VS", "Zadal",
]

TB_HEADERS = [
    "Dátum spracovania", "Dátum zúčtovania", "Suma", "Mena", "Typ",
    "Predčíslie", "Číslo účtu", "Kód banky", "IBAN",
    "Variabilný symbol", "Špecifický symbol", "Konštantný symbol",
    "Referencia platiteľa", "Informácia pre príjemcu", "Popis",
]

CURRENCY_DECIMALS = {
    "EUR": 2, "USD": 2, "CZK": 2, "GBP": 2,
    "PLN": 2, "CHF": 2, "HUF": 2, "JPY": 0,
}

TRANSACTION_COLUMNS = (
    "source_bank", "booking_date", "value_date", "amount", "currency",
    "transaction_type", "counterparty_name", "counterparty_iban",
    "counterparty_bic", "counterparty_bank_code", "counterparty_bank_name",
    "description", "payer_reference", "payment_message",
    "variable_symbol", "specific_symbol", "constant_symbol",
    "bank_transaction_id", "payment_instruction_id",
    "initiated_by", "amount_related", "currency_related",
)


@dataclass(frozen=True)
class ImportResult:
    """Summarize the outcome of importing one CSV file.

    Attributes:
        filename: Name of the CSV file, without its directory.
        bank: Detected source bank, either "FIO" or "TB".
        rows_imported: Number of transactions inserted during this import.
        skipped: Whether identical file contents were previously imported.
            Defaults to False; skipped files have zero rows_imported.
    """
    filename: str
    bank: str
    rows_imported: int
    skipped: bool = False


def _to_iso_date(value: str | None) -> str | None:
    """Convert a supported date string to ISO 8601 format.

    Args:
        value: Date in DD.MM.YYYY, YYYY-MM-DD, or DD/MM/YYYY format, or None.

    Returns:
        The date as YYYY-MM-DD, or None if value is None.

    Raises:
        ValueError: The value is not a valid date in a supported format.
    """
    if value is None:
        return None
    for date_format in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, date_format).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"Unsupported date: {value!r}")


def _to_minor_units(value: str | None, currency: str | None) -> int | None:
    """Convert an amount to integer currency minor units using Decimal.

    Args:
        value: Amount text, or None. Spaces are removed and decimal commas
            or dots are accepted. If both occur, the last separator is
            treated as the decimal separator.
        currency: Code listed in CURRENCY_DECIMALS. Required when value
            is not None.

    Returns:
        The signed amount in minor units, or None if value is None.

    Raises:
        ValueError: The currency is unsupported or the amount fails
            parsing, finiteness, or precision validation.
    """
    if value is None:
        return None
    if currency is None or currency not in CURRENCY_DECIMALS:
        raise ValueError(f"Unsupported currency: {currency!r}; add it to CURRENCY_DECIMALS")
    normalized = value.replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
    if "," in normalized and "." in normalized:
        if normalized.rfind(",") > normalized.rfind("."):
            normalized = normalized.replace(".", "").replace(",", ".")
        else:
            normalized = normalized.replace(",", "")
    else:
        normalized = normalized.replace(",", ".")

    try:
        amount = Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid amount: {value!r}") from exc

    minor = amount * (10 ** CURRENCY_DECIMALS[currency])
    if not amount.is_finite() or minor != minor.to_integral_value():
        raise ValueError(f"Amount {value!r} has invalid precision for {currency}")
    return int(minor)


def _normalize_domestic_bank_code(value: str | None) -> str | None:
    """Pad a Slovak numeric bank code to four digits.

    Args:
        value: One to four ASCII digits, or None.

    Returns:
        The code padded with leading zeros, or None if value is None.

    Raises:
        ValueError: The value is empty, contains non-ASCII digits or other
            characters, or exceeds four digits.
    """
    if value is None:
        return None
    if not value.isascii() or not value.isdigit() or len(value) > 4:
        raise ValueError(f"Invalid domestic bank code: {value!r}")
    return value.zfill(4)


def _normalize_payer_reference(value: str | None) -> str | None:
    """Normalize missing or placeholder payer references to None.

    Args:
        value: Raw payer reference, or None.

    Returns:
        The reference with surrounding whitespace removed, or None for
        missing or empty text or NOTPROVIDED. The placeholder is matched
        without regard to case or whitespace.
    """
    if value is None:
        return None
    value = value.strip()
    if "".join(value.upper().split()) == "NOTPROVIDED":
        return None
    return value or None


SYMBOLS_IN_REFERENCE = re.compile(r"\??/?VS([0-9]*)/SS([0-9]*)/KS([0-9]*)", re.IGNORECASE)


def _move_symbols_from_payer_reference(record: dict[str, object]) -> dict[str, object]:
    """Move VS/SS/KS tags from a payer reference into symbol columns.

    Only references consisting solely of the three tags are moved.
    Existing symbols must agree after leading zeros are ignored.
    A matching reference is cleared after its symbols are processed.

    Args:
        record: Transaction fields containing payer_reference and the
            variable_symbol, specific_symbol, and constant_symbol fields.
            The dictionary is modified in place.

    Returns:
        The same dictionary, with any matching reference moved.

    Raises:
        ValueError: A reference or compared symbol has an invalid type,
            or an existing symbol conflicts with the reference.
        KeyError: A required record field is missing.
    """
    reference = record["payer_reference"]
    if reference is None:
        return record
    if not isinstance(reference, str):
        raise ValueError("payer_reference must be a string or None")

    match = SYMBOLS_IN_REFERENCE.fullmatch("".join(reference.split()))
    if match is None:
        return record

    columns = ("variable_symbol", "specific_symbol", "constant_symbol")
    for column, value in zip(columns, match.groups()):
        if not value:
            continue
        existing = record[column]
        if existing is None:
            record[column] = value
        elif not isinstance(existing, str):
            raise ValueError(f"{column} must be a string or None")
        elif existing.lstrip("0") != value.lstrip("0"):
            raise ValueError(
                f"{column} {existing!r} conflicts with payer_reference {reference!r}"
            )

    record["payer_reference"] = None
    return record


def _parse_csv(data: bytes, filename: str) -> tuple[str, list[str], list[list[str]]]:
    """Detect and parse a supported bank CSV export.

    FIO uses UTF-8 with an optional BOM and semicolons; TB uses Windows-1250
    and commas. Header matching ignores column order but preserves the
    required number of occurrences of each column name.

    Args:
        data: Raw CSV file contents.
        filename: File name used in format-validation errors.

    Returns:
        A tuple containing the bank label ("FIO" or "TB"), stripped header
        names, and remaining rows as lists of unnormalized field strings.

    Raises:
        ValueError: No supported encoding, delimiter, and header match.
        csv.Error: Strict CSV parsing encounters malformed input.
    """
    for bank, encoding, delimiter, expected_headers in (
            ("FIO", "utf-8-sig", ";", FIO_HEADERS),
            ("TB", "cp1250", ",", TB_HEADERS),
    ):
        try:
            decoded = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        records = list(csv.reader(io.StringIO(decoded, newline=""), delimiter=delimiter, strict=True))
        if not records:
            continue
        header = [column.strip() for column in records[0]]
        if Counter(header) == Counter(expected_headers):
            return bank, header, records[1:]
    raise ValueError(
        f"{filename}: unrecognized CSV headers, delimiter, or encoding. "
        "Expected FIO (UTF-8, ;) or TB (Windows-1250, ,)."
    )


def _parse_transaction_row(bank: str, header: list[str], row: list[str]) -> dict[str, object]:
    """Convert a bank CSV row into normalized transaction fields.

    Dates use ISO format and amounts use integer minor units. TB debit
    amounts are negative and credit amounts are positive.

    Args:
        bank: Source bank label returned by _parse_csv: "FIO" or "TB".
        header: Detected column names, including repeated names.
        row: Raw field values aligned with the header.

    Returns:
        A dictionary containing the fields in TRANSACTION_COLUMNS, with
        missing values represented by None.

    Raises:
        ValueError: The column count is incorrect or a date, amount,
            currency, bank code, or transaction type fails validation.
    """
    if len(row) != len(header):
        raise ValueError(f"Expected {len(header)} columns; found {len(row)}")

    positions: dict[str, list[int]] = defaultdict(list)
    for index, name in enumerate(header):
        positions[name].append(index)

    def get_field(column_name: str, occurrence: int = 1) -> str | None:
        """Read a stripped field from the current row.

        Args:
            column_name: Header name to look up.
            occurrence: One-based occurrence of a repeated header name.

        Returns:
            The stripped field value, or None if it is empty.

        Raises:
            IndexError: The requested column or occurrence is absent.
        """
        value = row[positions[column_name][occurrence - 1]].strip()
        return value or None

    if bank == "FIO":
        currency = get_field("Mena")
        currency_related = get_field("Upresnenie - mena")
        return {
            "source_bank": "FIO",
            "booking_date": _to_iso_date(get_field("Dátum")),
            "value_date": None,
            "amount": _to_minor_units(get_field("Objem"), currency),
            "currency": currency,
            "transaction_type": translate_transaction_type("FIO", get_field("Typ")).value,
            "counterparty_name": get_field("Názov protiúčtu"),
            "counterparty_iban": get_field("Protiúčet"),
            "counterparty_bic": get_field("Kód banky"),
            "counterparty_bank_code": None,
            "counterparty_bank_name": get_field("Názov banky"),
            "description": get_field("Poznámka"),
            "payer_reference": _normalize_payer_reference(get_field("Referencia platiteľa")),
            "payment_message": get_field("Správa pre príjemcu"),
            "variable_symbol": get_field("VS", 1),
            "specific_symbol": get_field("SS", 1),
            "constant_symbol": get_field("KS", 1),
            "bank_transaction_id": get_field("ID operácie"),
            "payment_instruction_id": get_field("ID pokynu"),
            "initiated_by": get_field("Zadal"),
            "amount_related": _to_minor_units(get_field("Upresnenie - objem"), currency_related),
            "currency_related": currency_related,
        }

    currency = get_field("Mena")
    transaction_type = get_field("Typ")
    amount = _to_minor_units(get_field("Suma"), currency)

    if transaction_type == "Debet":
        amount = -abs(amount) if amount is not None else None
    elif transaction_type == "Kredit":
        amount = abs(amount) if amount is not None else None
    else:
        raise ValueError(f"Unknown TB transaction type: {transaction_type!r}")

    return {
        "source_bank": "TB",
        "booking_date": _to_iso_date(get_field("Dátum spracovania")),
        "value_date": _to_iso_date(get_field("Dátum zúčtovania")),
        "amount": amount,
        "currency": currency,
        "transaction_type": translate_transaction_type("TB", transaction_type).value,
        "counterparty_name": None,
        "counterparty_iban": get_field("IBAN"),
        "counterparty_bic": None,
        "counterparty_bank_code": _normalize_domestic_bank_code(get_field("Kód banky")),
        "counterparty_bank_name": None,
        "description": get_field("Popis"),
        "payer_reference": _normalize_payer_reference(get_field("Referencia platiteľa")),
        "payment_message": get_field("Informácia pre príjemcu"),
        "variable_symbol": get_field("Variabilný symbol"),
        "specific_symbol": get_field("Špecifický symbol"),
        "constant_symbol": get_field("Konštantný symbol"),
        "bank_transaction_id": None,
        "payment_instruction_id": None,
        "initiated_by": None,
        "amount_related": None,
        "currency_related": None,
    }


def import_csv_files(db_path: str | Path, csv_dir: str | Path = IMPORTS_DIR) -> list[ImportResult]:
    """Import new CSV files atomically and skip previously imported contents.

    Files are processed in case-insensitive filename order. Each file's
    transactions and import-log entry commit together; a failure rolls
    back that file while earlier successful files remain committed.
    Empty rows are ignored. SHA-256 hashes identify previously imported
    file contents; overlapping transactions in different exports are
    not deduplicated.

    Args:
        db_path: SQLite database path with an existing transactions table.
            The imported_files tracking table is created if needed.
        csv_dir: Directory containing CSV files, scanned without recursion
            and created if missing. Defaults to IMPORTS_DIR.

    Returns:
        One ImportResult per CSV file in processing order. Skipped files
        report zero imported rows. Returns an empty list if no CSVs exist.

    Raises:
        ValueError: A CSV format is unrecognized, or row validation or
            insertion fails. Row errors include the filename and row number.
        csv.Error: Strict CSV parsing encounters malformed input.
        OSError: Directory creation, listing, or file reading fails.
        sqlite3.Error: A database operation outside row insertion fails.
    """
    db_path = Path(db_path)
    csv_dir = Path(csv_dir)
    csv_dir.mkdir(parents=True, exist_ok=True)
    csv_files = sorted(
        (p for p in csv_dir.iterdir() if p.is_file() and p.suffix.lower() == ".csv"),
        key=lambda p: p.name.casefold(),
    )

    results: list[ImportResult] = []
    columns_sql = ", ".join(TRANSACTION_COLUMNS)
    placeholders = ", ".join("?" for _ in TRANSACTION_COLUMNS)
    insert_sql = f"INSERT INTO transactions ({columns_sql}) VALUES ({placeholders})"

    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS imported_files (
                sha256 TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                source_bank TEXT NOT NULL,
                rows_imported INTEGER NOT NULL,
                imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        connection.commit()

        for path in csv_files:
            data = path.read_bytes()
            file_hash = hashlib.sha256(data).hexdigest()
            with connection:  # commit/rollback each file together with its import-log entry
                previous = connection.execute(
                    "SELECT source_bank FROM imported_files WHERE sha256 = ?", (file_hash,)
                ).fetchone()
                if previous:
                    results.append(ImportResult(path.name, previous[0], 0, skipped=True))
                    continue

                bank, header, rows = _parse_csv(data, path.name)
                count = 0
                for row_number, row in enumerate(rows, start=2):
                    if not row or all(not cell.strip() for cell in row):
                        continue
                    try:
                        record = _move_symbols_from_payer_reference(_parse_transaction_row(bank, header, row))
                        connection.execute(
                            insert_sql, tuple(record[col] for col in TRANSACTION_COLUMNS)
                        )
                    except (ValueError, sqlite3.Error) as exc:
                        raise ValueError(f"{path.name}, row {row_number}: {exc}") from exc
                    count += 1

                connection.execute(
                    "INSERT INTO imported_files (sha256, filename, source_bank, rows_imported) "
                    "VALUES (?, ?, ?, ?)",
                    (file_hash, path.name, bank, count),
                )
            results.append(ImportResult(path.name, bank, count))

    return results
