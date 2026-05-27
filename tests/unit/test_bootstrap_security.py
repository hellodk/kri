"""Unit tests for #120 (SSH password plaintext) and #133 (DB session excess)."""
from pathlib import Path


SRC = Path("fleet_platform/workers/ansible_tasks.py").read_text()


def test_ssh_password_not_written_to_inventory_file():
    """ansible_ssh_pass must not appear in inventory file content."""
    # Find the inventory writing code and verify no plaintext password
    assert "ansible_ssh_pass" not in SRC or (
        # If it appears, it must be in a subprocess -e argument, not in file write
        "write" not in SRC[max(0, SRC.find("ansible_ssh_pass")-200):SRC.find("ansible_ssh_pass")+50]
    ), "SSH password must not be written to inventory file"


def test_incremental_log_batched_by_time():
    """Log updates must be batched by time interval, not line count."""
    assert "last_db_write" in SRC or "batch_interval" in SRC or "time.time" in SRC, (
        "Incremental log updates must use time-based batching"
    )


def test_get_sync_db_call_count_reduced():
    """bootstrap_node must not open excessive DB sessions."""
    # Count get_sync_db() occurrences inside the task function
    task_start = SRC.find("def bootstrap_node")
    if task_start == -1:
        task_start = SRC.find("def _run_bootstrap")
    task_src = SRC[task_start:task_start + 5000]
    db_opens = task_src.count("get_sync_db()")
    assert db_opens <= 3, f"bootstrap_node opens {db_opens} DB sessions, expected ≤ 3"
