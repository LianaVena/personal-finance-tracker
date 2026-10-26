PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE CHECK (length(trim(name)) > 0)
);

CREATE TABLE IF NOT EXISTS subcategories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
    name TEXT NOT NULL COLLATE NOCASE CHECK (length(trim(name)) > 0),
    UNIQUE (category_id, name)
);
CREATE INDEX IF NOT EXISTS idx_subcategories_category ON subcategories(category_id);

CREATE TABLE IF NOT EXISTS counterparties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE CHECK (length(trim(name)) > 0),
    default_subcategory_id INTEGER REFERENCES subcategories(id) ON DELETE SET NULL,
    default_is_subscription INTEGER CHECK (default_is_subscription IN (0, 1))
);

CREATE TABLE IF NOT EXISTS counterparties_match_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    counterparty_id INTEGER NOT NULL REFERENCES counterparties(id) ON DELETE CASCADE,
    source_field TEXT NOT NULL DEFAULT 'payment_message' CHECK (source_field IN (
        'counterparty_name', 'counterparty_iban', 'payer_reference',
        'payment_message', 'description'
    )),
    pattern TEXT NOT NULL COLLATE NOCASE CHECK (length(trim(pattern)) > 0),
    UNIQUE (source_field, pattern)
);
CREATE INDEX IF NOT EXISTS idx_counterparty_rules_counterparty
    ON counterparties_match_rules(counterparty_id);

CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE CHECK (length(trim(name)) > 0),
    counterparty_id INTEGER REFERENCES counterparties(id) ON DELETE SET NULL,
    billing_period TEXT NOT NULL CHECK (billing_period IN ('monthly', 'yearly')),
    expected_amount INTEGER CHECK (expected_amount <> 0),
    currency TEXT CHECK (currency GLOB '[A-Z][A-Z][A-Z]'),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    CHECK (
        (expected_amount IS NULL AND currency IS NULL)
        OR (expected_amount IS NOT NULL AND currency IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS idx_subscriptions_counterparty
    ON subscriptions(counterparty_id);

CREATE TABLE IF NOT EXISTS subscription_match_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_id INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
    source_field TEXT NOT NULL DEFAULT 'payment_message' CHECK (source_field IN (
        'counterparty_name', 'counterparty_iban', 'payer_reference',
        'payment_message', 'description'
    )),
    pattern TEXT NOT NULL COLLATE NOCASE CHECK (length(trim(pattern)) > 0),
    UNIQUE (subscription_id, source_field, pattern)
);
CREATE INDEX IF NOT EXISTS idx_subscription_rules_subscription
    ON subscription_match_rules(subscription_id);

CREATE TABLE IF NOT EXISTS transaction_metadata (
    transaction_id TEXT PRIMARY KEY CHECK (length(transaction_id) = 64),
    note TEXT,
    counterparty_id INTEGER REFERENCES counterparties(id) ON DELETE RESTRICT,
    counterparty_is_manual INTEGER CHECK (counterparty_is_manual IN (0, 1)),
    CHECK (
        (counterparty_id IS NULL AND counterparty_is_manual IS NULL)
        OR (counterparty_id IS NOT NULL AND counterparty_is_manual IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS idx_metadata_counterparty
    ON transaction_metadata(counterparty_id);

CREATE TABLE IF NOT EXISTS transaction_splits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id TEXT NOT NULL
        REFERENCES transaction_metadata(transaction_id) ON DELETE CASCADE,
    amount INTEGER NOT NULL CHECK (amount <> 0),
    subcategory_id INTEGER REFERENCES subcategories(id) ON DELETE RESTRICT,
    subcategory_is_manual INTEGER CHECK (subcategory_is_manual IN (0, 1)),
    note TEXT,
    is_subscription INTEGER CHECK (is_subscription IN (0, 1)),
    subscription_id INTEGER REFERENCES subscriptions(id) ON DELETE RESTRICT,
    subscription_is_manual INTEGER CHECK (subscription_is_manual IN (0, 1)),
    excluded INTEGER NOT NULL DEFAULT 0 CHECK (excluded IN (0, 1)),
    CHECK (
        (subcategory_id IS NULL AND subcategory_is_manual IS NULL)
        OR (subcategory_id IS NOT NULL AND subcategory_is_manual IS NOT NULL)
    ),
    CHECK (
        (is_subscription IS NULL AND subscription_id IS NULL
            AND subscription_is_manual IS NULL)
        OR (is_subscription IS 0 AND subscription_id IS NULL
            AND subscription_is_manual IS NOT NULL)
        OR (is_subscription IS 1 AND subscription_is_manual IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS idx_splits_transaction ON transaction_splits(transaction_id);
CREATE INDEX IF NOT EXISTS idx_splits_subcategory ON transaction_splits(subcategory_id);
CREATE INDEX IF NOT EXISTS idx_splits_subscription ON transaction_splits(subscription_id);
