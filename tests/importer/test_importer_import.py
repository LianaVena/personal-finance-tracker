"""Tests for CSV file importing, duplicate detection, failure handling, and symbol extraction."""

import unittest
from unittest.mock import patch

from src.importer import ImportResult, import_csv_files, TB_HEADERS
from tests.support import (
    BaseDatabaseTestCase,
    fio_row,
    tb_row,
    write_fio_csv,
    write_tb_csv,
)

SYMBOL_COLUMNS = "variable_symbol, specific_symbol, constant_symbol, payer_reference"


class ImportCsvFilesTests(BaseDatabaseTestCase):
    """Test suite for import_csv_files covering end-to-end import behaviors."""

    def write_tb(self, name, rows):
        """Write Tatra banka rows to a CSV file in the test imports directory.

        Args:
            name: Output CSV filename.
            rows: Synthetic Tatra banka rows to serialize.

        Returns:
            Path to the written CSV file.
        """
        return write_tb_csv(self.csv_dir / name, rows)

    def write_fio(self, name, rows):
        """Write FIO rows to a CSV file in the test imports directory.

        Args:
            name: Output CSV filename.
            rows: Synthetic Fio rows to serialize.

        Returns:
            Path to the written CSV file.
        """
        return write_fio_csv(self.csv_dir / name, rows)

    # ------------------------------------------------------------------ happy paths

    def test_imports_tb_statement(self):
        """Verify importing transactions from a Tatra banka CSV file."""
        self.write_tb("tb.csv", [
            tb_row(tx_type="Debet", amount="10,50", description="Coffee"),
            tb_row(tx_type="Kredit", amount="100,00", description="Salary"),
        ])
        self.assertEqual(self.run_import(), [ImportResult("tb.csv", "TB", 2)])
        self.assertEqual(
            self.query("SELECT source_bank, amount, currency, transaction_type, description "
                       "FROM transactions ORDER BY description"),
            [
                {"source_bank": "TB", "amount": -1050, "currency": "EUR",
                 "transaction_type": "DEBIT", "description": "Coffee"},
                {"source_bank": "TB", "amount": 10000, "currency": "EUR",
                 "transaction_type": "CREDIT", "description": "Salary"},
            ],
        )

    def test_imports_fio_statement(self):
        """Verify importing transactions from a FIO banka CSV file."""
        self.write_fio("fio.csv", [
            fio_row({"Objem": "-12,34", "Typ": "Transakcia kartou", "Názov protiúčtu": "Shop"}),
            fio_row({"Objem": "50,00", "Typ": "Bezhotovostný príjem"}),
        ])
        self.assertEqual(self.run_import(), [ImportResult("fio.csv", "FIO", 2)])
        self.assertEqual(
            self.query("SELECT source_bank, amount, transaction_type, counterparty_name "
                       "FROM transactions ORDER BY transaction_type"),
            [
                {"source_bank": "FIO", "amount": -1234, "transaction_type": "CARD_TRANSACTION",
                 "counterparty_name": "Shop"},
                {"source_bank": "FIO", "amount": 5000, "transaction_type": "INCOMING_TRANSFER",
                 "counterparty_name": None},
            ],
        )

    def test_both_banks_in_one_run(self):
        """Verify importing files from both FIO and Tatra banka in a single run."""
        self.write_fio("a_fio.csv", [fio_row()])
        self.write_tb("b_tb.csv", [tb_row()])
        results = self.run_import()
        self.assertEqual([(r.filename, r.bank, r.rows_imported) for r in results],
                         [("a_fio.csv", "FIO", 1), ("b_tb.csv", "TB", 1)])
        self.assertEqual(self.count_transactions(), 2)

    def test_amounts_are_stored_as_integer_minor_units(self):
        """Verify amounts are stored as integer minor units in SQLite."""
        self.write_tb("tb.csv", [
            tb_row(amount="1 234,56"),
            tb_row(amount="1000", currency="JPY"),
        ])
        self.run_import()
        rows = self.query("SELECT amount, typeof(amount) AS t FROM transactions ORDER BY amount")
        self.assertEqual(rows, [{"amount": 1000, "t": "integer"}, {"amount": 123456, "t": "integer"}])

    def test_windows_1250_characters_survive(self):
        """Verify Windows-1250 encoded diacritics are accurately preserved."""
        text = "Úhrada za služby, číslo 5 ťažký ľad ôsmy"
        self.write_tb("tb.csv", [tb_row(description=text)])
        self.run_import()
        self.assertEqual(self.query("SELECT description FROM transactions")[0]["description"], text)

    # ------------------------------------------------------------------ file selection

    def test_results_are_sorted_by_name_ignoring_case(self):
        """Verify CSV files are processed in case-insensitive alphabetical order."""
        for name, amount in (("b.csv", "2,00"), ("A.csv", "1,00"), ("c.csv", "3,00")):
            self.write_tb(name, [tb_row(amount=amount)])
        self.assertEqual([r.filename for r in self.run_import()], ["A.csv", "b.csv", "c.csv"])

    def test_only_csv_files_are_imported(self):
        """Verify non-CSV files and directories ending in .csv are ignored."""
        (self.csv_dir / "notes.txt").write_text("not a statement")
        (self.csv_dir / "folder.csv").mkdir()
        self.write_tb("UPPER.CSV", [tb_row()])
        self.assertEqual([r.filename for r in self.run_import()], ["UPPER.CSV"])

    def test_missing_directory_is_created(self):
        """Verify missing CSV directory is created automatically without error."""
        missing = self.temp_dir / "new" / "imports"
        self.assertEqual(import_csv_files(self.db_path, missing), [])
        self.assertTrue(missing.is_dir())

    def test_empty_directory_imports_nothing(self):
        """Verify importing an empty directory returns no results and inserts zero rows."""
        self.assertEqual(self.run_import(), [])
        self.assertEqual(self.count_transactions(), 0)

    def test_blank_rows_are_skipped(self):
        """Verify completely empty or blank CSV rows are skipped during import."""
        blank_cells = [""] * len(TB_HEADERS)
        self.write_tb("tb.csv", [tb_row(description="one"), blank_cells, [],
                                 tb_row(description="two")])
        self.assertEqual(self.run_import()[0].rows_imported, 2)
        self.assertEqual(self.count_transactions(), 2)

    def test_header_only_file_imports_zero_rows(self):
        """Verify a CSV file containing only headers reports zero imported rows."""
        self.write_tb("tb.csv", [])
        self.assertEqual(self.run_import(), [ImportResult("tb.csv", "TB", 0)])

    # ------------------------------------------------------------------ duplicate files

    def test_second_run_skips_files_already_imported(self):
        """Verify that re-running import on previously imported files skips them."""
        self.write_tb("tb.csv", [tb_row(description="one"), tb_row(description="two")])
        self.run_import()
        second = self.run_import()
        self.assertEqual(second, [ImportResult("tb.csv", "TB", 0, skipped=True)])
        self.assertEqual(self.count_transactions(), 2)

    def test_identical_content_under_another_name_is_skipped(self):
        """Verify that duplicate file contents under a different filename are skipped."""
        path = self.write_tb("a.csv", [tb_row()])
        (self.csv_dir / "b.csv").write_bytes(path.read_bytes())
        results = self.run_import()
        self.assertEqual([(r.filename, r.skipped) for r in results], [("a.csv", False), ("b.csv", True)])
        self.assertEqual(self.count_transactions(), 1)

    def test_overlapping_exports_only_import_new_rows(self):
        """Import rows unique to an export while skipping rows already stored."""
        first = tb_row(description="first")
        overlap = tb_row(amount="20,00", description="overlap")
        new = tb_row(amount="30,00", description="new")
        self.write_tb("a.csv", [first, overlap])
        self.write_tb("b.csv", [overlap, new])

        results = self.run_import()

        self.assertEqual([(result.rows_imported, result.skipped) for result in results],
                         [(2, False), (1, False)])
        self.assertEqual(
            [row["description"] for row in self.query(
                "SELECT description FROM transactions ORDER BY id")],
            ["first", "overlap", "new"],
        )

    def test_identical_rows_in_one_file_fail_as_ambiguous(self):
        """Reject duplicate rows within one file because stable IDs cannot distinguish them."""
        repeated = tb_row(description="same transaction details")
        self.write_tb("duplicates.csv", [repeated, repeated])
        with self.assertRaisesRegex(ValueError, "identical transactions within one CSV"):
            self.run_import()
        self.assertEqual(self.count_transactions(), 0)

    def test_hash_collision_preserves_original_row_and_rolls_back_new_file(self):
        """Reject different contents sharing an ID without overwriting an earlier import."""
        self.write_tb("a.csv", [tb_row(amount="10,00", description="Original")])
        self.write_tb("b.csv", [tb_row(amount="20,00", description="Different")])
        with patch("src.importer.generate_transaction_id", return_value="a" * 64):
            with self.assertRaisesRegex(ValueError, "b.csv, row 2: transaction ID collision"):
                self.run_import()
        self.assertEqual(self.query("SELECT amount, description FROM transactions"),
                         [{"amount": 1000, "description": "Original"}])

    def test_rows_that_differ_in_a_transaction_field_are_not_deduplicated(self):
        """Retain transactions with otherwise matching fields but different amounts."""
        self.write_tb("a.csv", [tb_row(amount="10,00", description="same")])
        self.write_tb("b.csv", [tb_row(amount="11,00", description="same")])

        results = self.run_import()

        self.assertEqual([result.rows_imported for result in results], [1, 1])
        self.assertEqual(
            [row["amount"] for row in self.query("SELECT amount FROM transactions ORDER BY amount")],
            [1000, 1100],
        )

    # ------------------------------------------------------------------ failures

    def test_bad_row_rolls_back_the_whole_file_and_reports_file_and_row(self):
        """Verify that an invalid row rolls back the entire file and logs no entries."""
        self.write_tb("bad.csv", [tb_row(description="one"), tb_row(description="two"),
                                  tb_row(amount="abc")])
        with self.assertRaisesRegex(ValueError, r"bad\.csv, row 4: Invalid amount"):
            self.run_import()
        self.assertEqual(self.count_transactions(), 0)

    def test_file_is_importable_once_fixed(self):
        """Verify that a corrected file can be imported successfully after prior failure."""
        self.write_tb("bad.csv", [tb_row(amount="abc")])
        with self.assertRaises(ValueError):
            self.run_import()
        self.write_tb("bad.csv", [tb_row()])
        self.assertEqual(self.run_import(), [ImportResult("bad.csv", "TB", 1)])

    def test_files_imported_before_a_failure_are_kept(self):
        """Verify that files committed prior to a subsequent file error remain saved."""
        self.write_tb("a_good.csv", [tb_row(description="one"), tb_row(description="two")])
        self.write_tb("b_bad.csv", [tb_row(amount="abc")])
        with self.assertRaises(ValueError):
            self.run_import()
        self.assertEqual(self.count_transactions(), 2)

    def test_unrecognized_file_fails_and_names_the_file(self):
        """Verify that an unrecognized CSV file raises an error naming the file."""
        (self.csv_dir / "weird.csv").write_text("a,b,c\n1,2,3\n")
        with self.assertRaisesRegex(ValueError, r"weird\.csv.*unrecognized"):
            self.run_import()

    def test_missing_required_value_fails(self):
        """Verify that a row missing a required value raises a validation error."""
        self.write_tb("tb.csv", [tb_row(date="")])
        with self.assertRaisesRegex(ValueError, r"tb\.csv, row 2: .*booking_date"):
            self.run_import()
        self.assertEqual(self.count_transactions(), 0)

    def test_unknown_transaction_type_fails_the_file(self):
        """Verify that an unknown bank transaction type rejects the file."""
        self.write_fio("fio.csv", [fio_row(), fio_row({"Typ": "Novy typ"})])
        with self.assertRaisesRegex(ValueError, r"fio\.csv, row 3: Unknown transaction type"):
            self.run_import()
        self.assertEqual(self.count_transactions(), 0)

    def test_unsupported_currency_fails_the_file(self):
        """Verify that an unsupported currency raises an error and fails import."""
        self.write_tb("tb.csv", [tb_row(currency="XYZ")])
        with self.assertRaisesRegex(ValueError, r"tb\.csv, row 2: Unsupported currency"):
            self.run_import()

    # ------------------------------------------------------------------ symbols in payer_reference

    def test_tb_symbols_in_payer_reference_are_moved_into_columns(self):
        """Verify moving VS, SS, and KS tags from Tatra banka payer references into columns."""
        self.write_tb("tb.csv", [
            tb_row(tx_type="Debet", payer_reference="VS123/SS/KS"),
            tb_row(tx_type="Kredit", ks="308", payer_reference="/VS456/SS0000000000/KS0308"),
            tb_row(tx_type="Debet", payer_reference="?/VS789/SS1/KS2"),
            tb_row(tx_type="Debet", payer_reference="free text"),
            tb_row(tx_type="Debet", vs="55", payer_reference="/VS0055/SS/KS"),
        ])
        self.run_import()
        rows = self.query(f"SELECT {SYMBOL_COLUMNS} FROM transactions")
        self.assertCountEqual(
            [(r["variable_symbol"], r["specific_symbol"], r["constant_symbol"], r["payer_reference"])
             for r in rows],
            [
                ("123", None, None, None),
                ("456", "0000000000", "308", None),
                ("789", "1", "2", None),
                (None, None, None, "free text"),
                ("55", None, None, None),
            ],
        )

    def test_fio_symbols_in_payer_reference_are_moved_into_columns(self):
        """Verify moving VS, SS, and KS tags from FIO payer references into columns."""
        self.write_fio("fio.csv", [fio_row({
            ("VS", 1): "777", ("KS", 1): "308", "Referencia platiteľa": "/VS777/SS/KS0308",
        })])
        self.run_import()
        row = self.query(f"SELECT {SYMBOL_COLUMNS} FROM transactions")[0]
        self.assertEqual(
            (row["variable_symbol"], row["specific_symbol"], row["constant_symbol"], row["payer_reference"]),
            ("777", None, "308", None),
        )

    def test_symbol_conflict_fails_the_file(self):
        """Verify that conflicting symbols between columns and payer reference fail import."""
        self.write_tb("tb.csv", [tb_row(), tb_row(vs="2", payer_reference="/VS1/SS/KS")])
        with self.assertRaisesRegex(ValueError, r"tb\.csv, row 3: variable_symbol '2' conflicts"):
            self.run_import()
        self.assertEqual(self.count_transactions(), 0)


if __name__ == "__main__":
    unittest.main()
