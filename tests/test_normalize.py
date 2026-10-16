import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from clockify_archive.normalize import IMPORT_COLUMNS, normalized_tables, write_all_csv, write_sqlite


FIXTURE = {
    "users": [{
        "id": "u1", "name": "Jane Doe", "email": "jane@example.com",
        "settings": {"timeZone": "Europe/Belgrade"}
    }],
    "clients": [{"id": "c1", "name": "Customer A"}],
    "projects": [{"id": "p1", "name": "Project A", "clientId": "c1"}],
    "tags": [{"id": "tag1", "name": "Meeting"}],
    "tasks_by_project": {"p1": [{"id": "t1", "name": "Development", "projectId": "p1"}]},
    "project_custom_fields": {},
    "user_groups": [],
    "custom_fields": [],
    "time_entries": [{
        "id": "te1", "workspaceId": "w1", "userId": "u1", "projectId": "p1", "taskId": "t1",
        "description": "Work", "tagIds": ["tag1"], "billable": True, "type": "REGULAR",
        "timeInterval": {"start": "2026-09-25T06:00:00Z", "end": "2026-09-25T14:00:00Z", "duration": "PT8H"},
        "customFieldValues": [{"customFieldId": "cf1", "value": "x"}],
    }],
    "expenses": [], "expense_categories": [], "invoices": [], "approval_requests": [], "holidays": [],
    "time_off_policies": [], "time_off_requests": [], "time_off_balances_by_policy": {},
}


class NormalizeTests(unittest.TestCase):
    def test_tables(self):
        tables = normalized_tables(FIXTURE)
        te = tables["time_entries"][0]
        self.assertEqual(te["duration_seconds"], 28800)
        self.assertEqual(te["client_name"], "Customer A")
        self.assertEqual(tables["time_entry_tags"][0]["tag_name"], "Meeting")
        imp = tables["clockify_import_compatible"][0]
        self.assertEqual(list(imp.keys()), IMPORT_COLUMNS)
        self.assertEqual(imp["Date"], "2026-09-25")
        self.assertEqual(imp["Start"], "08:00")
        self.assertEqual(imp["End"], "16:00")

    def test_csv_and_sqlite(self):
        tables = normalized_tables(FIXTURE)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_all_csv(root / "csv", tables)
            with (root / "csv" / "clockify_import_compatible.csv").open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                self.assertEqual(reader.fieldnames, IMPORT_COLUMNS)
                self.assertEqual(next(reader)["Project"], "Project A")

            db = root / "clockify.sqlite"
            write_sqlite(db, tables, {"format": "test", "counts": {"time_entries": 1}})
            con = sqlite3.connect(db)
            try:
                row = con.execute("SELECT user_name, duration_seconds FROM time_entries WHERE id='te1'").fetchone()
                self.assertEqual(row, ("Jane Doe", 28800))
            finally:
                con.close()


if __name__ == "__main__":
    unittest.main()
