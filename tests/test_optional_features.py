import tempfile
import unittest
from pathlib import Path

from clockify_archive.api import ClockifyAPIError
from clockify_archive.archive import ArchiveOptions, Archiver


class DummyClient:
    base_url = "https://api.clockify.me/api/v1"


class OptionalFeatureTests(unittest.TestCase):
    def _archiver(self, *, strict=False, verbose=False):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        options = ArchiveOptions(
            workspace="w1",
            output=Path(td.name),
            start="2026-01-01T00:00:00Z",
            end="2026-09-25T00:00:00Z",
            strict=strict,
            verbose=verbose,
        )
        return Archiver(DummyClient(), options)

    def test_repeated_403_is_cached_per_feature(self):
        archiver = self._archiver()
        calls = 0

        def forbidden():
            nonlocal calls
            calls += 1
            raise ClockifyAPIError(403, "Forbidden", "https://example.invalid")

        first = archiver._optional(
            "project custom fields for p1",
            forbidden,
            [],
            feature="project_custom_fields",
            feature_label="project custom fields",
        )
        second = archiver._optional(
            "project custom fields for p2",
            forbidden,
            [],
            feature="project_custom_fields",
            feature_label="project custom fields",
        )

        self.assertEqual(first, [])
        self.assertEqual(second, [])
        self.assertEqual(calls, 1)
        self.assertEqual(len(archiver.warnings), 1)
        self.assertEqual(
            archiver.unavailable_features["project_custom_fields"]["http_status"],
            403,
        )

    def test_404_is_not_cached_as_workspace_wide_feature_failure(self):
        archiver = self._archiver()
        calls = 0

        def missing():
            nonlocal calls
            calls += 1
            raise ClockifyAPIError(404, "Not Found", "https://example.invalid")

        archiver._optional(
            "expense receipt e1/f1",
            missing,
            None,
            feature="expense_receipts",
            feature_label="expense receipt downloads",
        )
        archiver._optional(
            "expense receipt e2/f2",
            missing,
            None,
            feature="expense_receipts",
            feature_label="expense receipt downloads",
        )

        self.assertEqual(calls, 2)
        self.assertEqual(len(archiver.warnings), 2)
        self.assertNotIn("expense_receipts", archiver.unavailable_features)

    def test_strict_mode_still_raises(self):
        archiver = self._archiver(strict=True)

        def forbidden():
            raise ClockifyAPIError(403, "Forbidden", "https://example.invalid")

        with self.assertRaises(ClockifyAPIError):
            archiver._optional(
                "project custom fields for p1",
                forbidden,
                [],
                feature="project_custom_fields",
                feature_label="project custom fields",
            )
        self.assertEqual(archiver.warnings, [])
        self.assertEqual(archiver.unavailable_features, {})


if __name__ == "__main__":
    unittest.main()
