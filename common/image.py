# What it does: Builds the Operator image (common/Dockerfile, context = the operator repo) for the AWS
#   server (linux/arm64) and pushes it to the stage's ECR repo. Tag = the operator repo's short git commit,
#   with "-dirty" when it has uncommitted changes (so a tag never claims code it doesn't hold).
# When it runs: On every AWS deploy (stages/<stage>/deploy.sh).
# What calls it: ops.py (deploy); tests/test_image.py.
import base64
import subprocess
from pathlib import Path

from .stage import OPERATOR_DIR, ROOT

DOCKERFILE = ROOT / "common" / "Dockerfile"
PLATFORM = "linux/arm64"


def git_tag(repo: Path = OPERATOR_DIR, run=subprocess.run) -> str:
    sha = run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
              check=True, capture_output=True, text=True).stdout.strip()
    dirty = run(["git", "-C", str(repo), "status", "--porcelain"],
                check=True, capture_output=True, text=True).stdout.strip()
    return f"{sha}-dirty" if dirty else sha


def build_command(image: str, platform: str = PLATFORM) -> list[str]:
    return ["docker", "buildx", "build", "--platform", platform, "-f", str(DOCKERFILE),
            "-t", image, "--load", str(OPERATOR_DIR)]


def ecr_login(ecr, run=subprocess.run) -> str:
    """Logs docker in to ECR; returns the registry host."""
    auth = ecr.get_authorization_token()["authorizationData"][0]
    user, password = base64.b64decode(auth["authorizationToken"]).decode().split(":", 1)
    registry = auth["proxyEndpoint"].removeprefix("https://")
    run(["docker", "login", "--username", user, "--password-stdin", registry],
        input=password, text=True, check=True, capture_output=True)
    return registry


def build_and_push(ecr, repo_name: str, tag: str, run=subprocess.run) -> str:
    """Returns the pushed image reference."""
    registry = ecr_login(ecr, run=run)
    image = f"{registry}/{repo_name}:{tag}"
    run(build_command(image), check=True)
    run(["docker", "push", image], check=True)
    return image
