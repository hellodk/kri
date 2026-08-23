# tests/unit/test_drift_inputs_1049.py
"""#1049 item 2 — drift engine real inputs.

Covers:
  1. ``==`` exact-pin version constraints in the drift engine (next to ``>=``).
  2. The scheduled ``collect_package_service_facts`` task: mocked ``_run_salt_api``
     returns fake pkg/service dicts and the task must persist a NodeFact whose
     grains carry the ``pkgs`` + ``services`` keys that ``compute_drift`` reads.
  3. The 6h beat entry in ``celery_app.beat_schedule``.
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from fleet_platform.services.drift_engine import compute_drift

# ── 1. == exact-pin support ───────────────────────────────────────────────────


def test_exact_pin_matching_version_passes():
    result = compute_drift(
        {"pkgs": {"git": "2.43.0"}},
        {"packages": {"required": [{"name": "git", "version": "==2.43.0"}]}},
    )
    assert result.version_mismatches == []
    assert result.missing_packages == []
    assert result.drift_score == 0


def test_exact_pin_mismatching_version_fails():
    result = compute_drift(
        {"pkgs": {"git": "2.30.0"}},
        {"packages": {"required": [{"name": "git", "version": "==2.43.0"}]}},
    )
    assert len(result.version_mismatches) == 1
    assert result.version_mismatches[0]["name"] == "git"
    assert result.version_mismatches[0]["actual"] == "2.30.0"
    assert result.version_mismatches[0]["required"] == "==2.43.0"


def test_exact_pin_major_mismatch_severity():
    result = compute_drift(
        {"pkgs": {"python3": "2.7.9"}},
        {"packages": {"required": [{"name": "python3", "version": "==3.12.1"}]}},
    )
    assert result.version_mismatches[0]["severity"] == "major"
    assert result.drift_score == 15  # version_mismatch_major weight


def test_exact_pin_minor_mismatch_severity():
    result = compute_drift(
        {"pkgs": {"python3": "3.12.9"}},
        {"packages": {"required": [{"name": "python3", "version": "==3.12.1"}]}},
    )
    assert result.version_mismatches[0]["severity"] == "minor"
    assert result.drift_score == 5  # version_mismatch_minor weight


def test_ge_constraint_still_works_next_to_exact_pin():
    result = compute_drift(
        {"pkgs": {"a": "1.0.0", "b": "0.9.0"}},
        {
            "packages": {
                "required": [
                    {"name": "a", "version": ">=0.5.0"},  # satisfied
                    {"name": "b", "version": ">=1.0.0"},  # violated
                ]
            }
        },
    )
    assert [m["name"] for m in result.version_mismatches] == ["b"]


def test_supported_operators_documented_in_module_docstring():
    import fleet_platform.services.drift_engine as de

    doc = (de.__doc__ or "") + " "
    assert ">=" in doc, "module docstring must document the >= operator"
    assert "==" in doc, "module docstring must document the == operator"


# ── 2. Scheduled collection task ──────────────────────────────────────────────


def _make_mock_db():
    db = MagicMock()
    db.__enter__ = lambda s: s
    db.__exit__ = MagicMock(return_value=False)
    return db


def _make_mock_redis():
    r = MagicMock()
    r.set.return_value = True  # SETNX succeeds — unique_task lock acquired
    return r


def _salt_api_stub(pkgs=None, services=None):
    """Return a fake _run_salt_api keyed on the salt function name."""

    def fake(function, target, args=None, kwarg=None, timeout=300):
        if function == "pkg.list_pkgs":
            if pkgs is None:
                return {"status": "error", "reason": "boom"}
            return {"status": "ok", "result": [{target: pkgs}]}
        if function == "service.get_all":
            if services is None:
                return {"status": "error", "reason": "boom"}
            return {"status": "ok", "result": [{target: services}]}
        raise AssertionError(f"unexpected salt function {function}")

    return fake


def test_collection_task_persists_pkgs_and_services(monkeypatch):
    from fleet_platform.models.facts import NodeFact
    from fleet_platform.workers import drift_tasks

    node_uuid = uuid.uuid4()
    mock_node = MagicMock()
    mock_node.id = node_uuid
    mock_node.minion_id = "minion-1"

    mock_fact = MagicMock()
    mock_fact.grains = {"os": "MacOS", "brew_pkgs": {"wget": "1.21"}}

    nodes_result = MagicMock()
    nodes_result.scalars.return_value.all.return_value = [mock_node]
    fact_result = MagicMock(**{"scalar_one_or_none.return_value": mock_fact})

    db = _make_mock_db()
    db.execute.side_effect = [nodes_result, fact_result]

    monkeypatch.setattr(drift_tasks, "_COLLECT_STAGGER_SECONDS", 0)
    monkeypatch.setattr(
        drift_tasks,
        "_run_salt_api",
        _salt_api_stub(
            pkgs={"git": "2.43.0", "curl": "8.4.0"},
            services=["ssh", "cron"],
        ),
    )
    monkeypatch.setattr(drift_tasks, "get_sync_db", lambda: db)

    with (
        patch("fleet_platform.services.task_lock._get_sync_redis", return_value=_make_mock_redis()),
        patch.object(drift_tasks.celery_app, "send_task") as send_task,
    ):
        result = drift_tasks.collect_package_service_facts()

    assert result["updated"] >= 1
    added_facts = [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], NodeFact)]
    assert added_facts, "collection task must persist a NodeFact row"
    fact = added_facts[-1]
    # The exact keys compute_drift reads (drift_engine._installed / _check_services):
    assert fact.grains["pkgs"] == {"git": "2.43.0", "curl": "8.4.0"}
    assert fact.grains["services"] == ["ssh", "cron"]
    # Prior grains are preserved by the merge — only our two keys are refreshed.
    assert fact.grains["os"] == "MacOS"
    assert fact.grains["brew_pkgs"] == {"wget": "1.21"}
    assert fact.node_id == node_uuid
    db.commit.assert_called()

    # Drift recomputation is triggered so scores become fresh immediately.
    send_task.assert_called()
    sent_names = [call.args[0] if call.args else call.kwargs.get("task") for call in send_task.call_args_list]
    assert any("drift_tasks.compute_drift" in str(n) for n in sent_names)


def test_compute_drift_consumes_collected_payload_keys():
    """The persisted payload shape feeds the engine end-to-end."""
    grains = {
        "pkgs": {"git": "2.30.0"},
        "services": ["sshd", "telnet"],
    }
    baseline = {
        "packages": {"required": [{"name": "git", "version": ">=2.39.0"}]},
        "services": {"required_stopped": ["telnet"], "required_running": ["sshd"]},
    }
    result = compute_drift(grains, baseline)
    assert [m["name"] for m in result.version_mismatches] == ["git"]
    assert [d["service"] for d in result.service_drift] == ["telnet"]


def test_collection_task_skips_node_on_salt_api_error(monkeypatch):
    from fleet_platform.models.facts import NodeFact
    from fleet_platform.workers import drift_tasks

    mock_node = MagicMock()
    mock_node.id = uuid.uuid4()
    mock_node.minion_id = "minion-err"

    nodes_result = MagicMock()
    nodes_result.scalars.return_value.all.return_value = [mock_node]

    db = _make_mock_db()
    db.execute.side_effect = [nodes_result]

    monkeypatch.setattr(drift_tasks, "_COLLECT_STAGGER_SECONDS", 0)
    monkeypatch.setattr(drift_tasks, "_run_salt_api", _salt_api_stub(pkgs=None, services=["ssh"]))
    monkeypatch.setattr(drift_tasks, "get_sync_db", lambda: db)

    with (
        patch("fleet_platform.services.task_lock._get_sync_redis", return_value=_make_mock_redis()),
        patch.object(drift_tasks.celery_app, "send_task") as send_task,
    ):
        result = drift_tasks.collect_package_service_facts()

    assert result["updated"] == 0
    assert result["skipped"] >= 1
    added_facts = [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], NodeFact)]
    assert added_facts == []
    send_task.assert_not_called()


def test_collection_task_has_singleton_guard(monkeypatch):
    """The sweep must carry a unique_task guard like refresh_all_node_grains (#1048)."""
    from fleet_platform.workers import drift_tasks

    fn = getattr(drift_tasks.collect_package_service_facts, "run", drift_tasks.collect_package_service_facts)
    assert getattr(fn, "lock_ttl", None) == 3600, (
        "collect_package_service_facts must be wrapped in @unique_task with a 6h-safe ttl"
    )


# ── 3. Beat schedule entry ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("entry_name", "expected_task"),
    [("collect-package-service-facts", "fleet_platform.workers.drift_tasks.collect_package_service_facts")],
)
def test_beat_entry_present(entry_name, expected_task):
    from fleet_platform.workers.celery_app import celery_app

    beat = celery_app.conf.beat_schedule
    assert entry_name in beat, f"missing beat entry {entry_name!r}"
    entry = beat[entry_name]
    assert entry["task"] == expected_task
    schedule = entry["schedule"]
    seconds = schedule.total_seconds() if hasattr(schedule, "total_seconds") else float(schedule)
    assert seconds == 21600.0, "collection must run every 6 hours"
