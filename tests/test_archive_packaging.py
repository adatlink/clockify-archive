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

    def test_default_creates_directory_without_zip(self):
        with tempfile.TemporaryDirectory() as td:
            result = DummyArchiver(DummyClient(), self._options(td)).run()
            self.assertTrue(result.archive_dir.is_dir())
            self.assertIsNone(result.zip_path)
            self.assertTrue((result.archive_dir / "manifest.json").exists())
            self.assertTrue((result.archive_dir / "database" / "clockify.sqlite").exists())
            self.assertTrue((result.archive_dir / "csv" / "clockify_import_compatible.csv").exists())
            self.assertTrue((result.archive_dir / "SHA256SUMS").exists())
            self.assertEqual(list(Path(td).glob("*.zip")), [])

    def test_zip_option_creates_zip_and_keeps_directory(self):
        with tempfile.TemporaryDirectory() as td:
            result = DummyArchiver(DummyClient(), self._options(td, create_zip=True)).run()
            self.assertTrue(result.archive_dir.is_dir())
            self.assertIsNotNone(result.zip_path)
            self.assertTrue(result.zip_path.exists())
            with zipfile.ZipFile(result.zip_path) as zf:
                names = zf.namelist()
                self.assertTrue(any(n.endswith("/manifest.json") for n in names))
                self.assertTrue(any(n.endswith("/database/clockify.sqlite") for n in names))
                self.assertTrue(any(n.endswith("/csv/clockify_import_compatible.csv") for n in names))
                self.assertTrue(any(n.endswith("/SHA256SUMS") for n in names))

    def test_date_subdirs_use_export_date(self):
        with tempfile.TemporaryDirectory() as td:
            fixed = datetime(2026, 9, 28, 15, 6, 7, tzinfo=timezone.utc)
            with patch("clockify_archive.archive.utc_now", return_value=fixed):
                result = DummyArchiver(DummyClient(), self._options(td, date_subdirs=True)).run()
            expected_parent = Path(td) / "2026" / "09" / "28"
            self.assertEqual(result.archive_dir.parent, expected_parent)
            self.assertEqual(result.archive_dir.name, "clockify-test-workspace-20260928-150607")
            self.assertTrue(result.archive_dir.exists())

    def test_date_subdirs_and_zip_put_both_in_same_day_directory(self):
        with tempfile.TemporaryDirectory() as td:
            fixed = datetime(2026, 9, 28, 15, 6, 7, tzinfo=timezone.utc)
            with patch("clockify_archive.archive.utc_now", return_value=fixed):
                result = DummyArchiver(DummyClient(), self._options(td, date_subdirs=True, create_zip=True)).run()
            expected_parent = Path(td) / "2026" / "09" / "28"
            self.assertEqual(result.archive_dir.parent, expected_parent)
            self.assertEqual(result.zip_path.parent, expected_parent)
            self.assertTrue(result.zip_path.exists())

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
