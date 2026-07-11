"""Unit tests for the masked ansible command line emitted into bootstrap/provision
output (#960). Secrets must never appear in the rendered command."""

from __future__ import annotations

from fleet_platform.workers.ansible_tasks import _format_ansible_cmdline, _mask_extravar


def test_mask_redacts_credential_keys():
    assert _mask_extravar("ansible_ssh_pass", "hunter2") == "****"
    assert _mask_extravar("ansible_become_password", "hunter2") == "****"
    assert _mask_extravar("node_token", "abc123deadbeef") == "****"
    assert _mask_extravar("kri_salt_api_password", "s3cret") == "****"
    assert _mask_extravar("some_api_secret", "x") == "****"
    assert _mask_extravar("controller_pubkey", "ssh-ed25519 AAAA...") != "****"  # public key is not a secret


def test_mask_passes_normal_values():
    assert _mask_extravar("minion_id", "mm2") == "mm2"
    assert _mask_extravar("ingest_url", "http://100.89.50.27/api/v1/ingest") == "http://100.89.50.27/api/v1/ingest"


def test_mask_truncates_long_nonsecret():
    long = "x" * 200
    out = _mask_extravar("controller_pubkey", long)
    assert out.endswith("...") and len(out) <= 120


def test_cmdline_includes_playbook_inventory_and_masks_secrets():
    extravars = {
        "salt_masters": ["192.168.1.64"],
        "minion_id": "mm2",
        "node_token": "SUPERSECRETTOKEN",
        "ansible_ssh_pass": "hunter2",
        "ansible_become_password": "hunter2",
    }
    out = _format_ansible_cmdline("/app/playbooks/bootstrap_node.yml", "/tmp/inv.ini", extravars)
    # structure
    assert "ansible-playbook" in out
    assert "-i /tmp/inv.ini" in out
    assert "/app/playbooks/bootstrap_node.yml" in out
    assert "-e minion_id=mm2" in out
    # secrets NEVER leak
    assert "SUPERSECRETTOKEN" not in out
    assert "hunter2" not in out
    assert "node_token=****" in out
    assert "ansible_ssh_pass=****" in out
    assert "ansible_become_password=****" in out
