# What it does: The local stage (stages/local/): Operator + DynamoDB Local in Docker Compose.
#   deploy — build + start (docker compose up -d --build), create the table if missing and seed it when
#            new (both via the operator repo's own code: app/db/dynamo_table.py, app/db/seed.py), smoke test.
#   remove — stop and delete the containers; DynamoDB data stays on its volume.
#   seed   — reload db/seed/ into the local table (safe to rerun).
# When it runs: stages/local/{deploy,remove,seed}.sh.
# What calls it: ops.py; tests/test_local.py.
import os
import subprocess
import time

from . import smoke
from .stage import OPERATOR_DIR, ROOT, Stage

COMPOSE_FILE = ROOT / "stages" / "local" / "docker-compose.yml"


def compose_env(stage: Stage) -> dict[str, str]:
    return {**os.environ, "PORT": str(stage.port), "DYNAMODB_PORT": str(stage.dynamodb_port),
            "DYNAMODB_TABLE": stage.table, "DOCKERFILE": str(ROOT / "common" / "Dockerfile")}


def _compose(stage: Stage, *args: str, run=subprocess.run) -> None:
    run(["docker", "compose", "-f", str(COMPOSE_FILE), *args], env=compose_env(stage), check=True)


def _operator_python(stage: Stage, module_args: list[str], run=subprocess.run) -> str:
    """Runs operator-repo code (its venv) against the local DynamoDB; returns stdout."""
    env = {**os.environ, "DB_BACKEND": "dynamodb", "DYNAMODB_TABLE": stage.table,
           "DYNAMODB_ENDPOINT_URL": f"http://localhost:{stage.dynamodb_port}", "AWS_REGION": "us-east-1"}
    result = run([str(OPERATOR_DIR / ".venv" / "bin" / "python"), "-m", *module_args],
                 cwd=OPERATOR_DIR, env=env, check=True, capture_output=True, text=True)
    print(result.stdout, end="")
    return result.stdout


def seed(stage: Stage, run=subprocess.run) -> None:
    _operator_python(stage, ["app.db.seed"], run=run)


def create_table(stage: Stage, run=subprocess.run, attempts: int = 20, delay: float = 1) -> str:
    """Creates the local table if missing, retrying while DynamoDB Local is still starting."""
    for attempt in range(attempts):
        try:
            return _operator_python(stage, ["app.db.dynamo_table", "create"], run=run)
        except subprocess.CalledProcessError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)
    raise AssertionError("unreachable")


def deploy(stage: Stage, run=subprocess.run, check=smoke.check) -> None:
    _compose(stage, "up", "-d", "--build", run=run)
    created = create_table(stage, run=run)
    if created.strip().endswith("created"):
        seed(stage, run=run)
    check(stage.base_url)


def remove(stage: Stage, run=subprocess.run) -> None:
    _compose(stage, "down", run=run)
