import re

# (key-name pattern, replacement) — redacts the VALUE, keeps the key for debuggability.
_FLAG_RE = re.compile(
    r"(--?(?:password|passwd|pwd|token|api[-_]?key|apikey|secret|access[-_]?key|"
    r"secret[-_]?key|auth|bearer|client[-_]?secret)[=\s])(\S+)",
    re.IGNORECASE,
)
_ENV_RE = re.compile(
    r"\b([A-Z0-9_]*(?:PASSWORD|PASSWD|TOKEN|SECRET|API[-_]?KEY|APIKEY|ACCESS_KEY|"
    r"PRIVATE_KEY|AUTH|BEARER|CREDENTIAL)[A-Z0-9_]*)=(\S+)",
    re.IGNORECASE,
)
# user:password@host  (connection strings / URLs)
_URLCRED_RE = re.compile(r"(://[^:/\s]+:)([^@/\s]+)(@)")

_REDACTED = "<REDACTED>"


def redact_cmdline(cmdline: str | None) -> str | None:
    """Strip secret-looking values from a process command line. Returns None for None."""
    if not cmdline:
        return cmdline
    out = _FLAG_RE.sub(rf"\1{_REDACTED}", cmdline)
    out = _ENV_RE.sub(rf"\1={_REDACTED}", out)
    out = _URLCRED_RE.sub(rf"\1{_REDACTED}\3", out)
    return out
