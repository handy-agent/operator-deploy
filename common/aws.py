# What it does: AWS steps for a stage (develop/demo/production):
#   init    — `sst deploy --stage <stage>` (infra: sst.config.ts), then seeds DynamoDB if the table is empty
#             (calls the operator repo's own seeding, app/db/seed.py — not copied here).
#   deploy  — code only: checks stages/<stage>/.env secrets (common/secrets.py), syncs the app env
#             (stage.yaml, String) and the secrets (SecureString) to SSM, builds + pushes the image, sets the
#             image tag in SSM, restarts Operator on the server through SSM Run Command, smoke test.
#   remove  — `sst remove --stage <stage>` (develop/demo only; ops.py refuses production).
#   stop / start — stop the server to save money while idle (disk and data kept), start it again.
#   AWS credentials: the usual chain (AWS_PROFILE from .env). Cloudflare: CLOUDFLARE_API_TOKEN for sst.
# When it runs: When stages/<stage>/{init,deploy,remove}.sh run.
# What calls it: ops.py; tests/test_aws.py.
import os
import shutil
import subprocess
import time
from pathlib import Path

from . import image, secrets, smoke
from .stage import OPERATOR_DIR, REGION, ROOT, Stage


def node_env(env: dict[str, str] | None = None, home: Path = Path.home()) -> dict[str, str]:
    """env with Node on PATH: if npx isn't there, the newest nvm-installed Node (install-tools.sh)."""
    env = dict(os.environ if env is None else env)
    if shutil.which("npx", path=env.get("PATH")):
        return env
    versions = sorted((home / ".nvm" / "versions" / "node").glob("v*/bin"),
                      key=lambda p: [int(x) for x in p.parent.name[1:].split(".")])
    if not versions:
        raise RuntimeError("Node not found: run install-tools.sh")
    env["PATH"] = f"{versions[-1]}{os.pathsep}{env.get('PATH', '')}"
    return env


def _sst(command: str, stage: Stage, run=subprocess.run) -> None:
    run(["npx", "sst", command, "--stage", stage.name], cwd=ROOT, env=node_env(), check=True)


def table_is_empty(dynamodb, table: str) -> bool:
    return dynamodb.scan(TableName=table, Limit=1, Select="COUNT")["Count"] == 0


def seed(stage: Stage, run=subprocess.run) -> None:
    """Runs the operator repo's seeding (python -m app.db.seed) against the stage's real table."""
    env = {**os.environ, "DB_BACKEND": "dynamodb", "DYNAMODB_TABLE": stage.table,
           "DYNAMODB_ENDPOINT_URL": "", "AWS_REGION": REGION}
    run([str(OPERATOR_DIR / ".venv" / "bin" / "python"), "-m", "app.db.seed"],
        cwd=OPERATOR_DIR, env=env, check=True)


def init(stage: Stage, session, run=subprocess.run) -> None:
    _sst("deploy", stage, run=run)
    if table_is_empty(session.client("dynamodb"), stage.table):
        print(f"{stage.table} is empty: seeding")
        seed(stage, run=run)
    else:
        print(f"{stage.table} has data: not seeding")
    print(f"init done. Next: stages/{stage.name}/deploy.sh")


def put_param(ssm, stage: Stage, name: str, value: str, kind: str = "String") -> None:
    """Writes an SSM parameter and tags it (AWS refuses Tags together with Overwrite, so tag after)."""
    ssm.put_parameter(Name=name, Value=value, Type=kind, Overwrite=True)
    ssm.add_tags_to_resource(ResourceType="Parameter", ResourceId=name,
                             Tags=[{"Key": k, "Value": v} for k, v in stage.tags.items()])


