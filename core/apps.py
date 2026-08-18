import os
import sys
import threading
import time
from django.apps import AppConfig
from django.core.management import call_command
from utils.logging import get_logger

logger = get_logger('core')


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        # Only run inside web server process (runserver / gunicorn / uwsgi)
        # Skip management commands like migrate / makemigrations / shell / test
        # note: gunicorn sets sys.argv[0] to a full path, so match by basename
        if not any(os.path.basename(str(x)) in ('runserver', 'gunicorn', 'uwsgi') for x in sys.argv):
            return

        # Django autoreloader forks twice; only run in the real serving child
        if 'runserver' in sys.argv and os.environ.get('RUN_MAIN') != 'true':
            return

        def loop():
            while True:
                try:
                    call_command('scheduled')
                except Exception as e:
                    logger.warning('[core.scheduler] scheduled error: %s', e)
                time.sleep(60)

        t = threading.Thread(target=loop, daemon=True, name='core-scheduler')
        t.start()
        logger.info('[core.scheduler] started, will run scheduled every 60s')
