"""Regression tests for webssh.py security fixes (issues #85)."""

import ast
import inspect


def test_session_list_requires_role():
    from fleet_platform.api.routes import webssh

    source = inspect.getsource(webssh)
    tree = ast.parse(source)
    # Find the list_sessions function and verify it uses require_role
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "list_sessions":
            func_source = ast.unparse(node)
            assert "require_role" in func_source, "list_sessions must use require_role, not get_current_user"
            return
    raise AssertionError("list_sessions not found")


def test_session_recording_requires_role():
    from fleet_platform.api.routes import webssh

    source = inspect.getsource(webssh)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_session_recording":
            func_source = ast.unparse(node)
            assert "require_role" in func_source, "get_session_recording must use require_role"
            return
    raise AssertionError("get_session_recording not found")


def test_security_events_requires_role():
    from fleet_platform.api.routes import webssh

    source = inspect.getsource(webssh)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "list_security_events":
            func_source = ast.unparse(node)
            assert "require_role" in func_source, "list_security_events must use require_role"
            return
    raise AssertionError("list_security_events not found")
