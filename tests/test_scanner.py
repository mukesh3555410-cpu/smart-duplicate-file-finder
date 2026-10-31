import csv
import tempfile
import threading
import unittest
from pathlib import Path

from core.reports import export_csv, export_txt
from core.scanner import scan_folder


class ScannerTests(unittest.TestCase):
    def test_detects_content_duplicates_and_calculates_extra_copy_savings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "alpha.txt").write_bytes(b"repeatA")
            (root / "renamed.bin").write_bytes(b"repeatA")
            (root / "one").mkdir()
            (root / "two").mkdir()
            (root / "one" / "same.txt").write_bytes(b"left")
            (root / "two" / "same.txt").write_bytes(b"right")
            for name in ("copy1.dat", "copy2.dat", "copy3.dat"):
                (root / name).write_bytes(b"other")
            (root / "unique").write_bytes(b"unique-size")
            (root / "empty").mkdir()

            result = scan_folder(root, True, threading.Event())

            self.assertEqual(result.files_scanned, 8)
            self.assertEqual(len(result.duplicate_groups), 2)
            self.assertEqual(result.extra_copies, 3)
            self.assertEqual(result.savings_bytes, 17)
            duplicate_paths = {record.path for group in result.duplicate_groups for record in group}
            self.assertNotIn((root / "one" / "same.txt").resolve(), duplicate_paths)
            self.assertNotIn((root / "two" / "same.txt").resolve(), duplicate_paths)
            self.assertEqual(result.errors, [])

    def test_non_recursive_scan_skips_nested_files_and_empty_folder_is_valid(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            child = root / "child"
            child.mkdir()
            (child / "copy-a").write_bytes(b"same")
            (child / "copy-b").write_bytes(b"same")
            result = scan_folder(root, False, threading.Event())
            self.assertEqual(result.files_scanned, 0)
            self.assertEqual(result.duplicate_groups, [])

            empty = root / "empty"
            empty.mkdir()
            empty_result = scan_folder(empty, True, threading.Event())
            self.assertEqual(empty_result.files_scanned, 0)
            self.assertEqual(empty_result.savings_bytes, 0)

    def test_exports_include_summary_and_duplicate_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "a.txt").write_bytes(b"identical")
            (root / "b.txt").write_bytes(b"identical")
            result = scan_folder(root, True, threading.Event())
            csv_path = export_csv(result, root / "report.csv")
            txt_path = export_txt(result, root / "report.txt")

            with csv_path.open(newline="", encoding="utf-8-sig") as stream:
                rows = list(csv.reader(stream))
            self.assertEqual(len(rows), 3)
            report = txt_path.read_text(encoding="utf-8")
            self.assertIn("Extra copies: 1", report)
            self.assertIn(str((root / "a.txt").resolve()), report)
            self.assertIn(str((root / "b.txt").resolve()), report)


if __name__ == "__main__":
    unittest.main()
