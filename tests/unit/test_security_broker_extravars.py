"""Tests for #494 (extravars scrub at write) and #495 (ssh_password not in broker)."""

import inspect
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient


def test_scrub_extravars_flat_secret():
    from fleet_platform.api.routes.ansible import _scrub_extravars

    ev = {"ansible_ssh_pass": "s3cr3t", "playbook_name": "test"}
    result = _scrub_extravars(ev)
    assert result["ansible_ssh_pass"] == "***"
    assert result["playbook_name"] == "test"


def test_scrub_extravars_nested_secret():
    from fleet_platform.api.routes.ansible import _scrub_extravars

    ev = {"creds": {"ansible_password": "x", "user": "foo"}}
    result = _scrub_extravars(ev)
    assert result["creds"]["ansible_password"] == "***"
    assert result["creds"]["user"] == "foo"


def test_scrub_extravars_list_of_dicts():
    from fleet_platform.api.routes.ansible import _scrub_extravars

    ev = [{"ansible_sudo_pass": "hunter2"}, {"safe_key": "value"}]
    result = _scrub_extravars(ev)
    assert result[0]["ansible_sudo_pass"] == "***"
    assert result[1]["safe_key"] == "value"


def test_scrub_extravars_none_returns_none():
    from fleet_platform.api.routes.ansible import _scrub_extravars

    assert _scrub_extravars(None) is None


def test_scrub_extravars_empty_dict():
    from fleet_platform.api.routes.ansible import _scrub_extravars

    assert _scrub_extravars({}) == {}


def test_scrub_extravars_all_sensitive_keys():
    from fleet_platform.api.routes.ansible import _SENSITIVE_EV_KEYS

    expected = {
        "ansible_ssh_pass",
        "ansible_become_password",
        "ansible_become_pass",
        "ansible_password",
        "ansible_sudo_pass",
        "vault_password",
        "password",
        "secret",
        "token",
        "api_key",
    }
    assert expected.issubset(_SENSITIVE_EV_KEYS)


def test_scrub_extravars_vault_password():
    from fleet_platform.api.routes.ansible import _scrub_extravars

    ev = {"vault_password": "topsecret", "playbook": "site.yml"}
    result = _scrub_extravars(ev)
    assert result["vault_password"] == "***"
    assert result["playbook"] == "site.yml"


def test_scrub_extravars_ansible_sudo_pass():
    from fleet_platform.api.routes.ansible import _scrub_extravars

    ev = {"ansible_sudo_pass": "sudo123", "env": "prod"}
    result = _scrub_extravars(ev)
    assert result["ansible_sudo_pass"] == "***"
    assert result["env"] == "prod"


def test_run_playbook_signature_has_no_ssh_password():
    """run_playbook task must not accept ssh_password (plaintext broker risk).

    Asserted against the live callable's signature (``inspect.signature``) rather
    than by AST-parsing the source file, so the test reflects the parameters the
    task actually exposes to callers at runtime.
    """
    from fleet_platform.workers.playbook_tasks import run_playbook

    params = inspect.signature(run_playbook).parameters
    assert "ssh_password" not in params, f"run_playbook must not accept ssh_password; params: {list(params)}"


class _FakeResult:
    def scalar_one_or_none(self):
        return None  # no playbook_sources row / no target lookup needed for this path


class _FakeSession:
    """Minimal async session that assigns ids on flush and swallows writes."""

    def __init__(self):
        self.added: list = []

    async def execute(self, *args, **kwargs):
        return _FakeResult()

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    async def commit(self):
        pass

    async def refresh(self, obj):
        pass

    async def rollback(self):
        pass


async def test_run_playbook_endpoint_does_not_pass_ssh_password_to_broker():
    """run_playbook_endpoint must NOT forward ssh_password to the dispatched task.

    #495: even though PlaybookRunRequest accepts ssh_password for API symmetry, a
    plaintext password must never reach the Celery broker. #749: the endpoint
    dispatches by task name via celery_app.send_task(...). We drive the real
    endpoint with a password supplied in the request and assert the captured
    send_task call carries neither the ssh_password key nor its value.
    """
    import fleet_platform.api.routes.ansible.playbooks as playbooks
    from fleet_platform.api import deps
    from fleet_platform.api.main import create_app
    from fleet_platform.core.auth import create_access_token

    app = create_app()

    async def _override_db():
        yield _FakeSession()

    mock_redis = AsyncMock()
    mock_redis.get.return_value = None

    async def _override_redis():
        return mock_redis

    app.dependency_overrides[deps.get_db] = _override_db
    app.dependency_overrides[deps.get_redis] = _override_redis

    token = create_access_token(user_id=str(uuid.uuid4()), email="operator@test.local", role="operator")
    entry = SimpleNamespace(filename="site.yml")
    secret = "PLAINTEXT-SSH-SECRET"

    with (
        patch.object(playbooks, "discover_all", return_value=[entry]),
        patch.object(playbooks, "get_all_playbook_dirs", return_value=["/fake/dir"]),
        patch("fleet_platform.workers.celery_app.celery_app.send_task") as send_task,
    ):
        send_task.return_value = SimpleNamespace(id="task-1")
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            resp = await client.post(
                "/api/v1/ansible/playbooks/run",
                json={
                    "playbook": "site.yml",
                    "target_type": "all",
                    "target_id": "everything",
                    "ssh_username": "deploy",
                    "ssh_password": secret,
                },
            )

    assert resp.status_code == 202, resp.text
    send_task.assert_called_once()
    call_blob = repr(send_task.call_args)
    assert "ssh_password" not in call_blob, f"ssh_password key leaked to broker dispatch: {call_blob}"
    assert secret not in call_blob, f"plaintext ssh password value leaked to broker dispatch: {call_blob}"
    # And the dispatched task is the playbook runner, by name.
    assert send_task.call_args.args[0] == "fleet_platform.workers.playbook_tasks.run_playbook"
