# fleet_platform/services/node_status.py
from datetime import UTC, datetime, timedelta

import bcrypt

_STALE_THRESHOLD = timedelta(minutes=15)
_OFFLINE_THRESHOLD = timedelta(hours=4)  # synced with maintenance._DEFAULT_OFFLINE_HOURS


def classify_status(last_seen_at: datetime | None) -> str:
    """Return 'online', 'stale', 'offline', or 'unknown' based on last_seen_at age."""
    if last_seen_at is None:
        return "unknown"
    age = datetime.now(UTC) - last_seen_at
    if age <= _STALE_THRESHOLD:
        return "online"
    if age <= _OFFLINE_THRESHOLD:
        return "stale"
    return "offline"


def verify_node_token(plaintext_token: str, hashed_token: str) -> bool:
    """Return True if plaintext_token matches the bcrypt hash. Returns False on corrupt hash."""
    try:
        return bcrypt.checkpw(plaintext_token.encode(), hashed_token.encode())
    except (ValueError, Exception):
        return False
