#!/usr/bin/env bash
# What it does: Stops and deletes the local stage's containers. DynamoDB data stays on its Docker volume.
# When it runs: When done with the local stage.
# What calls it: Roman / Claude, by hand. Logic: ops.py remove local (common/).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
exec .venv/bin/python ops.py remove local
