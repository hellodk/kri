"""Tests for #355/#357/#358: honest credential banner, collections pre-flight,
and run_playbook failure classification."""

from pathlib import Path

from fleet_platform.workers.playbook_tasks import (
    _classify_failure,
    _credential_source_banner,
    _playbook_uses_collections,
)

HOSTS = [
    {"hostname": "mm", "ip": "192.168.1.64", "credential_source": "controller"},
    {"hostname": "cylon", "ip": "10.0.0.9", "credential_source": "group:macs"},
]


# ---- #355: banner wording ------------------------------------------------
def test_banner_says_attempting_not_resolved():
    b = _credential_source_banner(HOSTS)
    assert "Attempting" in b
    assert "resolved" not in b.lower()
    assert "mm" in b and "controller" in b


# ---- #358 + #355: failure classification --------------------------------
def test_classify_unreachable():
    out = _classify_failure("fatal: [mm]: UNREACHABLE! => ...", HOSTS, "Install salt", 4, "failed")
    assert "[DIAGNOSIS]" in out
    assert "UNREACHABLE" in out
    assert "mm" in out  # identifies the host


def test_classify_auth_failure_names_credential_source():
    out = _classify_failure("fatal: [mm]: FAILED! => Authentication failure", HOSTS, "Gathering Facts", 4, "failed")
    assert "[DIAGNOSIS]" in out
    # #355: auth failure must point at the credential source that was rejected
    assert "controller" in out
    assert "REJECTED" in out.upper() or "auth" in out.lower()


def test_classify_auth_and_unreachable_are_distinct():
    unreach = _classify_failure("UNREACHABLE!", HOSTS, None, 4, "failed")
    auth = _classify_failure("Permission denied (publickey,password)", HOSTS, None, 4, "failed")
    assert unreach != auth
    assert "UNREACHABLE" in unreach
    assert "UNREACHABLE" not in auth


def test_classify_task_failure_includes_task_name():
    out = _classify_failure("fatal: [mm]: FAILED! => non-zero return code", HOSTS, "Download pkg", 2, "failed")
    assert "Download pkg" in out


def test_classify_timeout():
    out = _classify_failure("", HOSTS, "Install salt", None, "timeout")
    assert "[DIAGNOSIS]" in out and ("timed out" in out.lower() or "timeout" in out.lower())


# ---- #357: collections pre-flight ---------------------------------------
def test_playbook_uses_collections_detects_fqcn(tmp_path):
    pb = tmp_path / "p.yml"
    pb.write_text("- hosts: all\n  tasks:\n    - community.general.apt: name=x\n")
    assert _playbook_uses_collections(pb) is True


def test_playbook_uses_collections_detects_collections_key(tmp_path):
    pb = tmp_path / "p.yml"
    pb.write_text("- hosts: all\n  collections:\n    - community.general\n  tasks: []\n")
    assert _playbook_uses_collections(pb) is True


def test_playbook_uses_collections_false_for_builtin_only(tmp_path):
    pb = tmp_path / "p.yml"
    pb.write_text("- hosts: all\n  tasks:\n    - shell: echo hi\n    - copy: src=a dest=b\n")
    assert _playbook_uses_collections(pb) is False


def test_playbook_uses_collections_missing_file_false(tmp_path):
    assert _playbook_uses_collections(tmp_path / "nope.yml") is False


# ---- source-contract: wired into the worker -----------------------------
def test_worker_uses_classification_and_preflight():
    src = (Path(__file__).parent.parent.parent / "fleet_platform/workers/playbook_tasks.py").read_text()
    assert "_classify_failure(" in src  # #358 used on the failure path
    assert "_playbook_uses_collections(" in src  # #357 pre-flight wired
    assert "collections' / 'installed'" in src or 'collections" / "installed"' in src
