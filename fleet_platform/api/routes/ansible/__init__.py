# fleet_platform/api/routes/ansible/__init__.py
# ruff: noqa: I001
"""Ansible route package.

Importing this package registers all route handlers on the shared ``router``.
``main.py`` does ``app.include_router(ansible.router, ...)`` — that still works
because ``router`` is re-exported here.

The import order below is semantically required: _router must be resolved
first (it creates the APIRouter instance), then sub-modules import from it
and attach their handlers, then extravars are re-exported.  isort must not
re-order these groups.
"""

# 1. Shared router — must be imported before sub-modules attempt to use it.
from fleet_platform.api.routes.ansible._router import router  # noqa: F401

# 2. Sub-modules attach their route handlers to the shared router as a
#    side-effect of being imported.
from fleet_platform.api.routes.ansible import bootstrap  # noqa: F401
from fleet_platform.api.routes.ansible import files  # noqa: F401
from fleet_platform.api.routes.ansible import jobs  # noqa: F401
from fleet_platform.api.routes.ansible import misc  # noqa: F401
from fleet_platform.api.routes.ansible import playbooks  # noqa: F401
from fleet_platform.api.routes.ansible import sources  # noqa: F401

# 3. Re-export the extravars helpers that tests import from this package
#    (preserved from the original flat module).
from fleet_platform.services.extravars import _SENSITIVE_EV_KEYS  # noqa: F401
from fleet_platform.services.extravars import _scrub_extravars  # noqa: F401

# 4. Re-export route handler functions that test modules import directly from
#    this package (preserved from the original flat module's public surface).
from fleet_platform.api.routes.ansible.misc import get_task_status  # noqa: F401
from fleet_platform.api.routes.ansible.playbooks import run_playbook_endpoint  # noqa: F401
