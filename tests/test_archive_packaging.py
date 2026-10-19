import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timezone

from clockify_archive.archive import ArchiveOptions, Archiver


class DummyClient:
    base_url = "https://api.clockify.me/api/v1"


class DummyArchiver(Archiver):
    def resolve_workspace(self):
        return {"id": "w1", "name": "Test Workspace"}

    def collect(self, workspace_id):
        return {
            "workspace": {"id": "w1", "name": "Test Workspace"},
            "users": [{"id": "u1", "name": "Jane", "email": "j@example.com", "settings": {"timeZone": "UTC"}}],
            "clients": [], "projects": [], "tags": [], "user_groups": [], "custom_fields": [],
            "tasks_by_project": {}, "project_custom_fields": {}, "time_entries": [], "time_entries_by_user": {},
            "expense_categories": [], "expenses": [], "invoices": [], "approval_requests": [], "holidays": [],
            "time_off_policies": [], "time_off_requests": [], "time_off_balances_by_policy": {}, "deleted_entities": [],
        }

    def _download_receipts(self, root, wid, expenses):
        pass


class PackagingTests(unittest.TestCase):
    def _options(self, td, **kwargs):
        return ArchiveOptions(
            workspace="w1", output=Path(td), start="2026-01-01T00:00:00Z", end="2026-09-28T00:00:00Z",
            receipts=False, **kwargs,
        )

    def test_default_writes_directly_to_output_without_zip(self):
        with tempfile.TemporaryDirectory() as td:
            result = DummyArchiver(DummyClient(), self._options(td)).run()
            self.assertEqual(result.archive_dir, Path(td))
            self.assertIsNone(result.zip_path)
            self.assertTrue((Path(td) / "manifest.json").exists())
            self.assertTrue((Path(td) / "database" / "clockify.sqlite").exists())
            self.assertTrue((Path(td) / "csv" / "clockify_import_compatible.csv").exists())
            self.assertTrue((Path(td) / "SHA256SUMS").exists())
            self.assertEqual(list(Path(td).glob("clockify-test-workspace-*")), [])
            self.assertEqual(list(Path(td).glob("*.zip")), [])

    def test_default_preserves_unrelated_files(self):
        with tempfile.TemporaryDirectory() as td:
            keep = Path(td) / "keep-me.txt"
            keep.write_text("unrelated", encoding="utf-8")
            result = DummyArchiver(DummyClient(), self._options(td)).run()
            self.assertEqual(result.archive_dir, Path(td))
            self.assertEqual(keep.read_text(encoding="utf-8"), "unrelated")
            self.assertTrue((Path(td) / "manifest.json").exists())

    def test_direct_export_replaces_stale_managed_data(self):
        with tempfile.TemporaryDirectory() as td:
            stale = Path(td) / "raw" / "stale.json"
            stale.parent.mkdir(parents=True)
            stale.write_text("{}", encoding="utf-8")
            DummyArchiver(DummyClient(), self._options(td, raw=False)).run()
            self.assertFalse((Path(td) / "raw").exists())

    def test_zip_option_creates_zip_inside_direct_output(self):
        with tempfile.TemporaryDirectory() as td:
            fixed = datetime(2026, 9, 28, 15, 6, 7, tzinfo=timezone.utc)
            with patch("clockify_archive.archive.utc_now", return_value=fixed):
                result = DummyArchiver(DummyClient(), self._options(td, create_zip=True)).run()
            self.assertEqual(result.archive_dir, Path(td))
            self.assertEqual(result.zip_path, Path(td) / "clockify-test-workspace-20260928-150607.zip")
            self.assertTrue(result.zip_path.exists())
            with zipfile.ZipFile(result.zip_path) as zf:
                names = zf.namelist()
                self.assertIn("manifest.json", names)
                self.assertIn("database/clockify.sqlite", names)
                self.assertIn("csv/clockify_import_compatible.csv", names)
                self.assertIn("SHA256SUMS", names)
                self.assertFalse(any(n.startswith("clockify-test-workspace-") for n in names))

    def test_date_subdirs_write_directly_to_day_directory(self):
        with tempfile.TemporaryDirectory() as td:
            fixed = datetime(2026, 9, 28, 15, 6, 7, tzinfo=timezone.utc)
            with patch("clockify_archive.archive.utc_now", return_value=fixed):
                result = DummyArchiver(DummyClient(), self._options(td, date_subdirs=True)).run()
            expected = Path(td) / "2026" / "09" / "28"
            self.assertEqual(result.archive_dir, expected)
            self.assertTrue((expected / "manifest.json").exists())
            self.assertEqual(list(expected.glob("clockify-test-workspace-*")), [])

    def test_date_subdirs_and_zip_put_zip_in_day_directory(self):
        with tempfile.TemporaryDirectory() as td:
            fixed = datetime(2026, 9, 28, 15, 6, 7, tzinfo=timezone.utc)
            with patch("clockify_archive.archive.utc_now", return_value=fixed):
                result = DummyArchiver(DummyClient(), self._options(td, date_subdirs=True, create_zip=True)).run()
            expected = Path(td) / "2026" / "09" / "28"
            self.assertEqual(result.archive_dir, expected)
            self.assertEqual(result.zip_path.parent, expected)
            self.assertTrue(result.zip_path.exists())

    def test_archive_subdir_restores_named_wrapper(self):
        with tempfile.TemporaryDirectory() as td:
            fixed = datetime(2026, 9, 28, 15, 6, 7, tzinfo=timezone.utc)
            with patch("clockify_archive.archive.utc_now", return_value=fixed):
                result = DummyArchiver(DummyClient(), self._options(td, archive_subdir=True)).run()
            expected = Path(td) / "clockify-test-workspace-20260928-150607"
            self.assertEqual(result.archive_dir, expected)
            self.assertTrue((expected / "manifest.json").exists())

    def test_archive_subdir_with_zip_keeps_zip_beside_wrapper(self):
        with tempfile.TemporaryDirectory() as td:
            fixed = datetime(2026, 9, 28, 15, 6, 7, tzinfo=timezone.utc)
            with patch("clockify_archive.archive.utc_now", return_value=fixed):
                result = DummyArchiver(DummyClient(), self._options(td, archive_subdir=True, create_zip=True)).run()
            expected_dir = Path(td) / "clockify-test-workspace-20260928-150607"
            expected_zip = Path(td) / "clockify-test-workspace-20260928-150607.zip"
            self.assertEqual(result.archive_dir, expected_dir)
            self.assertEqual(result.zip_path, expected_zip)
            with zipfile.ZipFile(expected_zip) as zf:
                self.assertIn("clockify-test-workspace-20260928-150607/manifest.json", zf.namelist())

    def test_date_subdirs_and_archive_subdir_can_be_combined(self):
        with tempfile.TemporaryDirectory() as td:
            fixed = datetime(2026, 9, 28, 15, 6, 7, tzinfo=timezone.utc)
            with patch("clockify_archive.archive.utc_now", return_value=fixed):
                result = DummyArchiver(DummyClient(), self._options(td, date_subdirs=True, archive_subdir=True)).run()
            expected = Path(td) / "2026" / "09" / "28" / "clockify-test-workspace-20260928-150607"
            self.assertEqual(result.archive_dir, expected)
            self.assertTrue((expected / "manifest.json").exists())

    def test_explicit_zip_path_still_works_for_backward_compatibility(self):
        with tempfile.TemporaryDirectory() as td:
            explicit = Path(td) / "named-backup.zip"
            options = ArchiveOptions(
                workspace="w1", output=explicit, start="2026-01-01T00:00:00Z", end="2026-09-28T00:00:00Z",
                receipts=False,
            )
            result = DummyArchiver(DummyClient(), options).run()
            self.assertEqual(result.zip_path, explicit)
            self.assertTrue(explicit.exists())
            self.assertTrue(result.archive_dir.exists())
            self.assertEqual(result.archive_dir.name, "named-backup")


if __name__ == "__main__":
    unittest.main()
