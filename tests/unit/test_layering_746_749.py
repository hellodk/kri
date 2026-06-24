"""Architecture/layering guards for #746 (ARC-2) and #749 (ARC-5).

#746 — the service layer must not import from the API layer. Shared infra (the
async Redis client) now lives in ``fleet_platform.core.redis``; ``api.deps``
re-exports it for backward compatibility.

#749 — API route modules must not import Celery worker *task* modules at import
time, because that pulls the whole worker task import graph into the API process.
Routes dispatch by name via ``celery_app.send_task("task.name", ...)`` instead.
The only ``fleet_platform.workers`` import allowed at a route module's top level is
the shared broker handle ``fleet_platform.workers.celery_app``.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PKG = _REPO_ROOT / "fleet_platform"
_SERVICES_DIR = _PKG / "services"
_ROUTES_DIR = _PKG / "api" / "routes"

# The only worker module a route may import at module top level: the shared
# Celery app (broker handle). It does NOT import the task graph at construction.
_ALLOWED_TOPLEVEL_WORKER_MODULE = "fleet_platform.workers.celery_app"


def _imported_modules(node: ast.AST) -> list[str]:
    """Return the dotted module name(s) an Import/ImportFrom node refers to."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        # Ignore relative imports (level > 0) — they never name fleet_platform.* directly.
        return [node.module] if (node.module and node.level == 0) else []
    return []


def _all_import_nodes(tree: ast.Module) -> list[ast.AST]:
    return [n for n in ast.walk(tree) if isinstance(n, ast.Import | ast.ImportFrom)]


def _toplevel_import_nodes(tree: ast.Module) -> list[ast.AST]:
    return [n for n in tree.body if isinstance(n, ast.Import | ast.ImportFrom)]


def _py_files(directory: Path) -> list[Path]:
    return sorted(p for p in directory.rglob("*.py") if p.name != "__init__.py")


def test_services_do_not_import_api_layer():
    """#746 / ARC-2: no module under fleet_platform/services/ may import fleet_platform.api."""
    offenders: list[str] = []
    for path in _py_files(_SERVICES_DIR):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in _all_import_nodes(tree):
            for mod in _imported_modules(node):
                if mod == "fleet_platform.api" or mod.startswith("fleet_platform.api."):
                    offenders.append(f"{path.relative_to(_REPO_ROOT)}:{node.lineno} imports {mod}")
    assert not offenders, "Service layer must not import the API layer:\n" + "\n".join(offenders)


def test_routes_do_not_import_worker_tasks_at_module_top_level():
    """#749 / ARC-5: route modules must not import worker task modules at import time.

    Only fleet_platform.workers.celery_app (the shared broker handle) is allowed at
    a route module's top level; everything else must be dispatched by name via
    send_task or imported lazily inside a function.
    """
    offenders: list[str] = []
    for path in _py_files(_ROUTES_DIR):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in _toplevel_import_nodes(tree):
            for mod in _imported_modules(node):
                if mod.startswith("fleet_platform.workers") and mod != _ALLOWED_TOPLEVEL_WORKER_MODULE:
                    offenders.append(f"{path.relative_to(_REPO_ROOT)}:{node.lineno} imports {mod}")
    assert not offenders, (
        "Route modules must not import worker task modules at import time "
        "(dispatch by name with celery_app.send_task or import lazily):\n" + "\n".join(offenders)
    )


def test_converted_routes_dispatch_by_name():
    """The routes that previously imported tasks at top level now dispatch by name."""
    for name in ("ingest.py", "drift.py", "ansible.py"):
        src = (_ROUTES_DIR / name).read_text()
        assert "celery_app.send_task(" in src, f"{name} should dispatch Celery tasks by name via send_task"


def test_shared_redis_module_exists_and_is_reexported():
    """get_redis/init_redis/close_redis live in core.redis and api.deps re-exports them."""
    core_redis = (_PKG / "core" / "redis.py").read_text()
    for fn in ("def get_redis", "def init_redis", "def close_redis"):
        assert fn in core_redis, f"core/redis.py must define {fn}"

    deps_src = (_PKG / "api" / "deps.py").read_text()
    deps_tree = ast.parse(deps_src)
    reexports = {
        mod
        for node in _all_import_nodes(deps_tree)
        for mod in _imported_modules(node)
        if mod == "fleet_platform.core.redis"
    }
    assert reexports, "api/deps.py must re-export the redis helpers from fleet_platform.core.redis"
