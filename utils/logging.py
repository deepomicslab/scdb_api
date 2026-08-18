"""Shared logger for scdb_api business logs.

All request-path code should log through get_logger(__name__) instead of
print(). Messages carry context ids inline in a stable format so they can be
grepped/tailed:

    [task:123] [subtask:456] [job:789] created ...

The logger writes to stdout (see LOGGING in scdb_api/settings.py), which the
run_prod.sh tee chain routes into logs/app.log and the terminal.
"""

import logging

logger = logging.getLogger('scdb')


def get_logger(name=None):
    """Return the scdb business logger (optionally namespaced under it)."""
    if name:
        return logging.getLogger(f'scdb.{name}')
    return logger
