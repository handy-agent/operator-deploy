import base64
import subprocess
import unittest

from common import image


class FakeRun:
    def __init__(self, outputs=None):
        self.calls = []
        self.outputs = outputs or {}

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        out = next((v for k, v in self.outputs.items() if k in " ".join(cmd)), "")
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")


class FakeEcr:
    def get_authorization_token(self):
        token = base64.b64encode(b"AWS:secret-pass").decode()
        return {"authorizationData": [{"authorizationToken": token,
                                       "proxyEndpoint": "https://123.dkr.ecr.us-east-1.amazonaws.com"}]}


class GitTagTest(unittest.TestCase):
    def test_clean(self):
        run = FakeRun({"rev-parse": "3f2a1c9\n", "status": ""})
        self.assertEqual(image.git_tag(run=run), "3f2a1c9")

    def test_dirty(self):
        run = FakeRun({"rev-parse": "3f2a1c9\n", "status": " M app/main.py\n"})
        self.assertEqual(image.git_tag(run=run), "3f2a1c9-dirty")


class BuildAndPushTest(unittest.TestCase):
    def test_build_is_arm64_from_operator_repo(self):
        cmd = image.build_command("repo:tag")
        self.assertIn("linux/arm64", cmd)
        self.assertEqual(cmd[-1], str(image.OPERATOR_DIR))
        self.assertIn(str(image.DOCKERFILE), cmd)

    def test_login_build_push(self):
        run = FakeRun()
        pushed = image.build_and_push(FakeEcr(), "operator-develop", "3f2a1c9", run=run)
        self.assertEqual(pushed, "123.dkr.ecr.us-east-1.amazonaws.com/operator-develop:3f2a1c9")
        login, build, push = (c[0] for c in run.calls)
        self.assertEqual(login[:2], ["docker", "login"])
        self.assertEqual(run.calls[0][1]["input"], "secret-pass")  # password via stdin, not argv
        self.assertNotIn("secret-pass", login)
        self.assertEqual(build[:3], ["docker", "buildx", "build"])
        self.assertEqual(push, ["docker", "push", pushed])


if __name__ == "__main__":
    unittest.main()
