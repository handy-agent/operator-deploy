import tempfile
import unittest
from pathlib import Path

from common import stage as stages


def write_stage(root: Path, name: str, text: str) -> None:
    (root / name).mkdir(parents=True)
    (root / name / "stage.yaml").write_text(text)


class RealStageFilesTest(unittest.TestCase):
    def test_all_stage_files_load(self):
        for name in ("local", *stages.AWS_STAGES):
            self.assertEqual(stages.load(name).name, name)

    def test_aws_domains(self):
        self.assertEqual(stages.load("develop").domain, "dev-api.handyagent.dev")
        self.assertEqual(stages.load("demo").domain, "demo-api.handyagent.dev")
        self.assertEqual(stages.load("production").domain, "api.handyagent.dev")

    def test_thumbtack_env(self):
        self.assertEqual(stages.load("develop").thumbtack_env, "staging")
        self.assertEqual(stages.load("demo").thumbtack_env, "staging")
        self.assertEqual(stages.load("production").thumbtack_env, "production")

    def test_only_production_has_backups(self):
        self.assertTrue(stages.load("production").backups)
        self.assertFalse(stages.load("develop").backups)


class LoadTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_unknown_stage(self):
        with self.assertRaises(ValueError):
            stages.load("staging", self.dir)

    def test_name_must_match_folder(self):
        write_stage(self.dir, "demo", "name: develop\nthumbtack_env: staging\ndomain: x\ninstance_type: t4g.small\n")
        with self.assertRaisesRegex(ValueError, "expected 'demo'"):
            stages.load("demo", self.dir)

    def test_aws_stage_needs_domain(self):
        write_stage(self.dir, "demo", "name: demo\nthumbtack_env: staging\ninstance_type: t4g.small\n")
        with self.assertRaisesRegex(ValueError, "domain"):
            stages.load("demo", self.dir)

    def test_bad_thumbtack_env(self):
        write_stage(self.dir, "demo", "name: demo\nthumbtack_env: prod\ndomain: x\ninstance_type: t\n")
        with self.assertRaisesRegex(ValueError, "thumbtack_env"):
            stages.load("demo", self.dir)

    def test_blank_env_values_become_empty_strings(self):
        write_stage(self.dir, "demo", "name: demo\nthumbtack_env: staging\ndomain: x\ninstance_type: t\n"
                                      "env:\n  BUSINESS_NAME:\n  OPERATOR_ACCOUNT_ID: acc-1\n")
        s = stages.load("demo", self.dir)
        self.assertEqual(s.env, {"BUSINESS_NAME": "", "OPERATOR_ACCOUNT_ID": "acc-1"})
        self.assertEqual(s.empty_env(), ["BUSINESS_NAME"])


class NamesAndEnvTest(unittest.TestCase):
    def test_names(self):
        s = stages.Stage(name="develop", thumbtack_env="staging", domain="dev-api.handyagent.dev")
        self.assertEqual(s.table, "operator-develop")
        self.assertEqual(s.ecr_repo, "operator-develop")
        self.assertEqual(s.server_name, "handyagent-operator-develop")
        self.assertEqual(s.env_path, "/handyagent/operator/develop/env/")
        self.assertEqual(s.secret_path, "/handyagent/operator/develop/secret/")
        self.assertEqual(s.image_tag_param, "/handyagent/operator/develop/image-tag")
        self.assertEqual(s.base_url, "https://dev-api.handyagent.dev")

    def test_aws_app_env(self):
        s = stages.Stage(name="production", thumbtack_env="production", domain="api.handyagent.dev",
                         env={"BUSINESS_NAME": "ATX Handy Pros"})
        env = s.app_env()
        self.assertEqual(env["BUSINESS_NAME"], "ATX Handy Pros")
        self.assertEqual(env["DYNAMODB_TABLE"], "operator-production")
        self.assertEqual(env["DB_BACKEND"], "dynamodb")
        self.assertEqual(env["THUMBTACK_API_BASE_URL"], "https://api.thumbtack.com")
        self.assertEqual(env["TELEGRAM_WEBHOOK_URL"], "https://api.handyagent.dev")
        self.assertEqual(env["CLAUDE_CODE_USE_ANTHROPIC_AWS"], "1")
        self.assertNotIn("DYNAMODB_ENDPOINT_URL", env)

    def test_derived_env_wins_over_stage_yaml(self):
        s = stages.Stage(name="develop", thumbtack_env="staging", domain="d", env={"DYNAMODB_TABLE": "other"})
        self.assertEqual(s.app_env()["DYNAMODB_TABLE"], "operator-develop")

    def test_local_has_no_webhook_url(self):
        s = stages.Stage(name="local", thumbtack_env="production", port=8000, dynamodb_port=8001)
        self.assertNotIn("TELEGRAM_WEBHOOK_URL", s.app_env())
        self.assertEqual(s.base_url, "http://localhost:8000")


if __name__ == "__main__":
    unittest.main()
