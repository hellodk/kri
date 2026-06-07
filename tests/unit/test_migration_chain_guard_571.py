"""#571: every Alembic migration must define MODULE-LEVEL revision/down_revision
and the versions must form a single linear chain.

Migration 042 declared its IDs only in the docstring, so alembic couldn't locate
it and the chain died at 041 (live DB missing every 042/043/044 column). This
guard fails if any migration lacks module-level identifiers or the chain breaks.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "fleet_platform/db/migrations/versions"


def _module_assignments(path: Path) -> dict[str, object]:
    """Return module-level simple name=constant assignments from a .py file."""
    tree = ast.parse(path.read_text())
    out: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                out[node.targets[0].id] = "<non-literal>"
    return out


def _migration_files() -> list[Path]:
    return sorted(p for p in VERSIONS.glob("*.py") if p.name != "__init__.py")


def test_every_migration_has_module_level_revision_ids():
    missing = []
    for p in _migration_files():
        a = _module_assignments(p)
        if "revision" not in a or "down_revision" not in a:
            missing.append(p.name)
    assert not missing, f"migrations missing module-level revision/down_revision: {missing}"


def test_migrations_form_single_linear_chain():
    revs: dict[str, str | None] = {}
    for p in _migration_files():
        a = _module_assignments(p)
        revs[str(a.get("revision"))] = a.get("down_revision")  # type: ignore[assignment]
    # exactly one root (down_revision is None)
    roots = [r for r, d in revs.items() if d is None]
    assert len(roots) == 1, f"expected exactly one root migration, got {roots}"
    # every non-root down_revision points at a known revision
    known = set(revs)
    dangling = [(r, d) for r, d in revs.items() if d is not None and d not in known]
    assert not dangling, f"down_revision points to unknown revision(s): {dangling}"
    # no two migrations share a down_revision (single head / no branches)
    parents = [d for d in revs.values() if d is not None]
    dupes = {d for d in parents if parents.count(d) > 1}
    assert not dupes, f"multiple migrations share a down_revision (branch/multiple heads): {dupes}"
