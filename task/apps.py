from django.apps import AppConfig
import sys
import os
import subprocess
import time
import threading
from multiprocessing.managers import BaseManager

# Global variables
r_proxy = None

# ================= Config section =================
CONDA_PYTHON = '/data3/platform/sc_db/cellchat/env/bin/python'
CONDA_PREFIX = '/data3/platform/sc_db/cellchat/env'
WORKER_SCRIPT = os.path.join(os.path.dirname(__file__), 'r_worker.py')
SOCKET_PATH = '/tmp/cellchat_r.sock'
AUTH_KEY = os.environ.get('R_AUTH_KEY', 'cellchat_secret_key').encode()

_proxy_lock = threading.Lock()


def _r_worker_env():
    """Build a clean, self-contained environment for the R worker subprocess.

    The R worker runs with the cellchat conda env's python, so it must not inherit
    leftover CONDA_* state from whatever shell started Gunicorn (e.g. an inconsistent
    CONDA_SHLVL/CONDA_PREFIX_* stack can make conda's activate() crash with
    TypeError inside rpy2 startup). Pin the full stack to the cellchat env and keep
    only the essential variables.
    """
    env = {}
    for k in ('HOME', 'USER', 'LOGNAME', 'SHELL', 'TMPDIR', 'PATH'):
        if k in os.environ:
            env[k] = os.environ[k]
    # Base system PATH first, cellchat bin appended by cellchat_r_service at import
    env['PATH'] = env.get('PATH', '/usr/local/bin:/usr/bin:/bin')
    env['CONDA_PREFIX'] = CONDA_PREFIX
    env['CONDA_DEFAULT_ENV'] = 'cellchat'
    env['CONDA_SHLVL'] = '1'
    env['CONDA_EXE'] = os.environ.get('CONDA_EXE', '/data3/platform/sc_db/miniconda3/bin/conda')
    env['CONDA_ROOT'] = os.environ.get('CONDA_ROOT', '/data3/platform/sc_db/miniconda3')
    env['CONDA_PYTHON_EXE'] = os.environ.get(
        'CONDA_PYTHON_EXE', '/data3/platform/sc_db/miniconda3/bin/python'
    )
    env['CONDA_PROMPT_MODIFIER'] = '(cellchat)'
    env['PYTHONNOUSERSITE'] = '1'
    env['PYTHONUNBUFFERED'] = '1'
    # cellchat env's R runtime
    env['R_HOME'] = os.path.join(CONDA_PREFIX, 'lib', 'R')
    env['LD_LIBRARY_PATH'] = (
        os.path.join(CONDA_PREFIX, 'lib', 'R', 'lib') + ':' + env.get('LD_LIBRARY_PATH', '')
    )
    env['R_AUTH_KEY'] = AUTH_KEY.decode('utf-8')
    # The worker must see the Django project on sys.path (it imports task.cellchat_r_service)
    env['PYTHONPATH'] = os.getcwd()
    return env


class RServiceManager(BaseManager):
    pass


RServiceManager.register('get_cellchat_service')


def get_r_proxy():
    """Lazily connect to the R service: establish the connection on first call, reuse afterwards.

    Under gunicorn with multiple workers, fork copies the pre-built socket connection
    (4 workers sharing one connection would interleave data), so we must not pre-connect
    at process startup - each worker connects on its first call. Under runserver
    (single process) the semantics are equivalent to pre-connecting.
    """
    global r_proxy
    if r_proxy is None:
        with _proxy_lock:
            if r_proxy is None:
                manager = RServiceManager(address=SOCKET_PATH, authkey=AUTH_KEY)
                manager.connect()
                r_proxy = manager.get_cellchat_service()
    return r_proxy

class TaskConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'task'
    
    def ready(self):
        # Prevent repeated execution caused by the runserver reload mechanism
        if "runserver" in sys.argv and os.environ.get("RUN_MAIN") != "true":
            return

        # Also exclude commands like migrate
        # Note: under gunicorn, sys.argv[0] is a full path (e.g. /data2/.../bin/gunicorn),
        # so exact matching would fail; must match on the basename.
        if not any(os.path.basename(str(x)) in ('runserver', 'gunicorn', 'uwsgi') for x in sys.argv):
            return

        print("🔹 [AppConfig] Initializing R subsystem connection...")

        # 1. Start the subprocess (if the socket does not exist)
        # Note: we assume that if the socket exists, the service is alive.
        # If the socket is a leftover dead file from a previous run, it may need
        # manual cleanup, but r_worker cleans old sockets at startup.
        if not os.path.exists(SOCKET_PATH):
            print("⚙️ Starting background R process (Conda environment)...")
            subprocess.Popen(
                [CONDA_PYTHON, WORKER_SCRIPT, SOCKET_PATH, AUTH_KEY.decode('utf-8')],
                cwd=os.getcwd(),
                env=_r_worker_env(),
                # stdout=sys.stdout, # show subprocess output in the main terminal for debugging
                # stderr=sys.stderr
            )
        
        # 2. ⏳ Wait for the Socket file to appear (up to 60 seconds)
        # The connection itself is already lazy (get_r_proxy); here we only make sure
        # the R subprocess is up, avoiding the socket not being ready on the first
        # request (r_worker loads CellChat in about 30-40s).
        print("⏳ Waiting for R service...", end='', flush=True)
        max_retries = 120  # 120 retries * 0.5s = 60s timeout (r_worker sources CellChat in ~30-40s)
        connected = False
        
        for i in range(max_retries):
            if os.path.exists(SOCKET_PATH):
                connected = True
                print(" ✅") # newline
                break
            time.sleep(0.5)
            print(".", end='', flush=True)
        
        if not connected:
            print("\n❌ [Timeout] R service startup timed out (over 60 seconds), Socket file not created.")
            # Do not raise here to avoid Django failing to start; decide at your discretion
            return

        print("🔗 [Ready] R service is ready; the connection will be established on the first CellChat call (get_r_proxy)")