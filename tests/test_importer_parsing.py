"""Tests for CSV parsing, date/amount normalization, and symbol extraction."""

import unittest

# noinspection PyProtectedMember
from src.importer import _to_iso_date, _to_minor_units, _normalize_domestic_bank_code, _normalize_payer_reference, \
    _move_symbols_from_payer_reference, _parse_csv, FIO_HEADERS, TB_HEADERS
from support import fio_bytes, fio_row, tb_bytes, tb_row


class IsoDateTests(unittest.TestCase):
    """Test suite for _to_iso_date string parsing and validation."""

    def test_supported_formats(self):
        """Verify supported date formats are normalized to ISO YYYY-MM-DD."""
        for text, expected in (
                ("01.10.2026", "2026-10-01"),
                ("1.10.2026", "2026-10-01"),
                ("2026-10-01", "2026-10-01"),
                ("01/10/2026", "2026-10-01"),  # day first
                ("29.02.2024", "2024-02-29"),
        ):
            with self.subTest(text=text):
                self.assertEqual(_to_iso_date(text), expected)

    def test_none_stays_none(self):
        """Verify None input returns None."""
        self.assertIsNone(_to_iso_date(None))

    def test_unsupported_or_impossible_dates_fail(self):
        """Verify invalid or unparseable date strings raise a ValueError."""
        for text in ("31.02.2026", "29.02.2026", "2026.10.01", "10-01-2026", "abc", ""):
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, "Unsupported date"):
                    _to_iso_date(text)


class MinorUnitsTests(unittest.TestCase):
    """Test suite for _to_minor_units amount conversion and decimal scaling."""

    def test_valid_amounts(self):
        """Verify valid decimal amounts in supported currencies convert to integer minor units."""
        for text, currency, expected in (
                ("10,50", "EUR", 1050),
                ("10.50", "EUR", 1050),
                ("-10,50", "EUR", -1050),
                ("+10,50", "EUR", 1050),
                ("10", "EUR", 1000),
                ("0", "EUR", 0),
                ("0,01", "EUR", 1),
                ("-0,01", "EUR", -1),
                ("1 234,56", "EUR", 123456),
                ("1\u00a0234,56", "EUR", 123456),  # non-breaking space
                ("1\u202f234,56", "EUR", 123456),  # narrow no-break space
                ("1.234,56", "EUR", 123456),  # European thousands separator
                ("1,234.56", "EUR", 123456),  # US thousands separator
                ("-1.234.567,89", "EUR", -123456789),
                ("1000", "CZK", 100000),
                ("1000", "JPY", 1000),  # JPY has no minor unit
        ):
            with self.subTest(text=text, currency=currency):
                self.assertEqual(_to_minor_units(text, currency), expected)

    def test_none_stays_none(self):
        """Verify None input returns None."""
        self.assertIsNone(_to_minor_units(None, "EUR"))
        self.assertIsNone(_to_minor_units(None, None))

    def test_too_many_decimals_fail(self):
        """Verify exceeding the allowed currency decimals raises a precision error."""
        for text, currency in (("10,505", "EUR"), ("10.505", "EUR"), ("100,5", "JPY")):
            with self.subTest(text=text, currency=currency):
                with self.assertRaisesRegex(ValueError, "invalid precision"):
                    _to_minor_units(text, currency)

    def test_ambiguous_single_separator_with_three_digits_fails(self):
        """Verify ambiguous three-digit single separator formats raise a ValueError."""
        # "1,234" could be 1.234 or 1234; the importer refuses to guess.
        for text in ("1,234", "1.234"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    _to_minor_units(text, "EUR")

    def test_garbage_fails(self):
        """Verify malformed numeric strings raise an Invalid amount error."""
        for text in ("abc", "", "--5", "1,2,3"):
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, "Invalid amount"):
                    _to_minor_units(text, "EUR")

    def test_non_finite_numbers_fail(self):
        """Verify non-finite float strings such as NaN and Infinity raise a ValueError."""
        for text in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    _to_minor_units(text, "EUR")

    def test_unsupported_currency_fails(self):
        """Verify unsupported or lowercase currency codes raise an Unsupported currency error."""
        for currency in ("XYZ", "eur", None):
            with self.subTest(currency=currency):
                with self.assertRaisesRegex(ValueError, "Unsupported currency"):
                    _to_minor_units("10", currency)


