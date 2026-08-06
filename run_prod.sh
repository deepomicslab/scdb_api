#!/usr/bin/env bash
# Production gunicorn launcher for scdb_api.
# Run this inside the scdb conda env on the production server:
#   conda activate scdb
#   sh run_prod.sh
#
# Logs go to logs/ (access + error) instead of the terminal so incidents can
# be diagnosed later. Workers recycle every ~5000-6000 requests to avoid
# connection/FD leaks on long-lived workers.
set -euo pipefail

cd "$(dirname "$0")"
mkdir -p logs

exec gunicorn scdb_api.wsgi:application \
  --workers 4 \
  --bind 127.0.0.1:8899 \
  --preload \
  --timeout 120 \
  --max-requests 5000 \
  --max-requests-jitter 1000 \
  --access-logfile logs/access.log \
  --error-logfile logs/error.log
