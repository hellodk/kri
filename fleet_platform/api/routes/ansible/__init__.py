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

# 2. Re-export the extravars helpers that tests import from this package
#    (preserved from the original flat module).
from fleet_platform.services.extravars import _SENSITIVE_EV_KEYS  # noqa: F401
from fleet_platform.services.extravars import _scrub_extravars  # noqa: F401

# 4. Re-export the full public route-handler surface so callers/tests that did
#    `from fleet_platform.api.routes.ansible import <handler>` against the old
#    flat module keep working unchanged. NOTE: tests that PATCH a handler's
#    *dependencies* (celery_app, audit, discover_all, …) must patch them on the
#    sub-module that now owns the handler, e.g.
#    `fleet_platform.api.routes.ansible.playbooks.celery_app`.
from fleet_platform.api.routes.ansible.bootstrap import (  # noqa: F401
    bootstrap,
    bootstrap_history,
    bootstrap_logs,
    bootstrap_run_detail,
    bootstrap_status,
    cancel_bootstrap,
)
from fleet_platform.api.routes.ansible.files import (  # noqa: F401
    get_playbook_file,
    list_playbook_files,
    update_playbook_file,
)
from fleet_platform.api.routes.ansible.jobs import (  # noqa: F401
    cancel_playbook_job,
    get_ansible_job,
    list_ansible_jobs,
)
from fleet_platform.api.routes.ansible.misc import collect_grains, get_task_status  # noqa: F401
from fleet_platform.api.routes.ansible.playbooks import (  # noqa: F401
    get_playbook_content,
    get_playbook_tree,
    list_playbooks,
    playbook_stats,
    run_playbook_endpoint,
)
from fleet_platform.api.routes.ansible.sources import (  # noqa: F401
    add_source,
    import_sources_csv,
    list_sources,
    remove_source,
    sync_sources,
    validate_source,
)
from fleet_platform.api.routes.ansible._router import _BOOTSTRAP_ONLY_PLAYBOOKS  # noqa: F401,E402
