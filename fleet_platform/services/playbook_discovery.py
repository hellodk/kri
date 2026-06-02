# fleet_platform/services/playbook_discovery.py
"""Discover Ansible playbooks and roles from a directory tree.

Scans:
  - <root>/*.yml               — top-level playbooks
  - <root>/<subdir>/*.yml      — one level of subdirectories (e.g. playbooks/, deploy/)
  - <root>/roles/<name>/       — top-level roles
  - <root>/playbooks/roles/<name>/  — roles inside a playbooks/ subdir

Skips 'roles' subdirectories when scanning for playbooks (handled separately).
Skips files that are not valid Ansible play lists (e.g. vars files, handlers).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_log = logging.getLogger(__name__)

# Subdirectory names to skip when scanning for playbooks
_SKIP_SUBDIRS = frozenset({
    "roles", "tasks", "handlers", "vars", "defaults", "meta",
    "templates", "files", "group_vars", "host_vars", ".git",
    "collections",  # Ansible collections contain thousands of test YAMLs — skip entirely
})


_VAR_DESCRIPTIONS_KEY = "_kri_var_descriptions"


@dataclass
class PlaybookEntry:
    filename: str        # "deploy_config.yml", "playbooks/deploy.yml", "roles/salt_minion"
    name: str            # human-readable name
    description: str | None
    entry_type: str      # "playbook" | "role"
    default_vars: dict = field(default_factory=dict)
    var_descriptions: dict = field(default_factory=dict)  # {var_name: help_text}
    lint_errors: list[str] = field(default_factory=list)


def _extract_var_descriptions(vars_dict: dict) -> tuple[dict, dict]:
    """Split _kri_var_descriptions out of vars_dict.

    Returns (clean_vars, descriptions) where clean_vars has the meta-key removed
    and descriptions is the {var_name: help_text} mapping (empty dict if absent).
    """
    descriptions = vars_dict.pop(_VAR_DESCRIPTIONS_KEY, {}) or {}
    if not isinstance(descriptions, dict):
        descriptions = {}
    return vars_dict, descriptions


def _lint_yaml(path: Path) -> list[str]:
    """Return list of error strings, empty if valid."""
    try:
        with open(path) as f:
            list(yaml.safe_load_all(f))
        return []
    except yaml.YAMLError as e:
        return [str(e)]


def _parse_description(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# Description:"):
            return stripped[len("# Description:"):].strip()
    return None


def _is_playbook(path: Path) -> tuple[bool, str, dict]:
    """Return (is_playbook, name, default_vars) for a YAML file."""
    try:
        raw = path.read_text()
        data = yaml.safe_load(raw)
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            return False, "", {}
        # A playbook play dict has at least one of these keys; vars/handler files do not.
        first = data[0]
        _PLAY_KEYS = {"hosts", "import_playbook", "name", "roles", "tasks"}
        if not (_PLAY_KEYS & first.keys()):
            return False, "", {}
        play_name = first.get("name", path.stem)
        default_vars = first.get("vars", {}) or {}
        return True, play_name, default_vars if isinstance(default_vars, dict) else {}
    except Exception:
        return False, "", {}


def _discover_playbooks_in_dir(scan_dir: Path, prefix: str = "") -> list[PlaybookEntry]:
    """Discover playbooks in a single directory (non-recursive)."""
    results = []
    for path in sorted(scan_dir.glob("*.yml")):
        lint_errors = _lint_yaml(path)
        ok, play_name, default_vars = _is_playbook(path)
        if not ok:
            continue
        filename = f"{prefix}{path.name}" if prefix else path.name
        try:
            raw = path.read_text()
            clean_vars, var_descs = _extract_var_descriptions(default_vars)
            results.append(PlaybookEntry(
                filename=filename,
                name=play_name,
                description=_parse_description(raw),
                entry_type="playbook",
                default_vars=clean_vars,
                var_descriptions=var_descs,
                lint_errors=lint_errors,
            ))
        except Exception:
            continue
    return results


def _discover_roles_in_dir(roles_dir: Path, prefix: str = "roles/") -> list[PlaybookEntry]:
    """Discover roles in a roles/ directory."""
    if not roles_dir.is_dir():
        return []
    results = []
    for role_path in sorted(roles_dir.iterdir()):
        if not role_path.is_dir():
            continue
        defaults_path = role_path / "defaults" / "main.yml"
        default_vars: dict = {}
        description: str | None = None
        lint_errors: list[str] = []
        if defaults_path.exists():
            lint_errors = _lint_yaml(defaults_path)
            try:
                raw = defaults_path.read_text()
                parsed = yaml.safe_load(raw)
                if isinstance(parsed, dict):
                    default_vars = parsed
                description = _parse_description(raw)
            except Exception:
                pass
        clean_vars, var_descs = _extract_var_descriptions(default_vars)
        results.append(PlaybookEntry(
            filename=f"{prefix}{role_path.name}",
            name=role_path.name.replace("_", " ").title(),
            description=description,
            entry_type="role",
            default_vars=clean_vars,
            var_descriptions=var_descs,
            lint_errors=lint_errors,
        ))
    return results


def discover_all(playbooks_dir: Path) -> list[PlaybookEntry]:
    """Discover all playbooks and roles under *playbooks_dir*.

    Scans root-level *.yml, one level of subdirectories (skipping role-reserved
    names), root-level roles/, and playbooks/roles/ for external repos that
    use the standard Ansible collection layout.
    """
    entries: list[PlaybookEntry] = []

    if not playbooks_dir.is_dir():
        return entries

    # 1. Root-level playbooks
    entries.extend(_discover_playbooks_in_dir(playbooks_dir))

    # 2. One-level subdirectory scan (e.g. playbooks/, deploy/, provision/)
    for subdir in sorted(playbooks_dir.iterdir()):
        if not subdir.is_dir():
            continue
        if subdir.name in _SKIP_SUBDIRS:
            continue
        # Use subdir name as prefix so filename stays runnable
        entries.extend(_discover_playbooks_in_dir(subdir, prefix=f"{subdir.name}/"))
        # Also look for roles inside this subdir (e.g. playbooks/roles/)
        entries.extend(_discover_roles_in_dir(subdir / "roles", prefix=f"{subdir.name}/roles/"))

    # 3. Root-level roles/
    entries.extend(_discover_roles_in_dir(playbooks_dir / "roles"))

    # Deduplicate by filename (subdirectory scan may overlap with root scan in edge cases)
    seen: set[str] = set()
    deduped: list[PlaybookEntry] = []
    for e in entries:
        if e.filename not in seen:
            seen.add(e.filename)
            deduped.append(e)

    return deduped
