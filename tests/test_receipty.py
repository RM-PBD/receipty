import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from receipty import (
    ReceiptValidationError,
    build_filename,
    commit_receipt,
    preview_receipt,
    safe_path,
    validate_proposed_filename,
    validate_receipt_data,
)


VALID_DATA = {
    "date": "03/07/24",
    "what": "Server boosts",
    "business": "Discord, Inc.",
    "total": "$54.9",
    "currency": "usd",
}


class ReceiptDataTests(unittest.TestCase):
    def test_normalizes_all_filename_fields(self):
        self.assertEqual(
            validate_receipt_data(VALID_DATA),
            {
                "date": "3/7/24",
                "what": "Server_boosts",
                "business": "Discord_Inc",
                "total": "54.90",
                "currency": "USD",
            },
        )

    def test_builds_expected_foreign_currency_filename(self):
        self.assertEqual(
            build_filename(VALID_DATA, ".PDF"),
            "3_7_24_Server_boosts_Discord_Inc_54.90_USD.PDF",
        )

    def test_omits_gbp_suffix(self):
        data = VALID_DATA | {"currency": "GBP"}
        self.assertEqual(
            build_filename(data, ".jpg"),
            "3_7_24_Server_boosts_Discord_Inc_54.90.jpg",
        )

    def test_rejects_impossible_dates_and_unsafe_names(self):
        with self.assertRaises(ReceiptValidationError):
            validate_receipt_data(VALID_DATA | {"date": "31/2/24"})
        with self.assertRaises(ReceiptValidationError):
            validate_proposed_filename("../bad.pdf", ".pdf")

    def test_accepts_reviewed_standard_filename(self):
        name = "3_7_24_Server_Boosts_Discord_54.90_USD.pdf"
        self.assertEqual(validate_proposed_filename(name, ".pdf"), name)


class FileOperationTests(unittest.TestCase):
    def test_safe_path_adds_suffix(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "receipt.pdf").write_bytes(b"one")
            self.assertEqual(safe_path(path, "receipt.pdf").name, "receipt_2.pdf")

    @patch("receipty.analyze_receipt", return_value=VALID_DATA)
    def test_preview_never_changes_source(self, _analyze):
        result = preview_receipt(b"receipt", "source.pdf")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["action"], "preview")
        self.assertEqual(result["fingerprint"], hashlib.sha256(b"receipt").hexdigest())

    def test_commit_refuses_changed_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.pdf"
            source.write_bytes(b"changed")
            result = commit_receipt(
                filename=source.name,
                new_name="3_7_24_Server_Boosts_Discord_54.90_USD.pdf",
                source_dir=directory,
                mode="rename",
                expected_fingerprint=hashlib.sha256(b"original").hexdigest(),
            )
            self.assertEqual(result["status"], "error")
            self.assertTrue(source.exists())

    def test_commit_renames_and_preserves_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.pdf"
            source.write_bytes(b"receipt")
            new_name = "3_7_24_Server_Boosts_Discord_54.90_USD.pdf"
            result = commit_receipt(
                filename=source.name,
                new_name=new_name,
                source_dir=directory,
                mode="rename",
                expected_fingerprint=hashlib.sha256(b"receipt").hexdigest(),
            )
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["action"], "renamed")
            self.assertFalse(source.exists())
            self.assertEqual((Path(directory) / new_name).read_bytes(), b"receipt")

    def test_copy_collision_never_overwrites(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as output_dir:
            source = Path(source_dir) / "source.pdf"
            source.write_bytes(b"new")
            new_name = "3_7_24_Server_Boosts_Discord_54.90_USD.pdf"
            (Path(output_dir) / new_name).write_bytes(b"existing")
            result = commit_receipt(
                filename=source.name,
                new_name=new_name,
                source_dir=source_dir,
                mode="copy",
                output_dir=output_dir,
            )
            self.assertEqual(result["new_name"], "3_7_24_Server_Boosts_Discord_54.90_USD_2.pdf")
            self.assertEqual((Path(output_dir) / new_name).read_bytes(), b"existing")
            self.assertEqual((Path(output_dir) / result["new_name"]).read_bytes(), b"new")


if __name__ == "__main__":
    unittest.main()
