"""#651 Phase 0 — per-endpoint tool_mode column tests.

Validates:
- Migration 048 has module-level revision/down_revision (linear chain guard)
- LLMEndpointResponse defaults tool_mode to "json" and accepts "native"
- LLMEndpoint ORM model has tool_mode column in __table__.columns
"""

import ast
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "fleet_platform/db/migrations/versions"


# ---------------------------------------------------------------------------
# Migration chain guard (mirrors test_migration_chain_guard_571 logic via AST)
# ---------------------------------------------------------------------------

def _module_assignments(path: Path) -> dict[str, object]:
    tree = ast.parse(path.read_text())
    out: dict[str, object] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                out[node.targets[0].id] = "<non-literal>"
    return out


def _all_migration_files() -> list[Path]:
    return sorted(p for p in VERSIONS.glob("*.py") if p.name != "__init__.py")


def test_migration_048_has_module_level_revision_ids():
    """Migration 048 must declare revision and down_revision at module level."""
    migration = VERSIONS / "048_llm_endpoint_tool_mode.py"
    assert migration.exists(), "Migration 048 file not found"
    a = _module_assignments(migration)
    assert "revision" in a, "048 migration missing module-level 'revision'"
    assert "down_revision" in a, "048 migration missing module-level 'down_revision'"
    assert a["revision"] == "048"
    assert a["down_revision"] == "047"


def test_all_migrations_form_single_linear_chain():
    """Including migration 048, the full chain must remain linear (no branches, no dangling)."""
    revs: dict[str, str | None] = {}
    for p in _all_migration_files():
        a = _module_assignments(p)
        revs[str(a.get("revision"))] = a.get("down_revision")  # type: ignore[assignment]

    roots = [r for r, d in revs.items() if d is None]
    assert len(roots) == 1, f"expected exactly one root migration, got {roots}"

    known = set(revs)
    dangling = [(r, d) for r, d in revs.items() if d is not None and d not in known]
    assert not dangling, f"down_revision points to unknown revision(s): {dangling}"

    parents = [d for d in revs.values() if d is not None]
    dupes = {d for d in parents if parents.count(d) > 1}
    assert not dupes, f"multiple migrations share a down_revision (branch/multiple heads): {dupes}"


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

def _minimal_response_kwargs() -> dict:
    """Minimal valid kwargs for LLMEndpointResponse (no DB needed)."""
    return {
        "id": uuid.uuid4(),
        "name": "test",
        "provider": "openai_compat",
        "base_url": "http://localhost:11434",
        "has_api_key": False,
        "model": "llama3",
        "max_tokens": 4096,
        "is_default": False,
        "enabled": True,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }


def test_llm_endpoint_response_tool_mode_defaults_to_json():
    from fleet_platform.schemas.llm import LLMEndpointResponse

    resp = LLMEndpointResponse(**_minimal_response_kwargs())
    assert resp.tool_mode == "json"


def test_llm_endpoint_response_accepts_native_tool_mode():
    from fleet_platform.schemas.llm import LLMEndpointResponse

    resp = LLMEndpointResponse(**_minimal_response_kwargs(), tool_mode="native")
    assert resp.tool_mode == "native"


def test_llm_endpoint_response_accepts_anthropic_tool_mode():
    from fleet_platform.schemas.llm import LLMEndpointResponse

    resp = LLMEndpointResponse(**_minimal_response_kwargs(), tool_mode="anthropic")
    assert resp.tool_mode == "anthropic"


def test_llm_endpoint_create_tool_mode_defaults_to_json():
    from fleet_platform.schemas.llm import LLMEndpointCreate

    create = LLMEndpointCreate(
        name="test",
        provider="openai_compat",
        base_url="http://localhost:11434",
        model="llama3",
    )
    assert create.tool_mode == "json"


def test_llm_endpoint_update_tool_mode_is_optional():
    from fleet_platform.schemas.llm import LLMEndpointUpdate

    update = LLMEndpointUpdate()
    assert update.tool_mode is None

    update_with_mode = LLMEndpointUpdate(tool_mode="native")
    assert update_with_mode.tool_mode == "native"


# ---------------------------------------------------------------------------
# ORM model column introspection
# ---------------------------------------------------------------------------

def test_llm_endpoint_model_has_tool_mode_column():
    from fleet_platform.models.llm_endpoint import LLMEndpoint

    col_names = {c.name for c in LLMEndpoint.__table__.columns}
    assert "tool_mode" in col_names, f"tool_mode not found in columns: {col_names}"


def test_llm_endpoint_tool_mode_column_server_default():
    from fleet_platform.models.llm_endpoint import LLMEndpoint

    col = LLMEndpoint.__table__.columns["tool_mode"]
    assert col.server_default is not None, "tool_mode column must have a server_default"
    # server_default.arg is the raw DDL text or a ColumnDefault
    sd_text = str(col.server_default.arg)
    assert "json" in sd_text, f"server_default should contain 'json', got: {sd_text!r}"
