"""Unified diff between a quarantined artifact and the live tree (#713).

Pure text diffing — no I/O. The route supplies the live content (resolved from
the playbook/state tree with the usual path-traversal guards) and the quarantined
content; this returns a unified diff plus a small changed-line summary the UI
renders next to the Monaco editor.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass


@dataclass
class DiffResult:
    unified: str
    added: int
    removed: int
    is_new: bool

    def as_dict(self) -> dict:
        return {"unified": self.unified, "added": self.added, "removed": self.removed, "is_new": self.is_new}


def diff_text(old: str | None, new: str, *, fromfile: str = "live", tofile: str = "quarantine") -> DiffResult:
    old_lines = (old or "").splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = list(difflib.unified_diff(old_lines, new_lines, fromfile=fromfile, tofile=tofile, lineterm=""))
    added = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))
    return DiffResult(unified="\n".join(diff), added=added, removed=removed, is_new=(old is None or old == ""))
