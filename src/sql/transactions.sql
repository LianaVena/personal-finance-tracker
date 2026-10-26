CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY NOT NULL
        CHECK (length(id) = 64),
    source_bank TEXT NOT NULL
        CHECK (source_bank IN ('FIO', 'TB')),

    booking_date TEXT NOT NULL,    -- FIO: Dátum | TB: Dátum spracovania
    value_date TEXT,               -- FIO: —     | TB: Dátum zúčtovania
    amount INTEGER NOT NULL,       -- FIO: Objem | TB: Suma
    currency TEXT NOT NULL,        -- FIO: Mena  | TB: Mena
    transaction_type TEXT,         -- FIO: Typ   | TB: Typ (mapped to TransactionType)

    counterparty_name TEXT,        -- FIO: Názov protiúčtu | TB: —
    counterparty_iban TEXT,        -- FIO: Protiúčet       | TB: IBAN
    counterparty_bic TEXT,         -- FIO: Kód banky       | TB: —
    counterparty_bank_code TEXT,   -- FIO: —               | TB: Kód banky
    counterparty_bank_name TEXT,   -- FIO: Názov banky     | TB: —

    description TEXT,              -- FIO: Poznámka              | TB: Popis
    payer_reference TEXT,          -- FIO: Referencia platiteľa  | TB: Referencia platiteľa
    payment_message TEXT,          -- FIO: Správa pre príjemcu   | TB: Informácia pre príjemcu
    variable_symbol TEXT,          -- FIO: VS (1st)              | TB: Variabilný symbol
    specific_symbol TEXT,          -- FIO: SS (1st)              | TB: Špecifický symbol
    constant_symbol TEXT,          -- FIO: KS (1st)              | TB: Konštantný symbol

    bank_transaction_id TEXT,      -- FIO: ID operácie  | TB: —
    payment_instruction_id TEXT,   -- FIO: ID pokynu   | TB: —
    initiated_by TEXT,             -- FIO: Zadal       | TB: —

    amount_related INTEGER,        -- FIO: Upresnenie - objem | TB: —
    currency_related TEXT          -- FIO: Upresnenie - mena  | TB: —
);
CREATE INDEX IF NOT EXISTS idx_transactions_booking_date
    ON transactions(booking_date);
CREATE INDEX IF NOT EXISTS idx_transactions_source_bank
    ON transactions(source_bank);
