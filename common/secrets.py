# What it does: Reads a stage's secrets from stages/<stage>/.env (git-ignored) and checks them against
#   stages/<stage>/.env.example (in git): every uncommented name there is required and must be filled.
#   Commented names (# NAME=) are optional — synced when present in .env. deploy then copies the result
#   to SSM as SecureString parameters (common/aws.py), where the server reads them.
# When it runs: At the start of every AWS deploy, before anything is built or changed.
# What calls it: common/aws.py (deploy); tests/test_secrets.py.
from pathlib import Path

from .stage import STAGES_DIR, Stage


def parse(text: str) -> dict[str, str]:
    """KEY=VALUE lines; blank lines and # comments skipped; surrounding quotes stripped."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        out[key.strip()] = value
    return out


def load(stage: Stage, stages_dir: Path = STAGES_DIR) -> dict[str, str]:
    """The stage's secrets; raises with every problem named if .env is missing or incomplete."""
    folder = stages_dir / stage.name
    required = list(parse((folder / ".env.example").read_text()))
    env_file = folder / ".env"
    if not env_file.exists():
        raise RuntimeError(f"stages/{stage.name}/.env missing: copy .env.example and fill {', '.join(required)}")
    values = parse(env_file.read_text())
    missing = [name for name in required if not values.get(name)]
    if missing:
        raise RuntimeError(f"stages/{stage.name}/.env: fill {', '.join(missing)}")
    return {k: v for k, v in values.items() if v}
