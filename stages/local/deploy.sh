#!/usr/bin/env bash
# What it does: Builds and starts the local stage in Docker (Operator + DynamoDB Local), creates the table if missing (seeding a new one), smoke test.
# When it runs: Whenever you want the deployed image running locally.
# What calls it: Roman / Claude, by hand. Logic: ops.py deploy local (common/).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
exec .venv/bin/python ops.py deploy local
