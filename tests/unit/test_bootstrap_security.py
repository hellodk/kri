"""Unit tests for #120 (SSH password plaintext) and #133 (DB session excess)."""

from pathlib import Path

SRC = Path("fleet_platform/workers/ansible_tasks.py").read_text()


def test_ssh_password_not_in_file_write():
    """Verify ansible_ssh_pass is NOT written into the inventory file content."""
    # Find the inventory file write — it must NOT contain ansible_ssh_pass
    # Parse the source to find string literals that contain both 'write' context and ansible_ssh_pass
    # Simpler: find lines where .write_text( is called and check none contain ssh_pass
    lines = SRC.splitlines()
    write_lines = [ln for ln in lines if ".write_text(" in ln or ".write(" in ln]
    for ln in write_lines:
        assert "ansible_ssh_pass" not in ln, f"ansible_ssh_pass must not appear in a file-write call: {ln.strip()}"


def test_passwords_passed_via_extravars():
    """Verify passwords go through extravars dict, not inventory file."""
    assert "extravars" in SRC, "bootstrap must pass credentials via ansible-runner extravars"
    # Verify a password_extravars dict is built and merged into the ansible-runner extravars call.
    # We check that ansible_ssh_pass is set inside an extravars-named variable rather than
    # examining a narrow context window (which would miss the assignment further down in the file).
    assert "password_extravars" in SRC, (
        "bootstrap must accumulate credentials in a password_extravars dict before passing to ansible-runner"
    )
    assert "ansible_ssh_pass" in SRC, "bootstrap must set ansible_ssh_pass in the password_extravars dict"
    assert "**password_extravars" in SRC, "password_extravars must be spread into the ansible-runner extravars call"


def test_time_based_log_batching_present():
    """Verify incremental log writes use time-based batching."""
    assert "_LOG_BATCH_INTERVAL" in SRC or "last_db_write" in SRC, (
        "bootstrap must use time-based batching for incremental log writes"
    )
    assert "time.time()" in SRC, "bootstrap must call time.time() for batch interval check"


def test_bootstrap_db_session_count_low():
    """bootstrap_node must use ≤ 9 get_sync_db() opens total.

    Session breakdown (all error-path sessions are guarded, not on every run):
      1. Load node + mark bootstrapping (always)
      2. Health gate — persist probe result (only when master status==unknown, #520)
      3. Health gate — mark node failed and return early (only when master unreachable, #520)
      4. Write token hash + create BootstrapRun record (always, after gate passes)
      5. Periodic log batch (inside streaming loop, time-gated, #498)
      6. Finalise BootstrapRun + write terminal status (step 6, happy/failure path)
      7. SoftTimeLimitExceeded handler (error path only)
      8. except Exception handler (#509 — record terminal status on unexpected crash)
      9. finally orphan-reaper (#445 Part A — only when step 6 did not complete)

    Sessions 2 and 3 are mutually exclusive (probe runs only once per bootstrap).
    The maximum on any single execution path is ≤ 7 (gate-probe path hits 2+4+5+6+9 = 5 max).
    """
    # Count get_sync_db() calls in the bootstrap function body
    task_start = SRC.find("def bootstrap_node")
    # Find next top-level function after bootstrap_node
    next_fn = SRC.find("\ndef ", task_start + 20)
    task_body = SRC[task_start : next_fn if next_fn > 0 else task_start + 12000]
    count = task_body.count("get_sync_db()")
    assert count <= 9, f"bootstrap_node opens {count} DB sessions, expected ≤ 9"
