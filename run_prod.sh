#!/usr/bin/env bash
# Production gunicorn launcher for scdb_api.
#
# The scdb conda env is pinned by absolute path, so the shell's current conda
# env / PATH do not matter: this script always runs the same Python + Gunicorn
# regardless of where it is launched from.
#
# Logs go to logs/ (access + error) instead of the terminal so incidents can
# be diagnosed later. Workers recycle every ~5000-6000 requests to avoid
# connection/FD leaks on long-lived workers.
set -euo pipefail

cd "$(dirname "$0")"
mkdir -p logs

ENV_PREFIX="/data2/platform/scdb_platform/env/scdb"

# Fix PATH: keep the pinned env first, then the standard system paths so the
# SLURM commands the backend shells out to (sbatch/squeue/sacct in /usr/bin)
# remain reachable regardless of the launching shell.
export PATH="$ENV_PREFIX/bin:/usr/local/bin:/usr/bin:/bin"

# Strip conda/venv/user-site influence from the environment so only the pinned
# scdb env is used, independent of the shell that started this script.
unset PYTHONHOME
unset PYTHONPATH
unset VIRTUAL_ENV
unset CONDA_PREFIX
unset CONDA_DEFAULT_ENV
unset CONDA_PROMPT_MODIFIER
export PYTHONNOUSERSITE=1

exec "$ENV_PREFIX/bin/python" -m gunicorn scdb_api.wsgi:application \
  --workers 4 \
  --bind 127.0.0.1:8899 \
  --preload \
  --timeout 120 \
  --max-requests 5000 \
  --max-requests-jitter 1000 \
  --access-logfile logs/access.log \
  --error-logfile logs/error.log
