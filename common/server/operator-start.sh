#!/usr/bin/env bash
# What it does: Runs on the EC2 server as the operator systemd service (ExecStart). Builds the app env
#   file from SSM (/handyagent/operator/<stage>/env/ + /handyagent/operator/<stage>/secret/), reads the image tag from SSM
#   (/handyagent/operator/<stage>/image-tag), logs docker in to ECR, pulls the image and runs it in the foreground
#   on port 8000. Credentials: the server's IAM role.
# When it runs: On boot, and on every `systemctl restart operator` (each deploy, via SSM Run Command).
# What calls it: common/server/operator.service; installed by common/server/user-data.sh.
set -euo pipefail

# STAGE, REGION, ECR_REPO_URL — written by user-data.
source /etc/operator/stage

ENV_FILE=/etc/operator/env
umask 077
: > "$ENV_FILE.tmp"
for path in "/handyagent/operator/$STAGE/env/" "/handyagent/operator/$STAGE/secret/"; do
  aws ssm get-parameters-by-path --region "$REGION" --path "$path" --recursive --with-decryption \
    --query 'Parameters[*].[Name,Value]' --output text |
  while IFS=$'\t' read -r name value; do
    [ -n "$name" ] && printf '%s=%s\n' "${name##*/}" "$value" >> "$ENV_FILE.tmp"
  done
done
mv "$ENV_FILE.tmp" "$ENV_FILE"

TAG="$(aws ssm get-parameter --region "$REGION" --name "/handyagent/operator/$STAGE/image-tag" \
  --query Parameter.Value --output text)"
IMAGE="$ECR_REPO_URL:$TAG"

aws ecr get-login-password --region "$REGION" |
  docker login --username AWS --password-stdin "${ECR_REPO_URL%%/*}" >/dev/null
docker pull "$IMAGE"
docker rm -f operator >/dev/null 2>&1 || true
exec docker run --rm --name operator -p 8000:8000 --env-file "$ENV_FILE" "$IMAGE"
