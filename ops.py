# What it does: The one deploy CLI; all logic lives in common/. Commands:
#   init <stage>                 AWS infra (sst deploy) + seed a new table      — develop|demo|production
#   deploy <stage>               ship code: local = Docker Compose; AWS = image + restart + smoke
#   remove <stage>               local = stop containers; develop|demo = delete the stage (never production)
#   seed local                   reload db/seed/ into the local table
#   stop <stage> / start <stage> stop the AWS server while idle (saves money; disk + data kept) / start it
# Secrets: stages/<stage>/.env (git-ignored, names in .env.example) — deploy checks and syncs them to SSM.
# Env (.env, git-ignored): AWS_PROFILE, CLOUDFLARE_API_TOKEN, CLOUDFLARE_DEFAULT_ACCOUNT_ID.
# When it runs: Through stages/<stage>/*.sh.
# What calls it: stages/<stage>/{init,deploy,remove,seed}.sh.
import argparse
import os
import sys
from pathlib import Path

from common import local, stage as stages
from common.stage import REGION, ROOT


def _load_dotenv(path: Path = ROOT / ".env") -> None:
    """Minimal .env reader (KEY=VALUE lines); existing env wins."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def _session():
    import boto3

    return boto3.Session(region_name=REGION)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ops.py")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "deploy", "remove", "seed", "stop", "start"):
        sub.add_parser(name).add_argument("stage")
    args = parser.parse_args(argv)

    _load_dotenv()
    stage = stages.load(args.stage)

    if not stage.is_aws:
        if args.command in ("init", "stop", "start"):
            sys.exit(f"local has no {args.command}: use stages/local/deploy.sh / remove.sh")
        {"deploy": local.deploy, "remove": local.remove, "seed": local.seed}[args.command](stage)
        return

    from common import aws

    if args.command == "seed":
        sys.exit("AWS stages seed a new table on init")
    if args.command in ("stop", "start"):
        getattr(aws, args.command)(_session().client("ec2"), stage)
        return
    if args.command == "init":
        aws.init(stage, _session())
    elif args.command == "deploy":
        aws.deploy(stage, _session())
    elif args.command == "remove":
        if input(f"Delete stage '{stage.name}' from AWS (server, table, data)? Type the stage name: ") != stage.name:
            sys.exit("cancelled")
        aws.remove(stage)


if __name__ == "__main__":
    main()
