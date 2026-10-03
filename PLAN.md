# Operator AWS deploy plan

Decisions, status and open points. How to use the repo: `README.md`. Stages × Thumbtack table (domains,
webhooks, redirects, keys, accounts): `../operator/dev/REQUIREMENTS.md` → "Stages × Thumbtack".

## Status (2026-10-03)
- **develop:** infra up (`init.sh` done, table seeded), never deployed. **Server stopped** to save money
  while waiting for Thumbtack Partner API keys (Roman). Before the first deploy:
  `.venv/bin/python ops.py start develop`, then `stages/develop/deploy.sh`.
- **demo, production:** not created.
- Code uncommitted on `main` (waiting for Roman's review). 52 unit tests pass (`test.sh`).

## Decided
- Stages: `develop` / `demo` / `production`, us-east-1. Local is a stage folder too (Docker).
- Compute: one EC2 t4g.small per stage, Operator (uvicorn) in Docker under systemd. Not Lambda (in-memory
  timers/sessions — see REQUIREMENTS "Stack").
- **Outbound:** the server has a public IP (~$3.60/mo while running) so it can call Claude, Thumbtack and
  Telegram — cheapest option; a NAT costs ~$7–32/mo.
  - **Inbound:** the firewall lets in only API Gateway's VPC Link on port 8000; the public IP doesn't expose
    the server. No SSH (deploys use SSM Run Command).
  - **Difference from real estate:** Lambda gets outbound access free and has no IP to pay for.
- Ingress: API Gateway HTTP API + VPC Link (Cloud Map) → uvicorn. Default VPC; VPC Link subnets skip zone
  `use1-az3` (VPC Links aren't available there — found on first init).
- Domains: `dev-api.`, `demo-api.`, `api.handyagent.dev`. Each stage's `init.sh` creates its record + the
  certificate check in Cloudflare through SST's Cloudflare adapter (zone found by name). A record with the
  same name must not exist before that stage's first init (SST fails on it); the hand-made placeholders
  were deleted 2026-10-03.
- Infra tool: SST v3, `sst.config.ts` in this repo.
- Language (Roman): deploy logic in Python; TypeScript only for `sst.config.ts`. As few `.sh` as possible.
- Infra vs code (Roman):
  - `init.sh` — first time, or when infra changes (table, server size, domain): `sst deploy`, then seeds
    DynamoDB if the table is empty (calls the operator repo's `app/db/seed.py`).
  - `deploy.sh` — every code change, no infra touched: checks secrets → env + secrets to SSM → arm64 image
    tagged with the operator git commit → ECR → SSM Run Command restarts Operator (it pulls the tag from
    SSM) → smoke test (`/health` + an ignored webhook event). Rollback = deploy the previous commit.
  - A restart drops in-memory per-lead timers — see "Before prod".
- Secrets (Roman): per-stage `stages/<stage>/.env` (git-ignored; names in `.env.example`). deploy refuses
  while a required one is empty, then syncs them to SSM SecureString. Never in git or `stage.yaml`.
- SSM paths (Roman): `/handyagent/operator/<stage>/{env,secret}/<NAME>`, `/handyagent/operator/<stage>/image-tag`.
- Tags (Roman): only the `sst:` namespace — `sst:project = handyagent` (ours), `sst:app = operator` and
  `sst:stage` (added by SST; ours on SSM parameters). Server `Name` tag: `handyagent-operator-<stage>`.
  Find everything: Resource Groups → Tag Editor, `sst:project = handyagent`.
- Deploys run by hand, no CI, same as real estate. Git: `main` for now, no feature branches (Roman).
- Laptop AWS auth (Roman): `aws login --profile handyagent` (browser sign-in, short-term credentials, no
  stored key; currently the account root user). SST/boto3 can't read `aws login` sessions, so deploy uses
  profile `handyagent-tools` (`~/.aws/config`, `credential_process` over the same session). Identity
  Center (SSO) not enabled. The server uses its IAM role, no key.
- Idle stages can be stopped: `ops.py stop|start <stage>` (disk + data kept, ~$2/mo while stopped).

## Before prod
- Auth on the Thumbtack webhook (anyone with the URL can send fake events now).
- Telegram in webhook mode per stage (code ready: `TELEGRAM_WEBHOOK_URL` is set by deploy).
- `/prices` access: local-only or password.
- Thumbtack OAuth with tokens stored in DynamoDB (when Partner API keys arrive).
- Rebuild pending timers from DynamoDB after a restart.

## Thumbtack staging (from docs, 2026-10-03)
- Accounts: self-created on staging-partner.thumbtack.com after logging in with staging credentials from
  the Thumbtack Account Manager (so only after Partner API approval). Customer: `/register`; pro: "Join as
  a pro". Test card `4242 4242 4242 4242`, any valid fake SSN.
- Now (Roman): one staging account with one business, set in env. Multiple accounts or businesses are out
  of scope for deploy.
- Staging webhooks are registered via API, one per business:
  `POST /api/v4/businesses/{businessID}/webhooks` (bearer token; optional basic auth).
- Sources: https://developers.thumbtack.com/docs/pro-integrations/testing,
  https://developers.thumbtack.com/docs/pro-integrations/self-serve-webhooks

## Not verified yet (first deploy)
- The arm64 image build + push, the server start script (`common/server/`), the smoke test on AWS.
- Claude Platform on AWS IAM actions: `aws-external-anthropic:*` in `sst.config.ts` is a placeholder.
- The local stage (`stages/local/deploy.sh`) was never started: it uses the operator repo's real `.env`
  on port 8000, where the `local.handyagent.dev` tunnel points.

## Open
- Before the first develop deploy (Roman): `stages/develop/stage.yaml` env (business profile,
  `OPERATOR_ACCOUNT_ID`, `ANTHROPIC_AWS_WORKSPACE_ID`), Claude Platform on AWS subscription, a develop
  Telegram bot, `stages/develop/.env` secrets.
- Cost allocation tag `sst:project` in Billing — not activated.
- Future multi-user signup flow + Thumbtack investigate list: `../operator/dev/REQUIREMENTS.md` →
  "Future: user signup flow".
