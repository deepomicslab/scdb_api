# scdb_api

Backend of the OMICOS single-cell / spatial transcriptomics (scRNA-seq + ST) browsing
and analysis platform. Django 5 + Django REST Framework + PostgreSQL. Anonymous access,
no auth; task identity is tracked via a cookie `userId` sent in query/body as `userid`.

## Setup

- Python env: `conda activate scdb`
- PostgreSQL database: `scdb_platform_dev`
- `settings_local.py` and `.env` are git-ignored; copy from `settings_local.example` / `.env.example`
  on a fresh checkout, otherwise imports will fail.

```bash
conda activate scdb
python manage.py migrate
python manage.py makemigrations
python manage.py runserver <port>
```

## Task Status Sync

- `python manage.py scheduled` runs one module main-task status sync (a background thread
  in `core/apps.py` runs it every 60s automatically)
- On the server, `sh update.sh` loops the same command every 30s

## Production

Gunicorn (no runserver, no systemd/supervisor). Launch via `run_prod.sh` inside
the `scdb` env — it writes access/error logs to `logs/` and recycles workers
every ~5000 requests:

```bash
conda activate scdb
bash run_prod.sh
```

Restart = kill the gunicorn processes and re-run the script.

Notes:
- `--preload` runs `AppConfig.ready()` once in the master (background scheduled
  sync thread lives in the master; workers are plain forks)
- `DATABASES.OPTIONS` sets `connect_timeout=10` and `statement_timeout=60s` so a
  PostgreSQL connection storm or lock fails the request fast instead of letting
  all workers exceed the 120s timeout and get SIGKILLed in a loop

## R Service

R (CellChat etc.) runs in a separate conda env subprocess, started by `task/apps.py`
via a Unix socket proxy (the env is a server-side deployment detail; do not rely on it
locally). The scdb env has rpy2, but R calls must go through the `r_proxy` subprocess
proxy; do not import `task.cellchat_r_service` in the main process to run R logic.