class DomesticBankCodeTests(unittest.TestCase):
    """Test suite for _normalize_domestic_bank_code Slovak bank code padding."""

    def test_codes_are_zero_padded_to_four_digits(self):
        """Verify bank codes are zero-padded to four digits."""
        for code, expected in (("200", "0200"), ("0200", "0200"), ("1100", "1100"), ("9", "0009")):
            with self.subTest(code=code):
                self.assertEqual(_normalize_domestic_bank_code(code), expected)

    def test_none_stays_none(self):
        """Verify None input returns None."""
        self.assertIsNone(_normalize_domestic_bank_code(None))

    def test_invalid_codes_fail(self):
        """Verify invalid, non-ASCII, or out-of-range bank codes raise a ValueError."""
        for code in ("12345", "abc", "12 3", "-100", "\u0663\u0660\u0660"):  # last: Arabic-Indic digits
            with self.subTest(code=code):
                with self.assertRaisesRegex(ValueError, "Invalid domestic bank code"):
                    _normalize_domestic_bank_code(code)


class PayerReferenceTests(unittest.TestCase):
    """Test suite for _normalize_payer_reference placeholder stripping and cleanup."""

    def test_none_stays_none(self):
        """Verify None input returns None."""
        self.assertIsNone(_normalize_payer_reference(None))

    def test_value_is_stripped(self):
        """Verify leading and trailing whitespace is stripped."""
        self.assertEqual(_normalize_payer_reference("  REF 123  "), "REF 123")

    def test_blank_becomes_none(self):
        """Verify blank or whitespace-only references become None."""
        self.assertIsNone(_normalize_payer_reference("   "))

    def test_not_provided_placeholder_becomes_none(self):
        """Verify variations of NOTPROVIDED placeholders are converted to None."""
        for text in ("NOTPROVIDED", "NOT PROVIDED", "not provided", " Not  Provided ", "N O T P R O V I D E D"):
            with self.subTest(text=text):
                self.assertIsNone(_normalize_payer_reference(text))

    def test_text_that_merely_contains_the_placeholder_is_kept(self):
        """Verify references containing NOTPROVIDED as part of longer text are preserved."""
        self.assertEqual(_normalize_payer_reference("NOT PROVIDED yet"), "NOT PROVIDED yet")


def make_record(**overrides):
    """Create a dummy transaction record dictionary with symbol fields."""
    record = {"payer_reference": None, "variable_symbol": None,
              "specific_symbol": None, "constant_symbol": None}
    record.update(overrides)
    return record


def moved(reference, **columns):
    """Construct a record and apply _move_symbols_from_payer_reference."""
    return _move_symbols_from_payer_reference(make_record(payer_reference=reference, **columns))


