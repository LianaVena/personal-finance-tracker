"""Canonical banking transaction types and their source-bank CSV labels."""

from enum import StrEnum


class TransactionType(StrEnum):
    """Enumeration of canonical banking transaction types across supported banks."""
    CARD_TRANSACTION = "CARD_TRANSACTION"
    CARD_FEE = "CARD_FEE"
    OUTGOING_TRANSFER = "OUTGOING_TRANSFER"
    INCOMING_TRANSFER = "INCOMING_TRANSFER"
    INTRABANK_TRANSFER = "INTRABANK_TRANSFER"
    OUTGOING_INSTANT_SEPA_TRANSFER = "OUTGOING_INSTANT_SEPA_TRANSFER"
    INCOMING_INSTANT_SEPA_TRANSFER = "INCOMING_INSTANT_SEPA_TRANSFER"
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


SOURCE_TRANSACTION_TYPES: dict[str, dict[str, TransactionType]] = {
    "FIO": {
        "Transakcia kartou": TransactionType.CARD_TRANSACTION,
        "Poplatok - platobná karta": TransactionType.CARD_FEE,
        "Bezhotovostná platba": TransactionType.OUTGOING_TRANSFER,
        "Bezhotovostný príjem": TransactionType.INCOMING_TRANSFER,
        "Platba prevodom v rámci banky": TransactionType.INTRABANK_TRANSFER,
        "Okamžitá odchádzajúca Europlatba": TransactionType.OUTGOING_INSTANT_SEPA_TRANSFER,
        "Okamžitá prichádzajúca Europlatba": TransactionType.INCOMING_INSTANT_SEPA_TRANSFER,
    },
    "TB": {
        "Debet": TransactionType.DEBIT,
        "Kredit": TransactionType.CREDIT,
    },
}

TRANSACTION_TYPE_LABELS = {
    TransactionType.CARD_FEE: "Card Fee",
    TransactionType.CARD_TRANSACTION: "Card Transaction",
    TransactionType.INCOMING_INSTANT_SEPA_TRANSFER: "Incoming Instant SEPA Transfer",
    TransactionType.INCOMING_TRANSFER: "Incoming Bank Transfer",
    TransactionType.INTRABANK_TRANSFER: "Intra-bank Transfer",
    TransactionType.OUTGOING_INSTANT_SEPA_TRANSFER: "Outgoing Instant SEPA Transfer",
    TransactionType.OUTGOING_TRANSFER: "Outgoing Bank Transfer",
    TransactionType.CREDIT: "Credit",
    TransactionType.DEBIT: "Debit",
}


def translate_transaction_type(bank: str, source_type: str | None) -> TransactionType:
    """Convert a bank's CSV transaction type to a canonical type.

    Unknown bank labels fail the import so that no transactions are silently
    misclassified when a bank changes its CSV format.

    Args:
        bank: Source bank identifier (e.g., 'FIO' or 'TB').
        source_type: Raw transaction type string from the CSV export, or None.

    Returns:
        The matching canonical TransactionType enumeration member.

    Raises:
        ValueError: If source_type is None, unknown, or if bank is unsupported.
    """
    try:
        if source_type is None:
            raise KeyError("missing transaction type")
        return SOURCE_TRANSACTION_TYPES[bank][source_type]
    except KeyError as exc:
        raise ValueError(
            f"Unknown transaction type {source_type!r} for bank {bank!r}"
        ) from exc
