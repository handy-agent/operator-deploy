import subprocess
import unittest

from common import local
from common.stage import Stage

STAGE = Stage(name="local", thumbtack_env="production", port=8000, dynamodb_port=8001)


class FakeRun:
    def __init__(self, create_output="Table operator-local: created\n", fail_first=0):
        self.calls = []
        self.create_output = create_output
        self.fail_first = fail_first

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        if "app.db.dynamo_table" in cmd and self.fail_first:
            self.fail_first -= 1
            raise subprocess.CalledProcessError(1, cmd)
        out = self.create_output if "app.db.dynamo_table" in cmd else ""
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")


class LocalTest(unittest.TestCase):
    def test_deploy_new_table_is_seeded(self):
        run, checked = FakeRun(), []
        local.deploy(STAGE, run=run, check=checked.append)
        compose, create, seed = (c[0] for c in run.calls)
        self.assertEqual(compose[-3:], ["up", "-d", "--build"])
        self.assertEqual(create[-3:], ["-m", "app.db.dynamo_table", "create"])
        self.assertEqual(seed[-2:], ["-m", "app.db.seed"])
        self.assertEqual(run.calls[1][1]["env"]["DYNAMODB_ENDPOINT_URL"], "http://localhost:8001")
        self.assertEqual(run.calls[1][1]["env"]["DYNAMODB_TABLE"], "operator-local")
        self.assertEqual(checked, ["http://localhost:8000"])

    def test_existing_table_is_not_reseeded(self):
        run = FakeRun(create_output="Table operator-local: already exists\n")
        local.deploy(STAGE, run=run, check=lambda url: None)
        self.assertEqual(len(run.calls), 2)

    def test_waits_for_dynamodb_local(self):
        run = FakeRun(fail_first=2)
        self.assertIn("created", local.create_table(STAGE, run=run, delay=0))

    def test_compose_env(self):
        env = local.compose_env(STAGE)
        self.assertEqual((env["PORT"], env["DYNAMODB_PORT"], env["DYNAMODB_TABLE"]), ("8000", "8001", "operator-local"))
        self.assertTrue(env["DOCKERFILE"].endswith("common/Dockerfile"))

    def test_remove_keeps_volume(self):
        run = FakeRun()
        local.remove(STAGE, run=run)
        self.assertEqual(run.calls[0][0][-1], "down")
        self.assertNotIn("-v", run.calls[0][0])


if __name__ == "__main__":
    unittest.main()
