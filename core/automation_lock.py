from contextlib import contextmanager
from threading import Lock

from django.db import connection


_local_lock = Lock()
_LOCK_KEY = 827364921


@contextmanager
def automation_lock():
    """Prevent overlapping automation runs across processes when supported."""
    acquired = False
    postgres_lock = False
    try:
        if connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_try_advisory_lock(%s)', [_LOCK_KEY])
                postgres_lock = bool(cursor.fetchone()[0])
            acquired = postgres_lock
        else:
            acquired = _local_lock.acquire(blocking=False)

        yield acquired
    finally:
        if postgres_lock:
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_unlock(%s)', [_LOCK_KEY])
        elif acquired and connection.vendor != 'postgresql':
            _local_lock.release()
