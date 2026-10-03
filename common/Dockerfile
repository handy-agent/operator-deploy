# What it does: The Operator image. Built from the operator code repo (build context = ../operator) and
#   holds only the runtime: app/, agent/, requirements.txt and db/ (seed data). Never CLAUDE.md, dev/,
#   tests/, sim/ or .env (common/Dockerfile.dockerignore keeps them out of the build context).
#   Env comes from outside: docker compose (local) or the server's env file from SSM (AWS).
# When it runs: Built by every deploy — linux/arm64 for AWS (t4g server), the host's arch for local.
# What calls it: common/image.py (AWS deploy); stages/local/docker-compose.yml.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY agent/ agent/
COPY db/ db/

# Non-root; HOME must be writable (the Claude Agent SDK's bundled CLI keeps state there).
RUN useradd --create-home app
USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
