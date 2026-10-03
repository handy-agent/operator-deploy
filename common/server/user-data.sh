#!/usr/bin/env bash
# What it does: First-boot setup of the Operator EC2 server (Amazon Linux 2023, arm64): installs and
#   starts Docker, writes /etc/operator/stage, installs operator-start.sh + operator.service and enables
#   the service. The SSM agent ships with AL2023 (deploys reach the server through it, no SSH).
#   __STAGE__, __REGION__, __ECR_REPO_URL__, __START_SCRIPT__, __SERVICE_UNIT__ are filled in by
#   sst.config.ts; a change here replaces the server on the next init.
# When it runs: Once, when the server is created (EC2 user data).
# What calls it: EC2 at first boot; sst.config.ts passes it as the server's user data.
set -euo pipefail

dnf install -y docker
systemctl enable --now docker

mkdir -p /etc/operator
cat > /etc/operator/stage <<'EOF'
STAGE=__STAGE__
REGION=__REGION__
ECR_REPO_URL=__ECR_REPO_URL__
EOF

cat > /usr/local/bin/operator-start.sh <<'EOF'
__START_SCRIPT__
EOF
chmod 755 /usr/local/bin/operator-start.sh

cat > /etc/systemd/system/operator.service <<'EOF'
__SERVICE_UNIT__
EOF
systemctl daemon-reload
systemctl enable operator
systemctl start operator || true
