import unittest

from clockify_archive.util import iso8601_duration_seconds, normalize_datetime_arg


class UtilTests(unittest.TestCase):
    def test_duration(self):
        self.assertEqual(iso8601_duration_seconds("PT1H30M"), 5400)
        self.assertEqual(iso8601_duration_seconds("P1DT2H3M4S"), 93784)
        self.assertEqual(iso8601_duration_seconds("PT0S"), 0)

    def test_date_args(self):
        self.assertEqual(normalize_datetime_arg("2026-09-25"), "2026-09-25T00:00:00Z")
        self.assertEqual(normalize_datetime_arg("2026-09-25", end_of_day=True), "2026-09-25T23:59:59Z")


if __name__ == "__main__":
    unittest.main()
