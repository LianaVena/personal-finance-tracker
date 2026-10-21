"""Tests for mapping bank statement rows to transaction records."""

import unittest

# noinspection PyProtectedMember
from src.importer import _parse_transaction_row, TB_HEADERS, FIO_HEADERS, TRANSACTION_COLUMNS
from support import fio_row, tb_row


def tb_record(**kwargs):
    """Parse a transaction row using the Tatra banka column layout."""
    return _parse_transaction_row("TB", TB_HEADERS, tb_row(**kwargs))


def fio_record(values=None):
    """Parse a transaction row using the Fio bank column layout."""
    return _parse_transaction_row("FIO", FIO_HEADERS, fio_row(values))


class TbRecordTests(unittest.TestCase):
    """Verify Tatra banka rows are normalized into transaction records."""

    def test_full_mapping(self):
        """Map all supported Tatra banka fields to their record columns."""
        record = tb_record(
            date="01.10.2026", value_date="02.10.2026", amount="25,50", currency="EUR",
            tx_type="Debet", bank_code="200", iban="SK3111000000001234567890",
            vs="123", ss="456", ks="308", payer_reference="REF1",
            message="msg", description="desc",
        )
        self.assertEqual(record, {
            "source_bank": "TB",
            "booking_date": "2026-10-01",
            "value_date": "2026-10-02",
            "amount": -2550,
            "currency": "EUR",
            "transaction_type": "DEBIT",
            "counterparty_name": None,
            "counterparty_iban": "SK3111000000001234567890",
            "counterparty_bic": None,
            "counterparty_bank_code": "0200",
            "counterparty_bank_name": None,
            "description": "desc",
            "payer_reference": "REF1",
            "payment_message": "msg",
            "variable_symbol": "123",
            "specific_symbol": "456",
            "constant_symbol": "308",
            "bank_transaction_id": None,
            "payment_instruction_id": None,
            "initiated_by": None,
            "amount_related": None,
            "currency_related": None,
        })

    def test_keys_are_exactly_the_insert_columns(self):
        """Return exactly the columns expected by transaction insertion."""
        self.assertEqual(set(tb_record()), set(TRANSACTION_COLUMNS))

    def test_direction_comes_from_type_not_from_the_sign(self):
        """Derive debit and credit direction from the bank transaction type."""
        for tx_type, amount, expected in (
                ("Debet", "10,00", -1000),
                ("Debet", "-10,00", -1000),
                ("Kredit", "10,00", 1000),
                ("Kredit", "-10,00", 1000),
        ):
            with self.subTest(tx_type=tx_type, amount=amount):
                self.assertEqual(tb_record(tx_type=tx_type, amount=amount)["amount"], expected)

    def test_transaction_type_is_canonical(self):
        """Normalize Tatra banka transaction labels to canonical values."""
        self.assertEqual(tb_record(tx_type="Debet")["transaction_type"], "DEBIT")
        self.assertEqual(tb_record(tx_type="Kredit")["transaction_type"], "CREDIT")

    def test_unknown_type_fails(self):
        """Reject transaction labels that are not recognized."""
        with self.assertRaisesRegex(ValueError, "Unknown TB transaction type"):
            tb_record(tx_type="Prevod")

    def test_empty_cells_become_none(self):
        """Convert empty optional cells to None."""
        record = tb_record(value_date="", iban="", vs="", ss="", ks="", message="", description="")
        for column in ("value_date", "counterparty_iban", "variable_symbol", "specific_symbol",
                       "constant_symbol", "payment_message", "description"):
            with self.subTest(column=column):
                self.assertIsNone(record[column])

    def test_not_provided_payer_reference_becomes_none(self):
        """Treat the bank's missing-reference marker as an absent value."""
        self.assertIsNone(tb_record(payer_reference="NOT PROVIDED")["payer_reference"])

    def test_missing_bank_code_stays_none(self):
        """Leave an absent counterparty bank code unset."""
        self.assertIsNone(tb_record(bank_code="")["counterparty_bank_code"])

    def test_wrong_number_of_columns_fails(self):
        """Reject rows whose cell count does not match the bank layout."""
        with self.assertRaisesRegex(ValueError, "Expected 15 columns; found 14"):
            _parse_transaction_row("TB", TB_HEADERS, tb_row()[:-1])

    def test_invalid_amount_date_currency_and_bank_code_fail(self):
        """Reject malformed dates, amounts, currencies, and bank codes."""
        for kwargs in ({"amount": "abc"}, {"date": "99.99.9999"}, {"currency": "XYZ"}, {"bank_code": "12345"}):
            with self.subTest(**kwargs):
                with self.assertRaises(ValueError):
                    tb_record(**kwargs)


