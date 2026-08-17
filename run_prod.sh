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
unset CONDA_DEFAULT_ENV
unset CONDA_PROMPT_MODIFIER
unset CONDA_SHLVL
unset CONDA_PREFIX_1 CONDA_PREFIX_2 CONDA_PREFIX_3 CONDA_PREFIX_4
unset CONDA_STACK_ENV
unset PYTHON_SESSION_INITIALIZED
# Drop the current shell's conda prefix while keeping the conda root pointers
# (CONDA_EXE/CONDA_ROOT) so child processes that touch conda don't crash with an
# inconsistent "CONDA_SHLVL != 0 but CONDA_PREFIX unset" stack.
unset CONDA_PREFIX
export CONDA_SHLVL=0
export PYTHONNOUSERSITE=1
# Unbuffered stdout/stderr so the tees below flush lines immediately.
export PYTHONUNBUFFERED=1

# Use the absolute gunicorn binary (not `python -m gunicorn`): its shebang already
# points at the pinned scdb python, and it keeps sys.argv[0] basename == "gunicorn",
# which task/apps.py and core/apps.py rely on to detect the web server and start the
# R worker / scheduler threads.
#
# stdout/stderr are teed to both the terminal and logs/app.log / logs/app-error.log
# so Django/R worker print() stays visible in the console while also landing on disk.
# access/error logs remain gunicorn-only files (access.log / error.log).
exec "$ENV_PREFIX/bin/gunicorn" scdb_api.wsgi:application \
  --workers 4 \
  --bind 127.0.0.1:8899 \
  --preload \
  --timeout 120 \
  --max-requests 5000 \
  --max-requests-jitter 1000 \
  --access-logfile logs/access.log \
  --error-logfile logs/error.log \
  > >(tee -a logs/app.log) \
  2> >(tee -a logs/app-error.log >&2)
