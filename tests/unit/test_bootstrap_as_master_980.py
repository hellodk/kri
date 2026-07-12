"""Tests for #980 — Master-promotion Phase A: bootstrap "as master" toggle.

When ``as_master=True`` on a bootstrap request, a successful bootstrap should
auto-register the node as a SaltMaster and enqueue provisioning (mirrors
``promote_node_to_master`` in salt_masters.py, but synchronous, inside
``bootstrap_node`` in ansible_tasks.py).

These are schema + source-contract tests (no live DB/Celery); they verify the
wiring exists at the right call sites without exercising the full bootstrap
pipeline end to end.

All paths are relative to the repository root, resolved via pathlib from this
file's location (never absolute), so the test works regardless of cwd.
"""

from pathlib import Path

import pytest

from fleet_platform.schemas.ansible import BootstrapRequest

REPO_ROOT = Path(__file__).resolve().parents[2]
ANSIBLE_TASKS = REPO_ROOT / "fleet_platform" / "workers" / "ansible_tasks.py"
BOOTSTRAP_SVC = REPO_ROOT / "fleet_platform" / "services" / "bootstrap_svc.py"


def test_bootstrap_request_as_master_defaults_false():
    req = BootstrapRequest(minion_id="mm1", target_ip="1.2.3.4")
    assert req.as_master is False


def test_bootstrap_request_as_master_true_accepted():
    req = BootstrapRequest(minion_id="mm1", target_ip="1.2.3.4", as_master=True)
    assert req.as_master is True


@pytest.fixture(scope="module")
def ansible_tasks_source() -> str:
    return ANSIBLE_TASKS.read_text()


@pytest.fixture(scope="module")
def bootstrap_svc_source() -> str:
    return BOOTSTRAP_SVC.read_text()


def test_bootstrap_node_signature_includes_as_master(ansible_tasks_source: str):
    """`bootstrap_node`'s parameter list must accept `as_master: bool = False`."""
    idx = ansible_tasks_source.index("def bootstrap_node(")
    # Grab up to the closing `) -> dict:` of the signature.
    sig_end = ansible_tasks_source.index("-> dict:", idx)
    signature = ansible_tasks_source[idx:sig_end]
    assert "as_master: bool = False" in signature


def test_bootstrap_node_registers_salt_master_guarded_by_as_master(ansible_tasks_source: str):
    """The task must gate SaltMaster creation + provision_master dispatch on as_master."""
    assert "if _bootstrap_succeeded and as_master:" in ansible_tasks_source
    assert "SaltMaster(" in ansible_tasks_source
    assert '"fleet_platform.workers.ansible_tasks.provision_master"' in ansible_tasks_source


def test_bootstrap_svc_threads_as_master_into_delay(bootstrap_svc_source: str):
    """queue_node_bootstrap must forward as_master into bootstrap_node.delay(...)."""
    assert "as_master: bool = False" in bootstrap_svc_source
    delay_idx = bootstrap_svc_source.index(".delay(")
    delay_call = bootstrap_svc_source[delay_idx : delay_idx + 400]
    assert "as_master=as_master" in delay_call
