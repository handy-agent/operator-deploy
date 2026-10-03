#!/usr/bin/env bash
# What it does: One-time setup of this repo on a machine: Python venv + deps (ops.py), Node deps + SST
#   platform (sst.config.ts), and arm64 emulation for Docker so an x86 laptop can build the server's
#   arm64 image (tonistiigi/binfmt, privileged, only if arm64 isn't available yet). Safe to rerun.
#   Needs: python3, Node 20+, Docker. The operator repo next to this one (~/handy-agent/operator) with
#   its own .venv (deploy seeds through its code).
# When it runs: Once per machine, and after package.json / requirements.txt change.
# What calls it: Roman / Claude, by hand.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt

node_major="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
if [ "$node_major" -lt 20 ]; then
  echo "Node 20+ needed for SST (found: $(node --version 2>/dev/null || echo none))." >&2
  echo "Install it (e.g. nvm install 22), then rerun this script." >&2
  exit 1
fi
npm install --silent
npx sst install

if ! docker buildx inspect --bootstrap 2>/dev/null | grep -q 'linux/arm64'; then
  docker run --privileged --rm tonistiigi/binfmt --install arm64
fi

[ -f .env ] || { cp .env.example .env; echo "Created .env — fill AWS_PROFILE and the Cloudflare values."; }
[ -x ../operator/.venv/bin/python ] || echo "Warning: ../operator/.venv missing — set up the operator repo first." >&2
echo "setup done"
