"""Regression test for issue #399.

Walks every module under fleet_platform/models/ (excluding __init__ and base),
finds all DeclarativeBase subclasses with a __tablename__, and asserts:
  1. The table is registered in Base.metadata.tables (so create_all won't skip it).
  2. The class is importable directly from fleet_platform.models (so app code can
     use it without hunting through submodules).

This test is the regression net — if a future model is added to a module file
but forgotten in __init__.py, this test will catch it immediately.
"""

import importlib
import inspect
import pkgutil
from types import ModuleType
from typing import Any

import pytest

import fleet_platform.models as models_pkg
from fleet_platform.models.base import Base


def _collect_model_classes() -> list[tuple[str, type]]:
    """Return (module_name, class) pairs for every SQLAlchemy model class found
    in fleet_platform/models/*.py, excluding __init__ and base modules."""
    found: list[tuple[str, type]] = []
    pkg_path = models_pkg.__path__
    for finder, module_name, _is_pkg in pkgutil.iter_modules(pkg_path):
        if module_name in ("__init__", "base"):
            continue
        full_name = f"fleet_platform.models.{module_name}"
        module: ModuleType = importlib.import_module(full_name)
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            # Must be a subclass of Base and defined in this module (not an import)
            if (
                obj is not Base
                and issubclass(obj, Base)
                and obj.__module__ == full_name
                and hasattr(obj, "__tablename__")
            ):
                found.append((module_name, obj))
    return found


_MODEL_CLASSES = _collect_model_classes()


@pytest.mark.parametrize("module_name,model_cls", _MODEL_CLASSES, ids=[f"{m}.{c.__name__}" for m, c in _MODEL_CLASSES])
def test_model_table_in_metadata(module_name: str, model_cls: type) -> None:
    """Each model's __tablename__ must appear in Base.metadata.tables."""
    tablename: str = model_cls.__tablename__  # type: ignore[attr-defined]
    assert tablename in Base.metadata.tables, (
        f"{model_cls.__qualname__} (from models/{module_name}.py) defines "
        f"__tablename__={tablename!r} but that table is NOT in Base.metadata.tables. "
        f"Add the import to fleet_platform/models/__init__.py."
    )


@pytest.mark.parametrize("module_name,model_cls", _MODEL_CLASSES, ids=[f"{m}.{c.__name__}" for m, c in _MODEL_CLASSES])
def test_model_importable_from_package(module_name: str, model_cls: type) -> None:
    """Each model class must be importable directly from fleet_platform.models."""
    class_name = model_cls.__name__
    pkg_obj: Any = getattr(models_pkg, class_name, None)
    assert pkg_obj is model_cls, (
        f"{class_name} (from models/{module_name}.py) is not importable from "
        f"fleet_platform.models. Add it to __init__.py imports and __all__."
    )
