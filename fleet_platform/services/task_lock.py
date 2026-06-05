"""Simple Redis-based task deduplication using SETNX."""

import functools
import logging

import redis as sync_redis

_log = logging.getLogger(__name__)
_LOCK_TTL = 300  # 5 minutes — tasks must complete within this window


def _get_sync_redis():
    from fleet_platform.core.config import settings

    return sync_redis.from_url(settings.redis_url, decode_responses=True)


def unique_task(key_fn=None, ttl: int = _LOCK_TTL):
    """Decorator that skips task execution if a lock with the same key exists.

    Usage:
        @unique_task(key_fn=lambda args, kwargs: f"compute_drift:{args[0]}")
        @celery_app.task(...)
        def compute_drift(node_id): ...

    If key_fn is None, uses task name as lock key (for singleton tasks like
    refresh_all_node_grains).
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            task_name = func.__name__
            if key_fn is not None:
                lock_key = f"task_lock:{key_fn(args, kwargs)}"
            else:
                lock_key = f"task_lock:{task_name}"

            r = _get_sync_redis()
            acquired = r.set(lock_key, "1", nx=True, ex=ttl)
            if not acquired:
                _log.debug("Skipping duplicate task %s (key=%s)", task_name, lock_key)
                return None
            try:
                return func(*args, **kwargs)
            finally:
                r.delete(lock_key)

        return wrapper

    return decorator
