"""Database schema initialization and management for transactions."""

import sqlite3
from pathlib import Path


def create_transactions_table(db_path: str | Path) -> None:
    """Create the transactions table and indexes if they do not exist.

    Initializes the SQLite schema supporting imported banking transactions
    from FIO and Tatra Banka (TB), along with indexes on booking_date
    and source_bank.

    Args:
        db_path: Path to the SQLite database file as a string or Path object.
    """
    connection = sqlite3.connect(db_path)
    try:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_bank TEXT NOT NULL CHECK (source_bank IN ('FIO', 'TB')),
                
                booking_date TEXT NOT NULL,    -- FIO: Dátum | TB: Dátum spracovania
                value_date TEXT,               -- FIO: —     | TB: Dátum zúčtovania
                amount INTEGER NOT NULL,       -- FIO: Objem | TB: Suma
                currency TEXT NOT NULL,        -- FIO: Mena  | TB: Mena
                transaction_type TEXT,         -- FIO: Typ   | TB: Typ (mapped to TransactionType)

                counterparty_name TEXT,         -- FIO: Názov protiúčtu | TB: —
                counterparty_iban TEXT,         -- FIO: Protiúčet   | TB: IBAN
                counterparty_bic TEXT,          -- FIO: Kód banky   | TB: —
                counterparty_bank_code TEXT,    -- FIO: —           | TB: Kód banky
                counterparty_bank_name TEXT,    -- FIO: Názov banky | TB: —

                description TEXT,                   -- FIO: Poznámka             | TB: Popis
                payer_reference TEXT,               -- FIO: Referencia platiteľa | TB: Referencia platiteľa
                payment_message TEXT,               -- FIO: Správa pre príjemcu  | TB: Informácia pre príjemcu
                variable_symbol TEXT,               -- FIO: VS (1st)             | TB: Variabilný symbol
                specific_symbol TEXT,               -- FIO: SS (1st)             | TB: Špecifický symbol
                constant_symbol TEXT,               -- FIO: KS (1st)             | TB: Konštantný symbol

                bank_transaction_id TEXT,       -- FIO: ID operácie | TB: —
                payment_instruction_id TEXT,    -- FIO: ID pokynu | TB: —
                initiated_by TEXT,              -- FIO: Zadal | TB: —

                amount_related INTEGER,  -- FIO: Upresnenie - objem | TB: —
                currency_related TEXT    -- FIO: Upresnenie - mena | TB: —
            );

            CREATE INDEX IF NOT EXISTS idx_transactions_booking_date
                ON transactions(booking_date);

            CREATE INDEX IF NOT EXISTS idx_transactions_source_bank
                ON transactions(source_bank);
        """)
    finally:
        connection.close()
