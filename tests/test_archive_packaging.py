import tempfile
import unittest
import zipfile
from pathlib import Path

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
    def test_zip_contains_core_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            options = ArchiveOptions(
                workspace="w1", output=Path(td), start="2026-01-01T00:00:00Z", end="2026-09-25T00:00:00Z",
                receipts=False,
            )
            result = DummyArchiver(DummyClient(), options).run()
            self.assertTrue(result.zip_path.exists())
            with zipfile.ZipFile(result.zip_path) as zf:
                names = zf.namelist()
                self.assertTrue(any(n.endswith("/manifest.json") for n in names))
                self.assertTrue(any(n.endswith("/database/clockify.sqlite") for n in names))
                self.assertTrue(any(n.endswith("/csv/clockify_import_compatible.csv") for n in names))
                self.assertTrue(any(n.endswith("/SHA256SUMS") for n in names))


if __name__ == "__main__":
    unittest.main()
