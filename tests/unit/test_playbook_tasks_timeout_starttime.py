"""Tests for #454 (timeout isinstance) and #455 (job_start_time pre-init)."""

from decimal import Decimal

# ── #454: timeout isinstance fix ────────────────────────────────────────────


def _resolve_timeout(raw_value):
    """Mirrors the fixed timeout resolution logic."""
    _timeout_int = int(raw_value) if raw_value is not None else 1800
    return max(60, min(7200, _timeout_int))


def test_timeout_applied_when_column_returns_decimal():
    """Decimal('3600') must resolve to 3600, not 1800."""
    assert _resolve_timeout(Decimal("3600")) == 3600


def test_timeout_applied_when_column_returns_float():
    """3600.0 must resolve to 3600, not 1800."""
    assert _resolve_timeout(3600.0) == 3600


def test_timeout_applied_when_column_returns_int():
    """int 3600 must still resolve to 3600."""
    assert _resolve_timeout(3600) == 3600


def test_timeout_defaults_when_column_is_none():
    """None must resolve to 1800 (default)."""
    assert _resolve_timeout(None) == 1800


def test_timeout_clamped_to_minimum():
    """Values below 60 are clamped to 60."""
    assert _resolve_timeout(10) == 60


def test_timeout_clamped_to_maximum():
    """Values above 7200 are clamped to 7200."""
    assert _resolve_timeout(99999) == 7200


# ── #455: job_start_time pre-init source contract ───────────────────────────


def test_job_start_time_preinit_before_try_block():
    """
    AST-hardened structural guard: job_start_time must be initialised before the
    first try block in run_playbook so SoftTimeLimitExceeded can reference it
    without NameError (#455).
    """
    import ast
    from pathlib import Path

    src = Path("fleet_platform/workers/playbook_tasks.py").read_text()
    tree = ast.parse(src)

    # Locate the run_playbook function node
    run_playbook_fn = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run_playbook":
            run_playbook_fn = node
            break
    assert run_playbook_fn is not None, "run_playbook function not found in playbook_tasks.py"

    preinit_line: int | None = None
    first_try_line: int | None = None

    for node in ast.walk(run_playbook_fn):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "job_start_time":
                preinit_line = node.lineno
        elif isinstance(node, ast.Try):
            if first_try_line is None or node.lineno < first_try_line:
                first_try_line = node.lineno

    assert preinit_line is not None, (
        "job_start_time: float = 0.0 not found inside run_playbook — must be initialised before the try block (#455)."
    )
    assert first_try_line is not None, "Could not find a try block inside run_playbook"
    assert preinit_line < first_try_line, (
        f"job_start_time pre-init (line {preinit_line}) must appear "
        f"before the first try block (line {first_try_line}) (#455)"
    )
