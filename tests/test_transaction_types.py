"""Tests for canonical transaction types and their source labels."""

import unittest

from src.transaction_types import (
    SOURCE_TRANSACTION_TYPES,
    TRANSACTION_TYPE_LABELS,
    TransactionType,
    translate_transaction_type,
)


class TranslateTransactionTypeTests(unittest.TestCase):
    """Verify bank labels translate to canonical transaction types."""

    def test_every_source_label_maps_to_its_canonical_type(self):
        """Translate every configured bank label to its expected type."""
        for bank, labels in SOURCE_TRANSACTION_TYPES.items():
            for label, expected in labels.items():
                with self.subTest(bank=bank, label=label):
                    self.assertIs(translate_transaction_type(bank, label), expected)

    def test_representative_bank_labels_map_to_expected_types(self):
        """Translate representative Fio and Tatra banka labels."""
        self.assertIs(translate_transaction_type("FIO", "Transakcia kartou"),
                      TransactionType.CARD_TRANSACTION)
        self.assertIs(translate_transaction_type("FIO", "Okamžitá prichádzajúca Europlatba"),
                      TransactionType.INCOMING_INSTANT_SEPA_TRANSFER)
        self.assertIs(translate_transaction_type("TB", "Debet"), TransactionType.DEBIT)
        self.assertIs(translate_transaction_type("TB", "Kredit"), TransactionType.CREDIT)

    def test_unknown_label_fails_and_names_the_label_and_bank(self):
        """Include the unknown label and bank in translation errors."""
        with self.assertRaises(ValueError) as caught:
            translate_transaction_type("FIO", "Something new")
        self.assertIn("Something new", str(caught.exception))
        self.assertIn("FIO", str(caught.exception))

    def test_label_from_the_other_bank_is_not_accepted(self):
        """Reject a label when it belongs to a different bank."""
        with self.assertRaises(ValueError):
            translate_transaction_type("FIO", "Debet")
        with self.assertRaises(ValueError):
            translate_transaction_type("TB", "Transakcia kartou")

    def test_unknown_bank_fails(self):
        """Reject labels for unrecognized banks."""
        with self.assertRaises(ValueError):
            translate_transaction_type("XX", "Debet")

    def test_missing_label_fails(self):
        """Reject a missing transaction label."""
        with self.assertRaises(ValueError):
            translate_transaction_type("TB", None)

    def test_matching_is_exact(self):
        """Require exact label spelling, case, and surrounding whitespace."""
        for label in ("debet", "DEBET", "Debet ", " Debet", ""):
            with self.subTest(label=label):
                with self.assertRaises(ValueError):
                    translate_transaction_type("TB", label)


class TransactionTypeDefinitionTests(unittest.TestCase):
    """Verify the canonical type enum and its display labels."""

    def test_every_type_has_a_display_label(self):
        """Provide a display label for each canonical transaction type."""
        self.assertEqual(set(TRANSACTION_TYPE_LABELS), set(TransactionType))

    def test_display_labels_are_unique(self):
        """Use a distinct display label for each transaction type."""
        labels = list(TRANSACTION_TYPE_LABELS.values())
        self.assertEqual(len(labels), len(set(labels)))

    def test_every_type_can_be_produced_from_some_bank_label(self):
        """Make every canonical type reachable from at least one bank label."""
        reachable = {t for labels in SOURCE_TRANSACTION_TYPES.values() for t in labels.values()}
        self.assertEqual(reachable, set(TransactionType))

    def test_stored_value_is_the_type_name(self):
        """Keep each stored enum value equal to its canonical name."""
        # The importer stores `.value` in the database.
        for member in TransactionType:
            with self.subTest(member=member):
                self.assertEqual(member.value, member.name)
        self.assertEqual(TransactionType.CARD_FEE, "CARD_FEE")


if __name__ == "__main__":
    unittest.main()
