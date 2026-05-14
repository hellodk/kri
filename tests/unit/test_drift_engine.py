# tests/unit/test_drift_engine.py
import pytest
from fleet_platform.services.drift_engine import compute_drift, DriftResult


_GRAINS_FULL = {
    "pkgs": {
        "git": "2.43.0",
        "python3": "3.12.2",
        "teamviewer": "15.51.0",   # forbidden package
    },
    "services": ["com.apple.screensharing"],  # should be stopped
}

_BASELINE_FULL = {
    "packages": {
        "required": [
            {"name": "git", "version": ">=2.39.0"},
            {"name": "python3"},
            {"name": "node"},  # missing
        ],
        "forbidden": [
            {"name": "teamviewer"},
        ],
    },
    "services": {
        "required_stopped": ["com.apple.screensharing"],
    },
}


def test_compute_drift_returns_result():
    result = compute_drift({}, {})
    assert isinstance(result, DriftResult)


def test_clean_node_scores_zero():
    result = compute_drift(
        {"pkgs": {"git": "2.43.0"}},
        {"packages": {"required": [{"name": "git"}]}},
    )
    assert result.drift_score == 0
    assert result.missing_packages == []


def test_missing_required_package_detected():
    result = compute_drift(
        {"pkgs": {"git": "2.43.0"}},
        {"packages": {"required": [{"name": "git"}, {"name": "node"}]}},
    )
    assert len(result.missing_packages) == 1
    assert result.missing_packages[0]["name"] == "node"


def test_missing_package_adds_20_to_score():
    result = compute_drift(
        {},
        {"packages": {"required": [{"name": "git"}]}},
    )
    assert result.drift_score == 20


def test_forbidden_package_detected():
    result = compute_drift(
        {"pkgs": {"teamviewer": "15.0"}},
        {"packages": {"forbidden": [{"name": "teamviewer"}]}},
    )
    assert len(result.extra_packages) == 1
    assert result.extra_packages[0]["name"] == "teamviewer"


def test_forbidden_package_adds_10_to_score():
    result = compute_drift(
        {"pkgs": {"teamviewer": "15.0"}},
        {"packages": {"forbidden": [{"name": "teamviewer"}]}},
    )
    assert result.drift_score == 10


def test_version_mismatch_detected():
    result = compute_drift(
        {"pkgs": {"git": "2.30.0"}},
        {"packages": {"required": [{"name": "git", "version": ">=2.39.0"}]}},
    )
    assert len(result.version_mismatches) == 1
    assert result.version_mismatches[0]["name"] == "git"


def test_version_major_mismatch_severity():
    result = compute_drift(
        {"pkgs": {"python3": "2.7.0"}},
        {"packages": {"required": [{"name": "python3", "version": ">=3.11.0"}]}},
    )
    assert result.version_mismatches[0]["severity"] == "major"


def test_service_drift_detected():
    result = compute_drift(
        {"pkgs": {}, "services": ["com.apple.screensharing"]},
        {"services": {"required_stopped": ["com.apple.screensharing"]}},
    )
    assert len(result.service_drift) == 1
    assert result.service_drift[0]["expected"] == "stopped"


def test_score_capped_at_100():
    # 10 missing packages × 20 = 200 → capped at 100
    many_missing = [{"name": f"pkg{i}"} for i in range(10)]
    result = compute_drift(
        {},
        {"packages": {"required": many_missing}},
    )
    assert result.drift_score == 100


def test_case_insensitive_package_matching():
    result = compute_drift(
        {"pkgs": {"Git": "2.43.0"}},
        {"packages": {"required": [{"name": "git"}]}},
    )
    assert result.missing_packages == []


def test_full_baseline_composite_score():
    result = compute_drift(_GRAINS_FULL, _BASELINE_FULL)
    assert result.drift_score > 0
    assert len(result.missing_packages) == 1   # node missing
    assert len(result.extra_packages) == 1     # teamviewer present
    assert len(result.service_drift) == 1      # screensharing running
