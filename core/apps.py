import os
import sys
import threading
import time
from django.apps import AppConfig
from django.core.management import call_command


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        # Only run inside web server process (runserver / gunicorn / uwsgi)
        # Skip management commands like migrate / makemigrations / shell / test
        if not any(x in sys.argv for x in ['runserver', 'gunicorn', 'uwsgi']):
            return

        # Django autoreloader forks twice; only run in the real serving child
        if 'runserver' in sys.argv and os.environ.get('RUN_MAIN') != 'true':
            return

        def loop():
            while True:
                try:
                    call_command('scheduled')
                except Exception as e:
                    print('[core.scheduler] scheduled error:', e)
                time.sleep(60)

        t = threading.Thread(target=loop, daemon=True, name='core-scheduler')
        t.start()
        print('[core.scheduler] started, will run scheduled every 60s')
