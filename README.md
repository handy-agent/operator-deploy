# operator-deploy

Deploys Operator (`../operator`) to a local Docker stage and three AWS stages (develop, demo, production).
Decisions and status: `PLAN.md`. Stages × Thumbtack table: `../operator/dev/REQUIREMENTS.md`.

## Layout
- `ops.py` — the one CLI; logic in `common/`: `stage.py` (names, tags, app env), `aws.py`, `local.py`,
  `image.py`, `secrets.py`, `smoke.py`. `common/Dockerfile` = the Operator image; `common/server/` = files
  installed on the server (user data, systemd unit, start script).
- `sst.config.ts` — AWS infra per stage (the only TypeScript).
- `stages/<stage>/` — `stage.yaml` (values, no secrets), `.env.example` (secret names; your `.env` beside
  it is git-ignored), and the stage's scripts.
- `install-tools.sh` (Node 22 + AWS CLI, then `setup.sh`), `setup.sh` (venv, SST, arm64 emulation),
  `test.sh` (unit tests).

## Scripts
| Stage | Scripts |
|---|---|
| local | `deploy.sh` (start in Docker), `remove.sh` (stop), `seed.sh` |
| develop, demo | `init.sh` (infra), `deploy.sh` (code), `remove.sh` |
| production | `init.sh`, `deploy.sh` |

- `init.sh` — first time or infra change: `sst deploy`, seeds a new DynamoDB table. Then `deploy.sh`.
- `deploy.sh` — every code change: secrets check, env + secrets → SSM, arm64 image → ECR (tag = operator
  git commit), restart on the server via SSM Run Command, smoke test. Rollback: check out the old commit
  in `../operator`, deploy.
- `.venv/bin/python ops.py stop|start <stage>` — stop the server while idle / start it again.

## Where things live on AWS (per stage)
- DynamoDB table, ECR repo: `operator-<stage>`; server Name tag: `handyagent-operator-<stage>`.
- Tags: `sst:project = handyagent`, `sst:app = operator`, `sst:stage = <stage>`.
- SSM: `/handyagent/operator/<stage>/env/*` (from `stage.yaml`), `/handyagent/operator/<stage>/secret/*`
  (from `stages/<stage>/.env`), `/handyagent/operator/<stage>/image-tag` — all written by deploy. The
  server builds its env file from these on every start.
- Server: EC2 t4g in the default VPC (us-east-1a), public IP for outbound only; inbound only from
  API Gateway's VPC Link on port 8000. No SSH.

## First run
1. `./install-tools.sh` (or `./setup.sh` if Node 20+ and AWS CLI are already there). Needs Docker,
   python3 and `../operator/.venv`.
2. `aws login --profile handyagent`. Deploy uses profile `handyagent-tools` (`~/.aws/config`:
   `credential_process = aws configure export-credentials --profile handyagent --format process`),
   because SST can't read `aws login` sessions.
3. Fill `.env` (`AWS_PROFILE=handyagent-tools`, Cloudflare token + account ID) and
   `stages/<stage>/stage.yaml` `env`.
4. Copy `stages/<stage>/.env.example` to `.env` and fill the secrets.
5. No Cloudflare record with the stage's domain name may exist before its first init.
6. `stages/<stage>/init.sh`, then `stages/<stage>/deploy.sh`.
