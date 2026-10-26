"""Tests for stable transaction fingerprints used by finance metadata links."""

import re
import unittest

# noinspection PyProtectedMember
from src.importer import (
    FIO_HEADERS,
    TRANSACTION_ID_COLUMNS_V1,
    _parse_transaction_row,
    generate_transaction_id,
)
from tests.support import fio_row


def sample_record():
    """Parse a representative synthetic Fio record for hash tests.

    Returns:
        Normalized transaction record built from dummy data.
    """
    return _parse_transaction_row("FIO", FIO_HEADERS, fio_row())


class TransactionIdTests(unittest.TestCase):
    """Verify the stability and input validation of transaction fingerprints."""

    def test_id_is_a_lowercase_sha256_hex_digest(self):
        """Return IDs as lowercase 64-character SHA-256 digests."""
        self.assertRegex(generate_transaction_id(sample_record()), re.compile(r"^[0-9a-f]{64}$"))

    def test_same_normalized_record_has_same_id(self):
        """Produce the same fingerprint for the same normalized record."""
        self.assertEqual(generate_transaction_id(sample_record()), generate_transaction_id(sample_record()))

    def test_each_fingerprinted_field_changes_the_id(self):
        """Include every declared fingerprint field in the generated ID."""
        record = sample_record()
        original = generate_transaction_id(record)
        for field in TRANSACTION_ID_COLUMNS_V1:
            changed = dict(record)
            changed[field] = "different-value"
            with self.subTest(field=field):
                self.assertNotEqual(generate_transaction_id(changed), original)

    def test_missing_fingerprinted_field_is_rejected(self):
        """Reject records missing a field required by the fingerprint version."""
        record = sample_record()
        del record[TRANSACTION_ID_COLUMNS_V1[0]]
        with self.assertRaises(KeyError):
            generate_transaction_id(record)


if __name__ == "__main__":
    unittest.main()
