# Personal Finance Tracker

> Most of this app's code was written by AI, guided by the author's product, design, and business requirements.

A local personal-finance app for importing bank CSV exports, reviewing transactions, assigning categories and
counterparties, splitting payments, and tracking subscriptions. It uses Python, SQLite, and NiceGUI. The web interface
is served on `http://127.0.0.1:8765` and is intended for local use.

## Requirements

- Python 3.11 or newer
- Dependencies from `requirements.txt` (currently NiceGUI)
- CSV exports from Fio bank and/or Tatra banka

## Install and run

From the project directory, create and activate a virtual environment, install the dependencies, and start the app:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python src\main.py
```

On startup, the app initializes or validates its databases, imports CSV files found in the project's `imports`
directory, applies automatic matching, marks stale subscriptions inactive, and opens the local interface in a browser
tab. The `imports` directory is created if needed. Place supported bank export `.csv` files there before starting the
app.

## Supported imports

- **Fio banka:** UTF-8 CSV, optionally with a byte-order mark, separated by semicolons.
- **Tatra banka:** Windows-1250 CSV, separated by commas.

The importer identifies a bank from the CSV headers, so it does not rely on a particular filename. It normalizes dates,
transaction types, payer references, and monetary values, and extracts variable, specific, and constant symbols from
structured payer references where possible.

Each imported transaction receives a deterministic SHA-256 ID based on its normalized bank fields. Re-imports and
overlapping exports skip transactions already present. A malformed file is rolled back as a unit, while successfully
imported earlier files remain. Identical normalized transaction rows in a single CSV are reported as ambiguous because a
content-based ID cannot distinguish them.

## App tabs

### Review

The Review tab shows one transaction at a time, newest first, when it still needs attention. Imported transaction fields
are shown with readable labels; empty fields and the transaction ID are omitted. Use the previous and next arrows to
move through the queue.

For a transaction, you can:

- Assign a counterparty and add a transaction-wide note.
- Choose a subcategory and mark the payment as a subscription, not a subscription, or unresolved. A subscription marked
  Yes can be linked to a specific subscription.
- Exclude the payment from spending summaries.
- Split a payment into multiple signed amounts, each with its own subcategory, subscription decision/link, note, and
  exclusion setting.
- Save once the splits reconcile to the imported amount and each non-excluded split has the required category and
  subscription details.

The category creation forms on the right create categories, subcategories, counterparties, and subscriptions without
leaving the Review tab. New counterparties and subscriptions can include optional matching rules.

Subcategories can be assigned a color from the colors stored in `finance.db`. The picker opens as a compact, named
palette, and subcategories may also have no color. The palette is sorted by hue when the app starts. Colors are
maintained in the database rather than defined as a fixed palette in the application code.

### Subscriptions

Subscriptions are grouped into active and inactive tables. The tables show the latest payment's category and
subcategory, billing period, expected amount, and active status. Monthly and yearly equivalents are displayed; an `fx`
mark indicates a calculated equivalent. Active monthly and yearly totals are shown above the active table. The active
checkbox can be changed directly in either table.

Rows are tinted with the assigned subcategory color when the latest linked payment has one consistent color. The row
background uses that color's `row_hex`; colors are omitted when the latest payment has mixed or unset subcategory colors.

At startup, an active subscription is made inactive when its latest linked payment is more than one calendar billing
period old. Subscriptions without a linked payment are left active. Inactive subscriptions remain eligible when matching
historical transactions.

### Manage

Manage provides tables and editors for categories, subcategories, counterparties, and subscriptions. Select a row to
edit it; when no row is selected, the editor creates a new item. Counterparty and subscription matching rules can be
added, edited, and removed here. Tables can be sorted by their sortable columns; the subcategory table includes its
color and supports sorting by color. Subcategory colors can be selected or cleared in both create and edit forms.

## Automatic matching

Counterparty match rules look for a configured pattern inside one selected imported field: counterparty name, IBAN,
payer reference, payment message, or description. Matching is case-insensitive and uses Unicode-aware text
normalization. If rules resolve to more than one counterparty, the app leaves the counterparty unresolved for review.

A counterparty can provide a default subcategory and a default subscription answer. Those defaults are applied
automatically to matching transaction splits, but a manual split choice is preserved when rules are refreshed.

Subscriptions are matched separately from categories. A subscription may be scoped to a counterparty and may have
optional text match rules. When an expected amount and currency are set, both must match; the amount's sign is ignored.
An unambiguous match can link a split automatically. Ambiguous candidates remain unresolved for review. Subscription
active status controls the active/inactive display and does not disable matching.

Automatic matching runs after imports at startup and when new counterparties or subscriptions are created. The review
queue excludes a transaction only when its non-excluded splits have a subcategory, a subscription answer, and a linked
subscription for every Yes answer, and the split amounts add up to the original transaction amount.

## Data files and safety

The app uses two SQLite databases in the project directory:

- `transactions.db` stores imported bank transactions and can be rebuilt from the CSV exports.
- `finance.db` stores categories, counterparties, subscriptions, notes, matching rules, and transaction split decisions.
  Treat this as persistent user data and keep backups.

The databases are separate because imported transactions can be rebuilt while finance annotations should persist.
Finance references transaction IDs by their stable hashes; SQLite cannot enforce foreign keys across separate database
files. The app checks that an existing `finance.db` has the expected schema and stops if it does not. It does not
migrate an older or incompatible finance database automatically.

Do not delete `finance.db` to troubleshoot the app. Back up the database files before making manual changes. Bank CSV
exports and both databases contain sensitive financial information; keep them local and out of source control.

## Tests

Run the test suite from the project root:

```powershell
python -m unittest discover -s tests -v
```

Tests use synthetic transactions and temporary databases; they do not require real bank exports.