class SymbolsFromPayerReferenceTests(unittest.TestCase):
    """Test suite for extracting VS, SS, and KS symbols from payer reference strings."""

    def assert_symbols(self, record, vs, ss, ks, reference=None):
        """Assert expected symbol values and remaining payer_reference in a record."""
        self.assertEqual(
            (record["variable_symbol"], record["specific_symbol"], record["constant_symbol"],
             record["payer_reference"]),
            (vs, ss, ks, reference),
        )

    def test_all_three_supported_forms_are_moved_and_cleared(self):
        """Verify ?, /, or bare leading prefix formats are moved into symbol columns."""
        for reference in ("?/VS123/SS456/KS789", "/VS123/SS456/KS789", "VS123/SS456/KS789"):
            with self.subTest(reference=reference):
                self.assert_symbols(moved(reference), "123", "456", "789")

    def test_empty_tags_leave_their_columns_empty(self):
        """Verify empty symbol tags leave corresponding column values as None."""
        self.assert_symbols(moved("VS123/SS/KS"), "123", None, None)
        self.assert_symbols(moved("/VS/SS0000000000/KS"), None, "0000000000", None)

    def test_all_tags_empty_still_clears_the_reference(self):
        """Verify reference containing only empty tags is cleared to None."""
        self.assert_symbols(moved("VS/SS/KS"), None, None, None)

    def test_is_case_insensitive_and_ignores_whitespace(self):
        """Verify symbol extraction is case-insensitive and ignores internal whitespace."""
        self.assert_symbols(moved("vs123/ss456/ks789"), "123", "456", "789")
        self.assert_symbols(moved("? /VS 123 / SS 456 / KS 789"), "123", "456", "789")

    def test_matching_existing_value_is_kept_as_is(self):
        """Verify matching existing symbol values retain their original format."""
        record = moved("/VS0055/SS/KS0308", variable_symbol="55", constant_symbol="308")
        self.assert_symbols(record, "55", None, "308")  # column keeps its own spelling

    def test_existing_value_only_fills_gaps(self):
        """Verify extracted symbols only populate missing fields without overriding agreed ones."""
        record = moved("/VS123/SS456/KS789", specific_symbol="456")
        self.assert_symbols(record, "123", "456", "789")

    def test_conflicting_existing_value_fails(self):
        """Verify conflicting existing symbol values raise a ValueError."""
        for column in ("variable_symbol", "specific_symbol", "constant_symbol"):
            with self.subTest(column=column):
                with self.assertRaisesRegex(ValueError, f"{column} '999' conflicts with payer_reference"):
                    moved("/VS123/SS456/KS789", **{column: "999"})

    def test_other_references_are_left_untouched(self):
        """Verify unrecognized reference formats are left unmodified."""
        for reference in (
                None,
                "free text",
                "/VS123/SS456",  # KS missing
                "/SS456/VS123/KS789",  # wrong order
                "/VS123/SS456/KS789 extra",  # extra text
                "INV 2026/VS123/SS456/KS789",
                "/VS12A/SS456/KS789",  # non-digit
        ):
            with self.subTest(reference=reference):
                record = moved(reference, variable_symbol="1")
                self.assert_symbols(record, "1", None, None, reference)


class ParseCsvTests(unittest.TestCase):
    """Test suite for _parse_csv bank detection, encoding handling, and delimiter parsing."""

    def test_detects_fio(self):
        """Verify automatic detection and parsing of FIO CSV exports."""
        row = fio_row()
        bank, header, rows = _parse_csv(fio_bytes([row]), "fio.csv")
        self.assertEqual(bank, "FIO")
        self.assertEqual(header, FIO_HEADERS)
        self.assertEqual(rows, [row])

    def test_detects_tb(self):
        """Verify automatic detection and parsing of Tatra banka CSV exports."""
        row = tb_row(description="Platba č. 5")
        bank, header, rows = _parse_csv(tb_bytes([row]), "tb.csv")
        self.assertEqual(bank, "TB")
        self.assertEqual(header, TB_HEADERS)
        self.assertEqual(rows, [row])

    def test_header_only_file_has_no_rows(self):
        """Verify a file containing only headers returns an empty row list."""
        self.assertEqual(_parse_csv(tb_bytes([]), "tb.csv")[2], [])

    def test_header_whitespace_is_ignored(self):
        """Verify whitespace surrounding header names is stripped and ignored."""
        padded = ";".join(f" {name} " for name in FIO_HEADERS) + "\r\n"
        bank, header, _ = _parse_csv(padded.encode("utf-8-sig"), "fio.csv")
        self.assertEqual((bank, header), ("FIO", FIO_HEADERS))

    def test_unknown_headers_fail_and_name_the_file(self):
        """Verify unrecognized CSV headers raise an error naming the file."""
        with self.assertRaisesRegex(ValueError, "weird.csv.*unrecognized"):
            _parse_csv(b"a,b,c\r\n1,2,3\r\n", "weird.csv")

    def test_empty_file_fails(self):
        """Verify completely empty CSV files raise a ValueError."""
        with self.assertRaisesRegex(ValueError, "empty.csv"):
            _parse_csv(b"", "empty.csv")

    def test_tb_header_with_wrong_delimiter_fails(self):
        """Verify Tatra banka files with invalid delimiters raise a ValueError."""
        semicolons = ";".join(TB_HEADERS).encode("cp1250")
        with self.assertRaises(ValueError):
            _parse_csv(semicolons, "tb.csv")

    def test_tb_saved_in_the_wrong_encoding_fails(self):
        """Verify Tatra banka files encoded in UTF-8 instead of CP1250 fail parsing."""
        wrong = tb_bytes([tb_row()]).decode("cp1250").encode("utf-8")
        with self.assertRaises(ValueError):
            _parse_csv(wrong, "tb.csv")


if __name__ == "__main__":
    unittest.main()
