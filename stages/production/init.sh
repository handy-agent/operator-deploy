#!/usr/bin/env bash
# What it does: Creates or updates the production stage's AWS infra (sst.config.ts) and seeds its DynamoDB table if empty.
# When it runs: First time, or when the infra changes (table, server size, domain). Then run deploy.sh.
# What calls it: Roman / Claude, by hand. Logic: ops.py init production (common/).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
exec .venv/bin/python ops.py init production
