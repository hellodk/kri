"""Unit tests for P1 backend bug fixes (#64, #105, #126)."""
import ast
from pathlib import Path


def _src(path: str) -> str:
    return Path(path).read_text()


def _parse(path: str) -> ast.Module:
    return ast.parse(Path(path).read_text())


def test_credential_resolver_has_logging():
    """credential_resolver.py must log decryption failures."""
    src = _src("fleet_platform/services/credential_resolver.py")
    assert "logger" in src, "credential_resolver must use logging for decryption failures"
    assert "warning" in src or "Warning" in src, (
        "credential_resolver must log a warning on decryption failure"
    )


def test_security_route_no_blocking_subprocess():
    """security.py integration_status must not call blocking subprocess.run in async context."""
    src = _src("fleet_platform/api/routes/security.py")
    assert "to_thread" in src, (
        "security.py must use asyncio.to_thread to avoid blocking the event loop"
    )


def test_alerts_route_no_blocking_urlopen():
    """alerts.py test_webhook must not call blocking urlopen in async context."""
    src = _src("fleet_platform/api/routes/alerts.py")
    assert "to_thread" in src, (
        "alerts.py must use asyncio.to_thread to avoid blocking the event loop"
    )


def test_llm_list_models_allows_viewer():
    """GET /llm/models must be accessible to viewer role (not restricted to operator/admin)."""
    src = _src("fleet_platform/api/routes/llm.py")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            if node.name == "list_models":
                func_src = ast.unparse(node)
                assert "viewer" in func_src, (
                    "list_models must allow viewer role — model catalog is read-only"
                )
                return
    raise AssertionError("list_models function not found in llm.py")


def test_llm_list_models_has_auth_dependency():
    """list_models must declare a require_role Depends parameter."""
    tree = _parse("fleet_platform/api/routes/llm.py")
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            if node.name == "list_models":
                func_src = ast.unparse(node)
                assert "Depends" in func_src and "require_role" in func_src, (
                    "list_models must use Depends(require_role(...)) for auth"
                )
                return
    raise AssertionError("list_models function not found in llm.py")
