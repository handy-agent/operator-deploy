import tempfile
import unittest
from pathlib import Path

from common import secrets
from common.stage import Stage

STAGE = Stage(name="develop", thumbtack_env="staging", domain="dev-api.handyagent.dev")
EXAMPLE = "# comment\nTELEGRAM_BOT_TOKEN=\nBASE_LATITUDE=\n# THUMBTACK_API_TOKEN=\n"


class SecretsTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "develop").mkdir()
        (self.dir / "develop" / ".env.example").write_text(EXAMPLE)

    def write_env(self, text):
        (self.dir / "develop" / ".env").write_text(text)

    def test_parse(self):
        self.assertEqual(secrets.parse('A=1\n# B=2\n\nC="x=y"\nD=\'q\'\n'), {"A": "1", "C": "x=y", "D": "q"})

    def test_missing_file_names_what_to_fill(self):
        with self.assertRaisesRegex(RuntimeError, "missing.*TELEGRAM_BOT_TOKEN, BASE_LATITUDE"):
            secrets.load(STAGE, self.dir)

    def test_empty_required_value(self):
        self.write_env("TELEGRAM_BOT_TOKEN=abc\nBASE_LATITUDE=\n")
        with self.assertRaisesRegex(RuntimeError, "fill BASE_LATITUDE"):
            secrets.load(STAGE, self.dir)

    def test_commented_names_are_optional_but_synced_when_set(self):
        self.write_env("TELEGRAM_BOT_TOKEN=abc\nBASE_LATITUDE=30.5\nTHUMBTACK_API_TOKEN=tt\n")
        self.assertEqual(secrets.load(STAGE, self.dir),
                         {"TELEGRAM_BOT_TOKEN": "abc", "BASE_LATITUDE": "30.5", "THUMBTACK_API_TOKEN": "tt"})

    def test_empty_optional_is_dropped(self):
        self.write_env("TELEGRAM_BOT_TOKEN=abc\nBASE_LATITUDE=30.5\nTHUMBTACK_API_TOKEN=\n")
        self.assertNotIn("THUMBTACK_API_TOKEN", secrets.load(STAGE, self.dir))

    def test_real_stage_examples_exist(self):
        for name in ("develop", "demo", "production"):
            required = secrets.parse((secrets.STAGES_DIR / name / ".env.example").read_text())
            self.assertIn("TELEGRAM_BOT_TOKEN", required)
            self.assertNotIn("THUMBTACK_API_TOKEN", required)


if __name__ == "__main__":
    unittest.main()
