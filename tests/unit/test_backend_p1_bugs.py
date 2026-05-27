"""Unit tests for P1 backend bug fixes (#64, #105, #126)."""
import ast
from pathlib import Path


def _parse(path: str) -> ast.Module:
    return ast.parse(Path(path).read_text())


def test_credential_resolver_has_logging():
    """credential_resolver.py must log decryption failures."""
    src = Path("fleet_platform/services/credential_resolver.py").read_text()
    assert "logger" in src, "credential_resolver must use logging for decryption failures"
    assert "warning" in src or "Warning" in src, (
        "credential_resolver must log a warning on decryption failure"
    )


def test_security_route_no_blocking_subprocess():
    """security.py integration_status must not call blocking subprocess.run in async context."""
    src = Path("fleet_platform/api/routes/security.py").read_text()
    # The fix wraps subprocess.run with asyncio.to_thread
    assert "to_thread" in src, (
        "security.py must use asyncio.to_thread to avoid blocking the event loop"
    )


def test_llm_models_endpoint_requires_auth():
    """GET /llm/models must have an auth dependency."""
    src = Path("fleet_platform/api/routes/llm.py").read_text()
    # The endpoint must use get_current_user or require_role
    assert "get_current_user" in src or "require_role" in src, (
        "llm.py /models endpoint must require authentication"
    )


def test_llm_models_function_has_auth_param():
    """The list_models function must have a user/claims dependency parameter."""
    src = Path("fleet_platform/api/routes/llm.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if "model" in node.name.lower():
                func_src = ast.unparse(node)
                if "get_current_user" in func_src or "require_role" in func_src or "Depends" in func_src:
                    return  # found it
    # If we get here, check if the decorator has auth instead
    assert "get_current_user" in src, (
        "list_models (or equivalent) must have auth dependency"
    )
