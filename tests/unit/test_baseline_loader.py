import pytest
from pathlib import Path

from fleet_platform.services.baseline_loader import (
    load_baseline_yaml,
    validate_baseline,
)


def test_load_baseline_yaml_from_file(tmp_path):
    yml = tmp_path / "test.yaml"
    yml.write_text("name: test\npackages:\n  required:\n    - name: git\n")
    data = load_baseline_yaml(str(yml))
    assert data["name"] == "test"
    assert data["packages"]["required"][0]["name"] == "git"


def test_validate_baseline_valid():
    errors = validate_baseline({"name": "global", "packages": {"required": []}})
    assert errors == []


def test_validate_baseline_missing_name():
    errors = validate_baseline({"packages": {"required": []}})
    assert any("name" in e for e in errors)


def test_validate_baseline_no_sections():
    errors = validate_baseline({"name": "empty"})
    assert any("packages" in e or "services" in e for e in errors)


def test_validate_baseline_invalid_target_type():
    errors = validate_baseline({
        "name": "x",
        "target_type": "invalid",
        "packages": {"required": []},
    })
    assert any("target_type" in e for e in errors)