class FioRecordTests(unittest.TestCase):
    """Verify Fio rows are normalized into transaction records."""

    FULL = {
        "Dátum": "15.10.2026",
        "Objem": "-12,34",
        "Mena": "EUR",
        "Protiúčet": "SK1234567890",
        "Kód banky": "TATRSKBX",
        "Správa pre príjemcu": "message",
        "Poznámka": "note",
        "Typ": "Transakcia kartou",
        "ID operácie": "1001",
        "ID pokynu": "2002",
        ("KS", 1): "0308",
        "Názov banky": "Tatra banka",
        "Názov protiúčtu": "Shop s.r.o.",
        "Referencia platiteľa": "REF",
        ("SS", 1): "77",
        ("VS", 1): "123",
        "Upresnenie - objem": "10,00",
        "Upresnenie - mena": "USD",
        "Zadal": "Jane Doe",
    }

    def test_full_mapping(self):
        """Map all supported Fio fields to their record columns."""
        self.assertEqual(fio_record(self.FULL), {
            "source_bank": "FIO",
            "booking_date": "2026-10-15",
            "value_date": None,
            "amount": -1234,
            "currency": "EUR",
            "transaction_type": "CARD_TRANSACTION",
            "counterparty_name": "Shop s.r.o.",
            "counterparty_iban": "SK1234567890",
            "counterparty_bic": "TATRSKBX",
            "counterparty_bank_code": None,
            "counterparty_bank_name": "Tatra banka",
            "description": "note",
            "payer_reference": "REF",
            "payment_message": "message",
            "variable_symbol": "123",
            "specific_symbol": "77",
            "constant_symbol": "0308",
            "bank_transaction_id": "1001",
            "payment_instruction_id": "2002",
            "initiated_by": "Jane Doe",
            "amount_related": 1000,
            "currency_related": "USD",
        })

    def test_keys_are_exactly_the_insert_columns(self):
        """Return exactly the columns expected by transaction insertion."""
        self.assertEqual(set(fio_record()), set(TRANSACTION_COLUMNS))

    def test_uses_first_occurrence_of_repeated_symbol_headers(self):
        """Use the first occurrence when symbol headers are repeated."""
        # FIO repeats VS/SS/KS; only the first column of each pair is imported.
        # If you add a guard that rejects differing second columns, update this test.
        record = fio_record({
            ("VS", 1): "1", ("VS", 2): "2",
            ("SS", 1): "3", ("SS", 2): "4",
            ("KS", 1): "5", ("KS", 2): "6",
        })
        self.assertEqual(
            (record["variable_symbol"], record["specific_symbol"], record["constant_symbol"]),
            ("1", "3", "5"),
        )

    def test_every_known_fio_type_label_is_accepted(self):
        """Accept each supported Fio transaction label."""
        for label in ("Transakcia kartou", "Poplatok - platobná karta", "Bezhotovostná platba",
                      "Bezhotovostný príjem", "Platba prevodom v rámci banky",
                      "Okamžitá odchádzajúca Europlatba", "Okamžitá prichádzajúca Europlatba"):
            with self.subTest(label=label):
                self.assertTrue(fio_record({"Typ": label})["transaction_type"])

    def test_unknown_type_fails(self):
        """Reject transaction labels that are not recognized."""
        with self.assertRaisesRegex(ValueError, "Unknown transaction type"):
            fio_record({"Typ": "Novy typ"})

    def test_missing_type_fails(self):
        """Reject rows without a transaction type."""
        with self.assertRaises(ValueError):
            fio_record({"Typ": ""})

    def test_sign_of_amount_is_kept(self):
        """Preserve the sign of Fio transaction amounts."""
        self.assertEqual(fio_record({"Objem": "-5,00"})["amount"], -500)
        self.assertEqual(fio_record({"Objem": "5,00"})["amount"], 500)

    def test_related_amount_is_optional(self):
        """Leave optional related-currency fields unset when absent."""
        record = fio_record()
        self.assertIsNone(record["amount_related"])
        self.assertIsNone(record["currency_related"])

    def test_related_amount_uses_its_own_currency(self):
        """Parse a related amount alongside its specified currency."""
        record = fio_record({"Upresnenie - objem": "1000", "Upresnenie - mena": "JPY"})
        self.assertEqual((record["amount_related"], record["currency_related"]), (1000, "JPY"))

    def test_not_provided_payer_reference_becomes_none(self):
        """Treat Fio's missing-reference marker as an absent value."""
        self.assertIsNone(fio_record({"Referencia platiteľa": "NOTPROVIDED"})["payer_reference"])

    def test_wrong_number_of_columns_fails(self):
        """Reject rows whose cell count does not match the bank layout."""
        with self.assertRaisesRegex(ValueError, "Expected 22 columns; found 21"):
            _parse_transaction_row("FIO", FIO_HEADERS, fio_row()[:-1])


if __name__ == "__main__":
    unittest.main()
