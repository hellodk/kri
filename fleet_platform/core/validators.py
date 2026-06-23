"""Shared field validators for Pydantic schemas (#752).

A single authoritative definition prevents the per-file regex drift that was
reported in ARC-8: some files had no length bound, some used 128, some were
missing the end-anchor. The canonical rule:

  ^[a-zA-Z0-9._-]{1,128}$

picks the strictest sensible bound (128 chars, matching ``ansible.py``'s old
per-file regex) and applies it uniformly across every input schema that
accepts a ``minion_id`` field.

Usage in a Pydantic v2 model::

    from fleet_platform.core.validators import validate_minion_id
    from pydantic import field_validator

    class MyRequest(BaseModel):
        minion_id: str

        _validate_minion_id = field_validator("minion_id")(validate_minion_id)
"""

from __future__ import annotations

import re

MINION_ID_RE = re.compile(r"^[a-zA-Z0-9._-]{1,128}$")

_MINION_ID_ERR = "minion_id must be 1-128 characters, only [a-zA-Z0-9._-] allowed (got {value!r})"


def validate_minion_id(value: str) -> str:
    """Pydantic-compatible validator for ``minion_id`` fields.

    Raises ``ValueError`` when the value does not match ``MINION_ID_RE``.
    Safe to use as a classmethod validator via::

        _validate_minion_id = field_validator("minion_id")(validate_minion_id)
    """
    if not MINION_ID_RE.match(value):
        raise ValueError(_MINION_ID_ERR.format(value=value))
    return value
