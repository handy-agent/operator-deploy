import subprocess
import unittest
from unittest import mock

from common import aws
from common.stage import Stage


def develop(**env):
    return Stage(name="develop", thumbtack_env="staging", domain="dev-api.handyagent.dev",
                 instance_type="t4g.small", env=env)


class FakeRun:
    def __init__(self):
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


class FakeSsm:
    class exceptions:
        class InvocationDoesNotExist(Exception):
            pass

    def __init__(self, existing=None, statuses=("InProgress", "Success")):
        self.params = dict(existing or {})
        self.puts = []
        self.deleted = []
        self.statuses = list(statuses)
        self.sent = None

    def get_paginator(self, name):
        params = self.params

        class P:
            def paginate(self, Path, WithDecryption):
                yield {"Parameters": [{"Name": k, "Value": v} for k, v in params.items() if k.startswith(Path)]}

        return P()

    def add_tags_to_resource(self, **kw):
        self.tags = getattr(self, "tags", {})
        self.tags[kw["ResourceId"]] = kw["Tags"]

    def put_parameter(self, **kw):
        self.puts.append(kw)
        self.params[kw["Name"]] = kw["Value"]

    def delete_parameters(self, Names):
        self.deleted.extend(Names)

    def send_command(self, **kw):
        self.sent = kw
        return {"Command": {"CommandId": "cmd-1"}}

    def get_command_invocation(self, **kw):
        return {"Status": self.statuses.pop(0), "StandardErrorContent": "boom"}


class FakeEc2:
    def __init__(self, ids):
        self.ids = ids
        self.filters = None
        self.calls = []

    def stop_instances(self, InstanceIds):
        self.calls.append(("stop", InstanceIds))

    def start_instances(self, InstanceIds):
        self.calls.append(("start", InstanceIds))

    def get_waiter(self, name):
        calls = self.calls

        class W:
            def wait(self, InstanceIds):
                calls.append((name, InstanceIds))

        return W()

    def describe_instances(self, Filters):
        self.filters = Filters
        return {"Reservations": [{"Instances": [{"InstanceId": i} for i in self.ids]}]}


class FakeDynamo:
    def __init__(self, count):
        self.count = count

    def scan(self, **kw):
        return {"Count": self.count}


class FakeSession:
    def __init__(self, **clients):
        self.clients = clients

    def client(self, name):
        return self.clients[name]


class NodeEnvTest(unittest.TestCase):
    def test_uses_newest_nvm_node_when_npx_missing(self):
        import tempfile
        from pathlib import Path

        home = Path(tempfile.mkdtemp())
        for v in ("v20.1.0", "v22.23.3", "v9.0.0"):
            (home / ".nvm" / "versions" / "node" / v / "bin").mkdir(parents=True)
        env = aws.node_env({"PATH": "/nonexistent"}, home=home)
        self.assertTrue(env["PATH"].startswith(str(home / ".nvm/versions/node/v22.23.3/bin")))

    def test_no_node_at_all(self):
        import tempfile
        from pathlib import Path

        with self.assertRaisesRegex(RuntimeError, "install-tools"):
            aws.node_env({"PATH": "/nonexistent"}, home=Path(tempfile.mkdtemp()))


class EnvSyncTest(unittest.TestCase):
    def test_changes(self):
        put, delete = aws.env_changes({"A": "1", "B": "2"}, {"A": "1", "B": "old", "C": "x"})
        self.assertEqual(put, {"B": "2"})
        self.assertEqual(delete, ["C"])

    def test_sync_writes_plain_strings_under_env_path(self):
        ssm = FakeSsm({"/handyagent/operator/develop/env/GONE": "x", "/handyagent/operator/develop/secret/TOKEN": "keep"})
        aws.sync_env(ssm, develop(BUSINESS_NAME="Test Biz"))
        names = {p["Name"] for p in ssm.puts}
        self.assertIn("/handyagent/operator/develop/env/BUSINESS_NAME", names)
        self.assertIn("/handyagent/operator/develop/env/DYNAMODB_TABLE", names)
        self.assertTrue(all(p["Type"] == "String" for p in ssm.puts))
        self.assertEqual(ssm.deleted, ["/handyagent/operator/develop/env/GONE"])  # secrets untouched


class ServerAndRestartTest(unittest.TestCase):
    def test_finds_the_one_server(self):
        ec2 = FakeEc2(["i-1"])
        self.assertEqual(aws.server_id(ec2, develop()), "i-1")
        self.assertIn({"Name": "tag:Name", "Values": ["handyagent-operator-develop"]}, ec2.filters)

    def test_no_server_means_init_first(self):
        with self.assertRaisesRegex(RuntimeError, "ops.py start develop"):
            aws.server_id(FakeEc2([]), develop())

    def test_stop_waits_until_stopped(self):
        ec2 = FakeEc2(["i-1"])
        aws.stop(ec2, develop())
        self.assertEqual(ec2.calls, [("stop", ["i-1"]), ("instance_stopped", ["i-1"])])

    def test_start_looks_for_a_stopped_server(self):
        ec2 = FakeEc2(["i-1"])
        aws.start(ec2, develop())
        self.assertIn({"Name": "instance-state-name", "Values": ["stopped"]}, ec2.filters)
        self.assertEqual(ec2.calls, [("start", ["i-1"]), ("instance_running", ["i-1"])])

    def test_restart_waits_for_success(self):
        ssm = FakeSsm()
        aws.restart(ssm, "i-1", poll=0)
        self.assertEqual(ssm.sent["DocumentName"], "AWS-RunShellScript")
        self.assertIn("systemctl restart operator", ssm.sent["Parameters"]["commands"])

    def test_restart_failure(self):
        with self.assertRaisesRegex(RuntimeError, "restart failed"):
            aws.restart(FakeSsm(statuses=["Failed"]), "i-1", poll=0)


