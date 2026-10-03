#!/usr/bin/env bash
# What it does: Installs the deploy tools for the current user (no sudo): nvm + Node 22 (with npm), and
#   AWS CLI v2 into ~/.local/aws-cli (command in ~/.local/bin). Skips anything already installed.
#   Then runs setup.sh (venv, SST, arm64 emulation for Docker).
# When it runs: Once per machine, before the first deploy.
# What calls it: Roman / Claude, by hand (Claude opens it in a new terminal window).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

# --- Node 22 via nvm
export NVM_DIR="$HOME/.nvm"
if [ ! -s "$NVM_DIR/nvm.sh" ]; then
  curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
fi
# shellcheck disable=SC1091
source "$NVM_DIR/nvm.sh"
nvm install 22
nvm alias default 22
echo "node $(node --version), npm $(npm --version)"

# --- AWS CLI v2 (user install)
if ! command -v aws >/dev/null 2>&1; then
  tmp="$(mktemp -d)"
  curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "$tmp/awscliv2.zip"
  unzip -q "$tmp/awscliv2.zip" -d "$tmp"
  "$tmp/aws/install" -i "$HOME/.local/aws-cli" -b "$HOME/.local/bin"
  rm -rf "$tmp"
fi
aws --version

# --- This repo
./setup.sh

echo
echo "Done. Next: aws login --profile handyagent (see README \"First run\")"
