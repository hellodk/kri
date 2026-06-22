"""Validation pipeline for agent-authored artifacts (#713).

Every playbook/state the agent writes runs this gauntlet *before* it touches the
quarantine dir:

  1. 64 KB size cap
  2. ``yaml.safe_load`` (never ``load`` — no arbitrary tags)
  3. shape schema (looks like a playbook / SLS at all)
  4. dangerous-pattern scan (rm -rf /, forkbomb, dd to device, curl|sh, TLS bypass)
  5. forbidden-module scan (raw/script for Ansible; cmd.run-to-shell etc. for Salt)

A failure at any step rejects the artifact. The scan is deliberately
conservative: this is defense-in-depth behind quarantine + human review, not the
only gate, so false positives (warnings) are acceptable but escapes are not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import yaml

MAX_BYTES = 64 * 1024

# Patterns that are never acceptable in a generated artifact. Each is (regex, label).
_DANGEROUS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"rm\s+-rf\s+(/|/\*|~|\$HOME)(\s|$|'|\")"), "recursive root/home delete"),
    (re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"), "fork bomb"),
    (re.compile(r"\bdd\b[^\n]*\bof=/dev/(sd|nvme|disk|rdisk|hd)"), "dd to block device"),
    (re.compile(r"(curl|wget)\s[^\n|]*\|\s*(sudo\s+)?(ba)?sh"), "pipe-to-shell remote exec"),
    (re.compile(r"mkfs\.|>\s*/dev/sd"), "filesystem/device overwrite"),
    (re.compile(r"chmod\s+-R\s+0?777\s+/"), "world-writable root"),
    (
        re.compile(r"--no-check-certificate|validate_certs\s*:\s*(no|false)|verify\s*=\s*False|insecure_skip_verify"),
        "TLS verification bypass",
    ),
    (re.compile(r"/etc/(shadow|sudoers)\b"), "sensitive system file access"),
    (re.compile(r"\b(0\.0\.0\.0/0|nc\s+-l|ncat\s+-l|/dev/tcp/)"), "raw network egress/listener"),
]

# Ansible modules that allow unconstrained execution — forbidden in generated content.
_FORBIDDEN_ANSIBLE_MODULES = {"raw", "ansible.builtin.raw", "script", "ansible.builtin.script"}

# Salt execution functions that are too broad for a generated state.
_FORBIDDEN_SALT_FUNCTIONS = {"cmd.run", "cmd.shell", "cmd.powershell"}


@dataclass
class ValidationResult:
    valid: bool
    kind: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    parsed: Any = None

    def as_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "kind": self.kind, "errors": self.errors, "warnings": self.warnings}


def _scan_dangerous(content: str) -> list[str]:
    found: list[str] = []
    for pattern, label in _DANGEROUS_PATTERNS:
        if pattern.search(content):
            found.append(f"dangerous pattern: {label}")
    return found


def _iter_task_modules(tasks: Any):
    """Yield module keys used across a list of Ansible tasks (best-effort)."""
    if not isinstance(tasks, list):
        return
    reserved = {
        "name",
        "when",
        "loop",
        "with_items",
        "register",
        "vars",
        "tags",
        "become",
        "become_user",
        "notify",
        "block",
        "rescue",
        "always",
        "ignore_errors",
        "changed_when",
        "failed_when",
        "delegate_to",
        "run_once",
    }
    for task in tasks:
        if not isinstance(task, dict):
            continue
        for key in task:
            if key not in reserved:
                yield key
        # Recurse into block/rescue/always.
        for sub in ("block", "rescue", "always"):
            yield from _iter_task_modules(task.get(sub))


def validate_ansible_playbook(content: str) -> ValidationResult:
    res = ValidationResult(valid=True, kind="ansible_playbook")
    if len(content.encode("utf-8")) > MAX_BYTES:
        res.valid = False
        res.errors.append(f"artifact exceeds {MAX_BYTES}-byte cap")
        return res
    try:
        parsed = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        res.valid = False
        res.errors.append(f"invalid YAML: {str(exc).splitlines()[0] if str(exc) else 'parse error'}")
        return res
    res.parsed = parsed

    if not isinstance(parsed, list):
        res.valid = False
        res.errors.append("an Ansible playbook must be a list of plays")
        return res
    for i, play in enumerate(parsed):
        if not isinstance(play, dict):
            res.valid = False
            res.errors.append(f"play[{i}] is not a mapping")
            continue
        if "hosts" not in play and "import_playbook" not in play:
            res.errors.append(f"play[{i}] has no 'hosts' or 'import_playbook'")  # warning-level shape
        for module in _iter_task_modules(play.get("tasks")) if "tasks" in play else []:
            if module in _FORBIDDEN_ANSIBLE_MODULES:
                res.valid = False
                res.errors.append(f"forbidden module in play[{i}]: {module}")

    for d in _scan_dangerous(content):
        res.valid = False
        res.errors.append(d)
    return res


def validate_salt_state(content: str) -> ValidationResult:
    res = ValidationResult(valid=True, kind="salt_state")
    if len(content.encode("utf-8")) > MAX_BYTES:
        res.valid = False
        res.errors.append(f"artifact exceeds {MAX_BYTES}-byte cap")
        return res
    try:
        parsed = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        res.valid = False
        res.errors.append(f"invalid YAML: {str(exc).splitlines()[0] if str(exc) else 'parse error'}")
        return res
    res.parsed = parsed

    if not isinstance(parsed, dict):
        res.valid = False
        res.errors.append("a Salt state must be a mapping of state-ids to declarations")
        return res
    for state_id, decl in parsed.items():
        if state_id == "include":
            continue
        if not isinstance(decl, dict):
            res.errors.append(f"state '{state_id}' is not a mapping")
            continue
        for fn in decl:
            # Salt state functions look like "pkg.installed" / "cmd.run".
            if fn in _FORBIDDEN_SALT_FUNCTIONS:
                res.valid = False
                res.errors.append(f"forbidden function in '{state_id}': {fn}")

    for d in _scan_dangerous(content):
        res.valid = False
        res.errors.append(d)
    return res


def validate_artifact(content: str, kind: str) -> ValidationResult:
    if kind == "ansible_playbook":
        return validate_ansible_playbook(content)
    if kind == "salt_state":
        return validate_salt_state(content)
    res = ValidationResult(valid=False, kind=kind)
    res.errors.append(f"unknown artifact kind: {kind}")
    return res
