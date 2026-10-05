#!/bin/sh
# Container entrypoint: migrate, seed on first boot only, then serve. One process: the job worker runs in-process.
set -eu
PORT="${PORT:-8000}"
# The mock ERP is mounted on this same app; post to it over loopback unless a real ERP URL is given.
export ERP_URL="${ERP_URL:-http://127.0.0.1:${PORT}/erp-mock/v1}"
cd /app/api
alembic upgrade head
python -m orderdesk.seed --if-empty
exec uvicorn orderdesk.web.app:app --host 0.0.0.0 --port "$PORT" --no-server-header
