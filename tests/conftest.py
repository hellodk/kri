# Module-level initialization - runs as soon as conftest is imported
# CRITICAL: Handles the 'platform' package name collision with stdlib platform module

import sys
import importlib.util
from pathlib import Path

# Get the repo root and platform package path
_repo_root = Path(__file__).parent.parent
_platform_pkg_path = _repo_root / "platform"

# Step 1: Import and cache the stdlib platform module
import platform as _stdlib_platform

# Step 2: Preload our 'platform' package into sys.modules
# This ensures that when test modules try to import from it, it's already there
# Loading it early prevents the stdlib module from being found by Python's import system
if _platform_pkg_path.exists():
    spec = importlib.util.spec_from_file_location(
        "platform",
        str(_platform_pkg_path / "__init__.py"),
        submodule_search_locations=[str(_platform_pkg_path)]
    )
    if spec and spec.loader:
        _local_platform = importlib.util.module_from_spec(spec)
        _local_platform.__path__ = [str(_platform_pkg_path)]
        sys.modules["platform"] = _local_platform
        spec.loader.exec_module(_local_platform)

# Step 3: Make stdlib platform available for pytest and dependencies
sys.modules["_stdlib_platform"] = _stdlib_platform

# Step 4: Patch __import__ so pure "import platform" calls get the stdlib version
import builtins

_original_import = builtins.__import__

def _patched_import(name, globals=None, locals=None, fromlist=(), level=0):
    # If something does a pure "import platform" (not "from fleet_platform..."),
    # give them the stdlib version to prevent breaking pytest and other libraries
    if name == "platform" and not fromlist and not level:
        return _stdlib_platform
    return _original_import(name, globals, locals, fromlist, level)

builtins.__import__ = _patched_import


import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client():
    from fleet_platform.api.main import create_app
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac
