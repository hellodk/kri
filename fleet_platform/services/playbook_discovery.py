# fleet_platform/services/playbook_discovery.py
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class PlaybookEntry:
    filename: str        # "deploy_config.yml" or "roles/salt_minion"
    name: str            # human-readable name
    description: str | None
    entry_type: str      # "playbook" | "role"
    default_vars: dict = field(default_factory=dict)
    lint_errors: list[str] = field(default_factory=list)


def _lint_yaml(path: Path) -> list[str]:
    """Return list of error strings, empty if valid."""
    try:
        with open(path) as f:
            # consume all documents in multi-doc YAML files
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


def _discover_playbooks(playbooks_dir: Path) -> list[PlaybookEntry]:
    results = []
    for path in sorted(playbooks_dir.glob("*.yml")):
        lint_errors = _lint_yaml(path)
        try:
            raw = path.read_text()
            data = yaml.safe_load(raw)
            if not isinstance(data, list) or not data:
                continue
            play_name = data[0].get("name", path.stem)
            default_vars = data[0].get("vars", {}) or {}
            results.append(PlaybookEntry(
                filename=path.name,
                name=play_name,
                description=_parse_description(raw),
                entry_type="playbook",
                default_vars=default_vars if isinstance(default_vars, dict) else {},
                lint_errors=lint_errors,
            ))
        except Exception:
            continue
    return results


def _discover_roles(playbooks_dir: Path) -> list[PlaybookEntry]:
    roles_dir = playbooks_dir / "roles"
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
        results.append(PlaybookEntry(
            filename=f"roles/{role_path.name}",
            name=role_path.name.replace("_", " ").title(),
            description=description,
            entry_type="role",
            default_vars=default_vars,
            lint_errors=lint_errors,
        ))
    return results


def discover_all(playbooks_dir: Path) -> list[PlaybookEntry]:
    return _discover_playbooks(playbooks_dir) + _discover_roles(playbooks_dir)
