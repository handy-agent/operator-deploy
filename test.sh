#!/usr/bin/env bash
# What it does: Runs this repo's unit tests (tests/, unittest). No AWS, Docker or network needed.
# When it runs: After any change to ops.py or common/.
# What calls it: Roman / Claude, by hand. Needs setup.sh run once (.venv).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
exec .venv/bin/python -m unittest discover tests "$@"
