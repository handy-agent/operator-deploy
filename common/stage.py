# What it does: Loads a stage's settings from stages/<stage>/stage.yaml and derives everything named
#   after the stage (DynamoDB table, ECR repo, SSM paths, the server's Name tag) plus the app env the
#   server runs with. One place for names, so ops.py and sst.config.ts never disagree (sst.config.ts
#   uses the same convention: operator-<stage>, /handyagent/operator/<stage>/...).
# When it runs: At the start of every ops.py command.
# What calls it: ops.py, common/aws.py, common/local.py, tests/test_stage.py.
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
STAGES_DIR = ROOT / "stages"
# The code repo, cloned next to this one (~/handy-agent/operator).
OPERATOR_DIR = ROOT.parent / "operator"

AWS_STAGES = ("develop", "demo", "production")
LOCAL = "local"
REGION = "us-east-1"
# Tags: only the sst: namespace (Roman, 2026-10-03). SST tags what it creates with sst:app + sst:stage, and
# sst.config.ts adds sst:project; ops.py gives the SSM parameters it writes the same set (Stage.tags).
PROJECT_TAG = {"sst:project": "handyagent", "sst:app": "operator"}
THUMBTACK_API = {
    "staging": "https://staging-api.thumbtack.com",
    "production": "https://api.thumbtack.com",
}


@dataclass(frozen=True)
class Stage:
    name: str
    thumbtack_env: str
    domain: str | None = None
    instance_type: str | None = None
    backups: bool = False
    port: int | None = None
    dynamodb_port: int | None = None
    env: dict[str, str] = field(default_factory=dict)

    @property
    def is_aws(self) -> bool:
        return self.name in AWS_STAGES

    @property
    def table(self) -> str:
        return f"operator-{self.name}"

    @property
    def ecr_repo(self) -> str:
        return f"operator-{self.name}"

    @property
    def server_name(self) -> str:
        """The EC2 server's Name tag (sst.config.ts sets it)."""
        return f"handyagent-operator-{self.name}"

    @property
    def env_path(self) -> str:
        """SSM path of the non-secret app env (written by ops.py on deploy)."""
        return f"/handyagent/operator/{self.name}/env/"

    @property
    def secret_path(self) -> str:
        """SSM path of the secrets (SecureString, synced by deploy from stages/<stage>/.env)."""
        return f"/handyagent/operator/{self.name}/secret/"

    @property
    def image_tag_param(self) -> str:
        """SSM parameter holding the image tag the server runs."""
        return f"/handyagent/operator/{self.name}/image-tag"

    @property
    def tags(self) -> dict[str, str]:
        return {**PROJECT_TAG, "sst:stage": self.name}

    @property
    def base_url(self) -> str:
        if self.is_aws:
            return f"https://{self.domain}"
        return f"http://localhost:{self.port}"

    def app_env(self) -> dict[str, str]:
        """The full non-secret env the app runs with: stage.yaml `env` plus what the stage implies."""
        derived = {
            "DB_BACKEND": "dynamodb",
            "DYNAMODB_TABLE": self.table,
            "AWS_REGION": REGION,
            "THUMBTACK_API_BASE_URL": THUMBTACK_API[self.thumbtack_env],
        }
        if self.is_aws:
            # Telegram calls us (webhook) instead of being polled; Claude via Claude Platform on AWS (IAM role).
            derived["TELEGRAM_WEBHOOK_URL"] = self.base_url
            derived["CLAUDE_CODE_USE_ANTHROPIC_AWS"] = "1"
        return {**self.env, **derived}

    def empty_env(self) -> list[str]:
        """stage.yaml `env` keys still blank — the app would fail on them, so deploy refuses."""
        return sorted(k for k, v in self.env.items() if not v.strip())


def load(name: str, stages_dir: Path = STAGES_DIR) -> Stage:
    if name not in (LOCAL, *AWS_STAGES):
        raise ValueError(f"unknown stage '{name}' (expected {LOCAL}|{'|'.join(AWS_STAGES)})")
    data: dict[str, Any] = yaml.safe_load((stages_dir / name / "stage.yaml").read_text()) or {}
    if data.get("name") != name:
        raise ValueError(f"stages/{name}/stage.yaml: name is '{data.get('name')}', expected '{name}'")
    if data.get("thumbtack_env") not in THUMBTACK_API:
        raise ValueError(f"stages/{name}/stage.yaml: thumbtack_env must be staging or production")
    if name in AWS_STAGES:
        for key in ("domain", "instance_type"):
            if not data.get(key):
                raise ValueError(f"stages/{name}/stage.yaml: {key} is required")
    else:
        for key in ("port", "dynamodb_port"):
            if not data.get(key):
                raise ValueError(f"stages/{name}/stage.yaml: {key} is required")
    env = {k: "" if v is None else str(v) for k, v in (data.get("env") or {}).items()}
    return Stage(
        name=name,
        thumbtack_env=data["thumbtack_env"],
        domain=data.get("domain"),
        instance_type=data.get("instance_type"),
        backups=bool(data.get("backups", False)),
        port=data.get("port"),
        dynamodb_port=data.get("dynamodb_port"),
        env=env,
    )