def env_changes(wanted: dict[str, str], current: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """(params to put, param names to delete) to make SSM hold exactly `wanted`."""
    put = {k: v for k, v in wanted.items() if current.get(k) != v}
    delete = sorted(k for k in current if k not in wanted)
    return put, delete


def _params_by_path(ssm, path: str) -> dict[str, str]:
    out = {}
    for page in ssm.get_paginator("get_parameters_by_path").paginate(Path=path, WithDecryption=True):
        for p in page["Parameters"]:
            out[p["Name"].removeprefix(path)] = p["Value"]
    return out


def sync_params(ssm, stage: Stage, path: str, wanted: dict[str, str], kind: str, label: str) -> None:
    """Makes SSM under `path` hold exactly `wanted` (puts changed values, deletes extra names)."""
    put, delete = env_changes(wanted, _params_by_path(ssm, path))
    for name, value in put.items():
        put_param(ssm, stage, path + name, value, kind)
    for start in range(0, len(delete), 10):
        ssm.delete_parameters(Names=[path + n for n in delete[start:start + 10]])
    print(f"{label}: {len(put)} set, {len(delete)} removed")


def sync_env(ssm, stage: Stage) -> None:
    sync_params(ssm, stage, stage.env_path, stage.app_env(), "String", "env")


def sync_secrets(ssm, stage: Stage, values: dict[str, str]) -> None:
    sync_params(ssm, stage, stage.secret_path, values, "SecureString", "secrets")


def server_id(ec2, stage: Stage, states: tuple[str, ...] = ("running",)) -> str:
    reservations = ec2.describe_instances(Filters=[
        {"Name": "tag:Name", "Values": [stage.server_name]},
        {"Name": "instance-state-name", "Values": list(states)},
    ])["Reservations"]
    ids = [i["InstanceId"] for r in reservations for i in r["Instances"]]
    if len(ids) != 1:
        raise RuntimeError(f"expected 1 {'/'.join(states)} server '{stage.server_name}', found {len(ids)} — "
                           f"stopped? run `ops.py start {stage.name}`; none at all? run init")
    return ids[0]


def stop(ec2, stage: Stage) -> None:
    instance_id = server_id(ec2, stage)
    ec2.stop_instances(InstanceIds=[instance_id])
    ec2.get_waiter("instance_stopped").wait(InstanceIds=[instance_id])
    print(f"stopped {stage.server_name} ({instance_id}). Start again: ops.py start {stage.name}")


def start(ec2, stage: Stage) -> None:
    instance_id = server_id(ec2, stage, states=("stopped",))
    ec2.start_instances(InstanceIds=[instance_id])
    ec2.get_waiter("instance_running").wait(InstanceIds=[instance_id])
    print(f"started {stage.server_name} ({instance_id})")


def restart(ssm, instance_id: str, timeout: float = 300, poll: float = 5) -> None:
    """Restarts Operator on the server (it pulls the image tag from SSM on start: common/server/)."""
    command_id = ssm.send_command(
        InstanceIds=[instance_id], DocumentName="AWS-RunShellScript",
        Parameters={"commands": ["systemctl restart operator", "systemctl is-active operator"]},
    )["Command"]["CommandId"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(poll)
        try:
            result = ssm.get_command_invocation(CommandId=command_id, InstanceId=instance_id)
        except ssm.exceptions.InvocationDoesNotExist:
            continue
        if result["Status"] in ("Pending", "InProgress", "Delayed"):
            continue
        if result["Status"] != "Success":
            raise RuntimeError(f"restart failed ({result['Status']}): {result.get('StandardErrorContent', '')}")
        return
    raise RuntimeError(f"restart did not finish in {timeout}s (command {command_id})")


def deploy(stage: Stage, session, run=subprocess.run) -> None:
    if empty := stage.empty_env():
        raise RuntimeError(f"stages/{stage.name}/stage.yaml: fill env before deploy: {', '.join(empty)}")
    stage_secrets = secrets.load(stage)
    ssm = session.client("ssm")
    sync_env(ssm, stage)
    sync_secrets(ssm, stage, stage_secrets)
    tag = image.git_tag(run=run)
    pushed = image.build_and_push(session.client("ecr"), stage.ecr_repo, tag, run=run)
    put_param(ssm, stage, stage.image_tag_param, tag)
    print(f"image: {pushed}")
    restart(ssm, server_id(session.client("ec2"), stage))
    smoke.check(stage.base_url)


def remove(stage: Stage, run=subprocess.run) -> None:
    if stage.name == "production":
        raise RuntimeError("production is never removed by script")
    _sst("remove", stage, run=run)

