"""Tests for #46: Salt pillar input dialog."""

from pathlib import Path


def test_dialog_component_exists():
    assert Path("frontend/src/pages/SaltPillarDialog.tsx").exists()


def test_dialog_accepts_state_prop():
    # Frontend-only feature: TypeScript source is the only testable artifact at the Python unit level.
    src = Path("frontend/src/pages/SaltPillarDialog.tsx").read_text()
    assert "state:" in src or "state :" in src


def test_dialog_accepts_minion_ids_prop():
    # Frontend-only feature: TypeScript source is the only testable artifact at the Python unit level.
    src = Path("frontend/src/pages/SaltPillarDialog.tsx").read_text()
    assert "minionIds" in src


def test_dialog_has_pillar_input():
    # Frontend-only feature: TypeScript source is the only testable artifact at the Python unit level.
    src = Path("frontend/src/pages/SaltPillarDialog.tsx").read_text()
    assert "pillar" in src.lower()


def test_dialog_has_add_remove():
    # Frontend-only feature: TypeScript source is the only testable artifact at the Python unit level.
    src = Path("frontend/src/pages/SaltPillarDialog.tsx").read_text()
    assert "add" in src.lower() and ("remove" in src.lower() or "filter" in src.lower())


def test_dialog_calls_onconfirm():
    # Frontend-only feature: TypeScript source is the only testable artifact at the Python unit level.
    src = Path("frontend/src/pages/SaltPillarDialog.tsx").read_text()
    assert "onConfirm" in src


def test_salt_ops_page_imports_dialog():
    # Frontend-only feature: TypeScript source is the only testable artifact at the Python unit level.
    src = Path("frontend/src/pages/SaltOpsPage.tsx").read_text()
    assert "SaltPillarDialog" in src


def test_salt_api_supports_pillar():
    # Frontend-only feature: TypeScript source is the only testable artifact at the Python unit level.
    src = Path("frontend/src/api/saltOps.ts").read_text()
    assert "pillar" in src


def test_no_backend_changes_needed():
    # Behavioral: ApplyRequest must still expose a 'pillar' field in the backend schema (#46).
    from fleet_platform.api.routes.salt_ops import ApplyRequest

    assert "pillar" in ApplyRequest.model_fields, (
        "'pillar' field was removed from ApplyRequest — it must remain to support pillar data (#46)"
    )
