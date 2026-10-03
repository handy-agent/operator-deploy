#!/usr/bin/env bash
# What it does: Ships the current operator code to the develop stage: syncs app env to SSM, builds + pushes the arm64 image, restarts Operator on the server, smoke test.
# When it runs: On every code change. The stage must exist (init.sh).
# What calls it: Roman / Claude, by hand. Logic: ops.py deploy develop (common/).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
exec .venv/bin/python ops.py deploy develop
