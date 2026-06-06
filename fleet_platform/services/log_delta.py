# fleet_platform/services/log_delta.py
# Delta-slicing helpers for playbook log polling (#371).
import re

_RUNNING_MARKER_RE = re.compile(r"\n\n\[running: ([^\]]+)\]\s*$")


def split_running_marker(stdout: str | None) -> tuple[str, str | None]:
    """Split stdout into (append-only base, running-task name or None).

    The worker appends a volatile '\\n\\n[running: <task>]' marker on each flush;
    the base before it only ever grows, so byte offsets into the base are stable.
    """
    if not stdout:
        return "", None
    m = _RUNNING_MARKER_RE.search(stdout)
    if not m:
        return stdout, None
    return stdout[: m.start()], m.group(1)


def slice_from(base: str, from_byte: int) -> str:
    """Return base[from_byte:]; empty when from_byte is at/past the end."""
    if from_byte >= len(base):
        return ""
    return base[from_byte:]
