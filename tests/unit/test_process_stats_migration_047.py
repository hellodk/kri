"""Migration 047: node_process_stats TimescaleDB hypertable (#598).

Static checks on the migration source — no live DB required. The cross-migration
module-level / single-chain invariant is enforced by test_migration_chain_guard_571.
"""

import ast
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[2] / "fleet_platform/db/migrations/versions"
MIGRATION = VERSIONS / "047_node_process_stats.py"


def _source() -> str:
    return MIGRATION.read_text()


def _module_assignments(path: Path) -> dict[str, object]:
    tree = ast.parse(path.read_text())
    out: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                out[node.targets[0].id] = "<non-literal>"
    return out


class TestMigrationMetadata:
    def test_module_level_revision_ids(self) -> None:
        """#571 guard: revision/down_revision must be module-level literals."""
        a = _module_assignments(MIGRATION)
        assert a.get("revision") == "047"
        assert a.get("down_revision") == "046"

    def test_047_is_chain_head(self) -> None:
        """No other migration may descend from 047 — it must be the single head."""
        children = []
        for p in VERSIONS.glob("*.py"):
            if p.name == "__init__.py":
                continue
            if _module_assignments(p).get("down_revision") == "047":
                children.append(p.name)
        assert not children, f"047 is not the head; descended from by {children}"


class TestHypertable:
    def test_creates_table(self) -> None:
        assert 'op.create_table(\n        "node_process_stats"' in _source() or (
            "create_table" in _source() and "node_process_stats" in _source()
        )

    def test_composite_primary_key(self) -> None:
        assert 'sa.PrimaryKeyConstraint("id", "collected_at")' in _source()

    def test_hypertable_on_collected_at(self) -> None:
        assert "create_hypertable('node_process_stats', by_range('collected_at', INTERVAL '1 day')" in _source()

    def test_compression_orderby(self) -> None:
        s = _source()
        assert "timescaledb.compress = true" in s
        assert "compress_orderby = 'collected_at DESC'" in s

    def test_compression_policy_7_days(self) -> None:
        assert "add_compression_policy('node_process_stats', INTERVAL '7 days')" in _source()

    def test_retention_policy_14_days(self) -> None:
        assert "add_retention_policy('node_process_stats', INTERVAL '14 days')" in _source()


class TestDowngrade:
    def test_drops_table_and_policies(self) -> None:
        s = _source()
        assert "remove_retention_policy('node_process_stats'" in s
        assert "remove_compression_policy('node_process_stats'" in s
        assert 'op.drop_table("node_process_stats")' in s
