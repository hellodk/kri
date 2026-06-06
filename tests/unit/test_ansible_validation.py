# tests/unit/test_ansible_validation.py
import pytest


def test_valid_minion_id():
    from fleet_platform.workers.ansible_tasks import _validate_minion_id

    assert _validate_minion_id("mac-mini-01") == "mac-mini-01"
    assert _validate_minion_id("mac.mini.01") == "mac.mini.01"
    assert _validate_minion_id("node_01") == "node_01"


def test_invalid_minion_id_path_traversal():
    from fleet_platform.workers.ansible_tasks import _validate_minion_id

    with pytest.raises(ValueError, match="Invalid minion ID"):
        _validate_minion_id("../etc/passwd")


def test_invalid_minion_id_yaml_injection():
    from fleet_platform.workers.ansible_tasks import _validate_minion_id

    with pytest.raises(ValueError, match="Invalid minion ID"):
        _validate_minion_id("foo\n  bar: baz")


def test_invalid_minion_id_spaces():
    from fleet_platform.workers.ansible_tasks import _validate_minion_id

    with pytest.raises(ValueError, match="Invalid minion ID"):
        _validate_minion_id("mac mini 01")


def test_safe_label_strips_traversal():
    from fleet_platform.workers.playbook_tasks import _safe_label

    result = _safe_label("../../etc/hosts")
    assert "/" not in result
    assert ".." not in result


def test_safe_label_valid():
    from fleet_platform.workers.playbook_tasks import _safe_label

    assert _safe_label("my-group-name") == "my-group-name"


def test_safe_label_empty_becomes_unknown():
    from fleet_platform.workers.playbook_tasks import _safe_label

    assert _safe_label("...") == "unknown"