class InitTest(unittest.TestCase):
    def test_seeds_empty_table_with_operator_code(self):
        run = FakeRun()
        aws.init(develop(), FakeSession(dynamodb=FakeDynamo(0)), run=run)
        sst, seed = run.calls
        self.assertEqual(sst[0], ["npx", "sst", "deploy", "--stage", "develop"])
        self.assertEqual(seed[0][1:], ["-m", "app.db.seed"])
        self.assertEqual(seed[1]["env"]["DYNAMODB_TABLE"], "operator-develop")
        self.assertEqual(seed[1]["env"]["DYNAMODB_ENDPOINT_URL"], "")

    def test_does_not_seed_table_with_data(self):
        run = FakeRun()
        aws.init(develop(), FakeSession(dynamodb=FakeDynamo(1)), run=run)
        self.assertEqual(len(run.calls), 1)


class DeployTest(unittest.TestCase):
    def test_refuses_missing_secrets_before_touching_aws(self):
        with mock.patch.object(aws.secrets, "load", side_effect=RuntimeError("stages/develop/.env: fill X")):
            with self.assertRaisesRegex(RuntimeError, "fill X"):
                aws.deploy(develop(BUSINESS_NAME="Biz"), FakeSession())

    def test_refuses_blank_env(self):
        with self.assertRaisesRegex(RuntimeError, "BUSINESS_NAME"):
            aws.deploy(develop(BUSINESS_NAME=""), FakeSession())

    def test_order_env_image_tag_restart_smoke(self):
        ssm = FakeSsm()
        session = FakeSession(ssm=ssm, ecr=object(), ec2=FakeEc2(["i-1"]))
        with mock.patch.object(aws.secrets, "load", return_value={"TELEGRAM_BOT_TOKEN": "t"}), \
                mock.patch.object(aws.image, "git_tag", return_value="abc123"), \
                mock.patch.object(aws.image, "build_and_push", return_value="reg/operator-develop:abc123") as push, \
                mock.patch.object(aws, "restart") as restart, \
                mock.patch.object(aws.smoke, "check") as check:
            aws.deploy(develop(BUSINESS_NAME="Biz"), session)
        push.assert_called_once()
        self.assertEqual(push.call_args.args[1:], ("operator-develop", "abc123"))
        self.assertEqual(ssm.params["/handyagent/operator/develop/image-tag"], "abc123")
        self.assertEqual(ssm.params["/handyagent/operator/develop/secret/TELEGRAM_BOT_TOKEN"], "t")
        restart.assert_called_once_with(ssm, "i-1")
        check.assert_called_once_with("https://dev-api.handyagent.dev")


class RemoveAndSecretTest(unittest.TestCase):
    def test_never_removes_production(self):
        prod = Stage(name="production", thumbtack_env="production", domain="api.handyagent.dev")
        with self.assertRaisesRegex(RuntimeError, "never removed"):
            aws.remove(prod, run=FakeRun())

    def test_remove_develop(self):
        run = FakeRun()
        aws.remove(develop(), run=run)
        self.assertEqual(run.calls[0][0], ["npx", "sst", "remove", "--stage", "develop"])

    def test_secrets_sync_as_secure_strings_tagged(self):
        ssm = FakeSsm({"/handyagent/operator/develop/secret/OLD": "x"})
        aws.sync_secrets(ssm, develop(), {"TELEGRAM_BOT_TOKEN": "t0k"})
        self.assertEqual(ssm.puts[0]["Name"], "/handyagent/operator/develop/secret/TELEGRAM_BOT_TOKEN")
        self.assertEqual(ssm.puts[0]["Type"], "SecureString")
        self.assertEqual(ssm.tags["/handyagent/operator/develop/secret/TELEGRAM_BOT_TOKEN"],
                         [{"Key": "sst:project", "Value": "handyagent"}, {"Key": "sst:app", "Value": "operator"},
                          {"Key": "sst:stage", "Value": "develop"}])
        self.assertEqual(ssm.deleted, ["/handyagent/operator/develop/secret/OLD"])

    def test_unchanged_secret_is_not_rewritten(self):
        ssm = FakeSsm({"/handyagent/operator/develop/secret/TELEGRAM_BOT_TOKEN": "t0k"})
        aws.sync_secrets(ssm, develop(), {"TELEGRAM_BOT_TOKEN": "t0k"})
        self.assertEqual(ssm.puts, [])

if __name__ == "__main__":
    unittest.main()
