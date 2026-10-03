#!/usr/bin/env bash
# What it does: Deletes the develop stage from AWS (server, table, data, domain). Asks to type the stage name first.
# When it runs: Only when the stage is no longer wanted.
# What calls it: Roman / Claude, by hand. Logic: ops.py remove develop (common/).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
exec .venv/bin/python ops.py remove develop
