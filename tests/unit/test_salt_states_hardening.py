"""
Source-contract + structure tests for the #1047 fleet-hardening changes:

- salt/states/base/heartbeat.sls           (token out of world-readable script,
                                            per-os groups, python3 not python3.10,
                                            branched detached restart)
- salt/states/base/process_report_schedule.sls  (cmd.run collector, not state.apply)
- salt/states/base/sbom_scan.sls           (no double /api/v1/ingest prefix,
                                            pillar-guarded, /var/run not /tmp)
- playbooks/roles/salt_master/defaults/main.yml (auto_accept defaults to false)
- salt/returners/ removed                  (no non-doc references remain)
- salt/_grains/mobileconfig.py             (moved out of states/mobileconfig)

Each changed .sls is jinja-stripped ({% ... %} dropped, {{ ... }} replaced with
a placeholder) and parsed with yaml.safe_load to prove it is structurally
valid YAML; token-level assertions pin the security-relevant content.
"""

import re
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Paths resolved relative to this test file — never absolute, per project rules
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SALT_DIR = _REPO_ROOT / "salt"
_BASE_STATES = _SALT_DIR / "states" / "base"

HEARTBEAT_SLS = _BASE_STATES / "heartbeat.sls"
PROCESS_SCHEDULE_SLS = _BASE_STATES / "process_report_schedule.sls"
SBOM_SCAN_SLS = _BASE_STATES / "sbom_scan.sls"
MASTER_DEFAULTS = _REPO_ROOT / "playbooks" / "roles" / "salt_master" / "defaults" / "main.yml"

JINJA_BLOCK_RE = re.compile(r"\{%-?.*?-?%\}", re.DOTALL)
JINJA_EXPR_RE = re.compile(r"\{\{.*?\}\}")

_LINUX_OS_FAMILY_SET = "grains['os_family'] in ['Debian', 'RedHat', 'Suse', 'Arch', 'Gentoo', 'Alpine']"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read(path: Path) -> str:
    assert path.exists(), f"Missing expected file: {path}"
    return path.read_text(encoding="utf-8")


def _strip_jinja(text: str) -> str:
    """Replace jinja with placeholders so the result is plain YAML."""
    text = JINJA_BLOCK_RE.sub(" ", text)
    return JINJA_EXPR_RE.sub("JINJA", text)


def _sls_yaml(path: Path) -> dict:
    """Parse a .sls template into a dict, asserting it stays valid YAML."""
    parsed = yaml.safe_load(_strip_jinja(_read(path)))
    assert isinstance(parsed, dict), f"{path.name} did not parse to a mapping"
    return parsed


def _salt_state(parsed: dict, state_id: str) -> dict:
    """Return the merged opts dict of a state declared in Salt's short syntax
    (`file.managed:` followed by a list of `- opt:` items)."""
    body = parsed[state_id]
    assert isinstance(body, dict) and len(body) == 1, f"unexpected shape for {state_id}"
    opts = next(iter(body.values()))
    if isinstance(opts, list):
        merged: dict = {}
        for item in opts:
            assert isinstance(item, dict), f"non-dict opt in {state_id}: {item!r}"
            merged.update(item)
        return merged
    assert isinstance(opts, dict), f"unexpected opts for {state_id}: {opts!r}"
    return opts


def _non_comment_lines(path: Path) -> str:
    lines = [ln for ln in _read(path).splitlines() if not ln.lstrip().startswith("#")]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# heartbeat.sls
# ---------------------------------------------------------------------------


def test_heartbeat_parses_as_yaml():
    parsed = _sls_yaml(HEARTBEAT_SLS)
    for state_id in (
        "kri_etc_kri_dir",
        "kri_node_token",
        "kri_heartbeat_minion_conf",
        "kri_heartbeat_script",
        "kri_heartbeat_reload_minion",
    ):
        assert state_id in parsed, f"heartbeat.sls missing state {state_id}"


def test_heartbeat_writes_root_only_token_file():
    parsed = _sls_yaml(HEARTBEAT_SLS)
    token_state = _salt_state(parsed, "kri_node_token")
    assert token_state["name"] == "/etc/kri/node_token"
    assert token_state["mode"] == "0600"
    dir_state = _salt_state(parsed, "kri_etc_kri_dir")
    assert dir_state["name"] == "/etc/kri"
    assert dir_state["mode"] == "0700"


def test_heartbeat_script_reads_token_at_runtime_not_baked_in():
    raw = _read(HEARTBEAT_SLS)
    assert "open('/etc/kri/node_token').read().strip()" in raw or (
        'open("/etc/kri/node_token").read().strip()' in raw
    ), "heartbeat script must read the token from /etc/kri/node_token at runtime"


def test_heartbeat_no_python310_anywhere():
    raw = _read(HEARTBEAT_SLS)
    assert "/opt/salt/bin/python3.10" not in raw, (
        "heartbeat.sls must use /opt/salt/bin/python3 (not version-pinned 3.10)"
    )
    assert "/opt/salt/bin/python3" in raw


def test_heartbeat_script_mode_0750_root_owned():
    parsed = _sls_yaml(HEARTBEAT_SLS)
    script_state = _salt_state(parsed, "kri_heartbeat_script")
    assert script_state["mode"] == "0750"
    assert script_state["user"] == "root"


def test_heartbeat_groups_branch_per_os():
    raw = _read(HEARTBEAT_SLS)
    assert _LINUX_OS_FAMILY_SET in raw, "must copy the is_linux set-expression pattern"
    assert "{% if is_linux %}root{% else %}wheel{% endif %}" in raw, "group must be root on Linux, wheel elsewhere"


