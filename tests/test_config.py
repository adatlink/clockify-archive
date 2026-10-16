import tempfile
import unittest
from pathlib import Path

from clockify_archive.config import load_settings, write_example_config


class ConfigTests(unittest.TestCase):
    def test_example_config_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.toml"
            write_example_config(path)
            text = path.read_text(encoding="utf-8")
            self.assertIn("[clockify]", text)
            self.assertIn("YOUR_CLOCKIFY_API_KEY", text)
            settings = load_settings(str(path))
            self.assertEqual(settings.base_url, "https://api.clockify.me/api/v1")


if __name__ == "__main__":
    unittest.main()
