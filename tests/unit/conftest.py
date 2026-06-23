"""Unit-test conftest: provide lightweight stubs for heavy runtime deps.

This only stubs packages that (a) are NOT available in the unit-test runner
environment and (b) are never exercised by the unit tests themselves — they're
merely imported as side effects of loading the module under test.

Rules upheld:
- We never reload ``fleet_platform.core.config``.
- We never replace partial fleet_platform stubs; only third-party C-extension
  packages that have no meaningful unit-test behaviour are stubbed here.
"""

from __future__ import annotations

import sys
import types


def _stub_if_missing(name: str, attrs: dict | None = None) -> None:
    """Insert a minimal MagicMock-backed module under *name* if not installed."""
    if name in sys.modules:
        return
    mod = types.ModuleType(name)
    for attr, value in (attrs or {}).items():
        setattr(mod, attr, value)
    sys.modules[name] = mod


# bcrypt — only used in fleet_platform.core.auth for password hashing; none of
# the unit tests exercise the hashing paths.
_stub_if_missing(
    "bcrypt",
    {
        "hashpw": lambda *a, **kw: b"$2b$12$stubhash",
        "checkpw": lambda *a, **kw: False,
        "gensalt": lambda *a, **kw: b"$2b$12$stubsalt",
    },
)