def test_heartbeat_restart_branched_like_process_report_schedule():
    raw = _non_comment_lines(HEARTBEAT_SLS)
    assert "{% if is_linux %}" in raw
    assert "systemctl restart salt-minion" in raw
    assert "launchctl stop com.saltstack.salt.minion" in raw
    assert "launchctl start com.saltstack.salt.minion" in raw
    assert "nohup" in raw, "restart must stay detached (nohup)"


def test_heartbeat_schedule_still_runs_every_5_minutes():
    parsed = _sls_yaml(HEARTBEAT_SLS)
    contents = _salt_state(parsed, "kri_heartbeat_minion_conf")["contents"]
    assert "function: cmd.run" in contents
    assert "/opt/salt/bin/python3 /usr/local/bin/kri_heartbeat.py" in contents
    assert "minutes: 5" in contents


# ---------------------------------------------------------------------------
# process_report_schedule.sls
# ---------------------------------------------------------------------------


def test_process_report_schedule_parses_as_yaml():
    parsed = _sls_yaml(PROCESS_SCHEDULE_SLS)
    assert "kri_process_report_schedule_conf" in parsed


def test_process_report_schedule_uses_cmd_run_not_state_apply():
    body = _non_comment_lines(PROCESS_SCHEDULE_SLS)
    assert "state.apply" not in body, "schedule must invoke the collector directly (cmd.run), not state.apply"
    parsed = _sls_yaml(PROCESS_SCHEDULE_SLS)
    contents = _salt_state(parsed, "kri_process_report_schedule_conf")["contents"]
    assert "function: cmd.run" in contents
    assert "python3 /opt/kri/process_collector.py" in contents
    assert "seconds: 30" in contents
    assert "run_on_start: True" in contents


def test_process_report_schedule_documents_process_report_prerequisite():
    header = "\n".join(_read(PROCESS_SCHEDULE_SLS).splitlines()[:30])
    assert "base.process_report" in header, (
        "header must document that base.process_report installs psutil + collector "
        "and must be applied once before/with the schedule"
    )


def test_process_report_schedule_keeps_detached_branched_restart():
    body = _non_comment_lines(PROCESS_SCHEDULE_SLS)
    assert "systemctl restart salt-minion" in body
    assert "launchctl stop com.saltstack.salt.minion" in body


# ---------------------------------------------------------------------------
# sbom_scan.sls
# ---------------------------------------------------------------------------


def test_sbom_scan_parses_as_yaml_and_is_pillar_guarded():
    raw = _read(SBOM_SCAN_SLS)
    assert "{% if pillar.get('fleet_platform', {}).get('ingest_url', '') %}" in raw, (
        "whole state must be guarded like heartbeat.sls when pillar is unset"
    )
    _sls_yaml(SBOM_SCAN_SLS)


def test_sbom_scan_url_has_exactly_one_api_prefix_occurrence():
    raw = _read(SBOM_SCAN_SLS)
    # One documented occurrence max (header comment); the URL itself must be
    # ingest_url + /sbom/<id> because ingest_url already ends with /api/v1/ingest.
    assert raw.count("/api/v1/ingest") <= 1
    body = _non_comment_lines(SBOM_SCAN_SLS)
    assert "/api/v1/ingest" not in body, "double prefix bug: ingest_url already ends with /api/v1/ingest"
    assert "['ingest_url'] }}/sbom/{{ grains['id'] }}" in body


def test_sbom_scan_does_not_write_to_world_readable_tmp():
    raw = _read(SBOM_SCAN_SLS)
    assert "/tmp/sbom-" not in raw
    body = _non_comment_lines(SBOM_SCAN_SLS)
    assert "/var/run/kri-sbom-" in body
    assert body.count("/var/run/kri-sbom-") == 3, "scan, upload and cleanup must agree on the path"


# ---------------------------------------------------------------------------
# salt-master auto_accept default
# ---------------------------------------------------------------------------


def test_auto_accept_defaults_to_false_with_ui_comment():
    raw = _read(MASTER_DEFAULTS)
    assert re.search(r"^salt_master_auto_accept:\s*false\s*$", raw, re.MULTILINE), (
        "salt_master_auto_accept must default to false"
    )
    assert "Minion Keys UI" in raw, "comment must explain manual acceptance via the UI"


# ---------------------------------------------------------------------------
# Returner removal + grain relocation
# ---------------------------------------------------------------------------


def test_returner_directory_removed():
    assert not (_SALT_DIR / "returners").exists(), "salt/returners/ must be deleted"


def test_no_non_doc_references_to_returner_remain():
    forbidden = "fleet_platform_return"
    hits = []
    scan_roots = ["fleet_platform", "salt", "playbooks", "tests"]
    for root_name in scan_roots:
        root = _REPO_ROOT / root_name
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.resolve() == Path(__file__).resolve():
                continue
            if path.is_file() and path.suffix in {".py", ".yml", ".yaml", ".sls", ".sh", ".j2"}:
                if forbidden in path.read_text(encoding="utf-8", errors="ignore"):
                    hits.append(str(path))
    assert not hits, f"non-doc references to {forbidden} remain: {hits}"


def test_mobileconfig_grain_moved_to_top_level_grains():
    assert (_SALT_DIR / "_grains" / "mobileconfig.py").is_file(), (
        "custom grain must live at salt/_grains/ so saltutil.sync_grains picks it up"
    )
    assert not (_SALT_DIR / "states" / "mobileconfig" / "_grains").exists(), "old nested _grains tree must be removed"
