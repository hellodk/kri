"""Simple Redis-based task deduplication using SETNX with owner tokens (#153, #1048).

Locks carry a per-acquisition UUID token. Release is a compare-and-delete
(atomic Lua GETDEL-compare): only the worker whose token matches may delete
the lock, so a late finisher can never steal a lock that expired and was
re-acquired by another worker in the meantime.
"""

import functools
import logging
import uuid

import redis as sync_redis

_log = logging.getLogger(__name__)
_LOCK_TTL = 300  # 5 minutes — tasks must complete within this window

# Atomic compare-and-delete: delete KEYS[1] only if it still holds our token.
_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


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

    ``ttl`` is per call site: long-running sweeps pass a larger budget (e.g.
    refresh_all_node_grains uses 2400s); short tasks keep the 300s default.
    The effective ttl is exposed on the wrapper as ``lock_ttl`` for tests/ops.
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
            token = uuid.uuid4().hex
            acquired = r.set(lock_key, token, nx=True, ex=ttl)
            if not acquired:
                _log.debug("Skipping duplicate task %s (key=%s)", task_name, lock_key)
                return None
            try:
                return func(*args, **kwargs)
            finally:
                _release_lock(r, lock_key, token)

        wrapper.lock_ttl = ttl
        return wrapper

    return decorator


def _release_lock(r, lock_key: str, token: str) -> None:
    """Release the lock only if we still own it (#1048).

    The compare-and-delete runs atomically server-side: if the lock expired
    and was re-acquired by another worker, its token no longer matches and
    the new owner's lock is left untouched.
    """
    try:
        released = bool(r.eval(_RELEASE_LUA, 1, lock_key, token))
        if not released:
            _log.debug("task lock %s already expired or re-owned; skipping release", lock_key)
    except Exception:  # noqa: BLE001 — never mask the task's own outcome
        _log.warning("task lock %s release failed", lock_key, exc_info=True)
