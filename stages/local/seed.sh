#!/usr/bin/env bash
# What it does: Reloads db/seed/ (pricing catalog) from the operator repo into the local DynamoDB table. Safe to rerun.
# When it runs: After the seed files change. The local stage must be running.
# What calls it: Roman / Claude, by hand. Logic: ops.py seed local (common/).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
exec .venv/bin/python ops.py seed local
