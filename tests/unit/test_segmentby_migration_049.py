"""Tests for migration 049: node_process_stats compress_segmentby=node_id.

Verifies:
  1. Module-level revision="049" and down_revision="048" are correct.
  2. The migration text contains compress_segmentby and node_id.
  3. The chain guard (test_migration_chain_guard_571) still passes with 049 in place.
"""

import ast
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[2] / "fleet_platform/db/migrations/versions"
MIGRATION = VERSIONS / "049_process_stats_compress_segmentby.py"


def _module_assignments(path: Path) -> dict:
    """Return module-level simple name=constant assignments."""
    tree = ast.parse(path.read_text())
    out: dict = {}
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


def test_migration_049_module_level_revision():
    assignments = _module_assignments(MIGRATION)
    assert assignments.get("revision") == "049", (
        f"expected revision='049', got {assignments.get('revision')!r}"
    )
    assert assignments.get("down_revision") == "048", (
        f"expected down_revision='048', got {assignments.get('down_revision')!r}"
    )


def test_migration_049_contains_compress_segmentby_node_id():
    text = MIGRATION.read_text()
    assert "compress_segmentby" in text, "migration must reference compress_segmentby"
    assert "node_id" in text, "migration must reference node_id as the segmentby column"


def test_chain_still_linear_after_049():
    """Inline the chain-guard logic so this test file is self-contained."""
    files = sorted(p for p in VERSIONS.glob("*.py") if p.name != "__init__.py")
    revs: dict = {}
    for p in files:
        a = _module_assignments(p)
        revs[str(a.get("revision"))] = a.get("down_revision")

    roots = [r for r, d in revs.items() if d is None]
    assert len(roots) == 1, f"expected exactly one root migration, got {roots}"

    known = set(revs)
    dangling = [(r, d) for r, d in revs.items() if d is not None and d not in known]
    assert not dangling, f"down_revision points to unknown revision(s): {dangling}"

    parents = [d for d in revs.values() if d is not None]
    dupes = {d for d in parents if parents.count(d) > 1}
    assert not dupes, f"multiple migrations share a down_revision (branch/multiple heads): {dupes}"

    assert "049" in known, "migration 049 not found in chain"
