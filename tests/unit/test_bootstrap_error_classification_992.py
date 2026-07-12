"""Regression tests for #992: bootstrap gate failures mislabeled as SSH unreachable.

The salt-master reachability gate (host_prep_gate.yml) prints the bare word
"UNREACHABLE" in its Ansible debug output even when SSH itself succeeded. The
classifier must distinguish that from a real SSH-unreachable failure, which is
signalled by Ansible's own "UNREACHABLE!" host marker or "unreachable=1" in the
PLAY RECAP.
"""

from fleet_platform.workers.ansible_tasks import _classify_ansible_failure_category


def test_gate_failure_is_not_ssh_unreachable():
    """The regression case for #992: SSH worked, only the salt-master gate failed."""
    stdout = (
        "TASK [debug] ***\n"
        "ok: [node1] => {\n"
        '    "msg": "Master 192.168.1.64 (probed via 127.0.0.1) port 4505: UNREACHABLE"\n'
        "}\n"
        "FAILED! => {\n"
        '    "msg": "Target cannot reach any salt-master on 4505/4506"\n'
        "}\n"
    )
    assert _classify_ansible_failure_category(stdout) == "salt_master_gate"


def test_real_ssh_unreachable_host_marker():
    stdout = "fatal: [host]: UNREACHABLE! => {\"changed\": false, \"msg\": \"...\"}\n"
    assert _classify_ansible_failure_category(stdout) == "ssh_unreachable"


def test_real_ssh_unreachable_recap():
    stdout = "PLAY RECAP ***\nhost : ok=0 changed=0 unreachable=1 failed=0\n"
    assert _classify_ansible_failure_category(stdout) == "ssh_unreachable"


def test_auth_failure():
    stdout = "fatal: [host]: FAILED! => {\"msg\": \"Permission denied (publickey,password)\"}\n"
    assert _classify_ansible_failure_category(stdout) == "ssh_auth"


def test_clean_stdout_returns_none():
    stdout = "PLAY RECAP ***\nhost : ok=5 changed=2 unreachable=0 failed=1\n"
    assert _classify_ansible_failure_category(stdout) is None


def test_gate_wins_over_real_unreachable_marker():
    """Ordering guard: gate marker must be checked before the SSH markers."""
    stdout = (
        "Target cannot reach any salt-master on 4505/4506\n"
        "fatal: [host]: UNREACHABLE! => {\"msg\": \"...\"}\n"
    )
    assert _classify_ansible_failure_category(stdout) == "salt_master_gate"
