"""#710 Phase A — agent quarantine filesystem scaffolding."""

import os
import stat

import pytest

from fleet_platform.services import agent_quarantine as q


def test_session_dir_layout(tmp_path):
    p = q.session_dir("alice@org", "sess-1", root=tmp_path)
    assert p == (tmp_path / "alice@org" / "sess-1").resolve()


@pytest.mark.parametrize(
    "user,session",
    [
        ("..", "s"),
        ("a/b", "s"),
        ("u", "../escape"),
        ("u", "a/b"),
        ("", "s"),
        ("u", ""),
        ("u\x00", "s"),
        ("u", "s\x00"),
        ("u", "a\\b"),
        ("u", "x" * 256),
    ],
)
def test_traversal_and_injection_components_rejected(tmp_path, user, session):
    with pytest.raises(q.QuarantineError):
        q.session_dir(user, session, root=tmp_path)


def test_ensure_session_dir_creates_with_0700(tmp_path):
    p = q.ensure_session_dir("bob@org", "sess-2", root=tmp_path)
    assert p.is_dir()
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(p.parent).st_mode) == 0o700


def test_assert_within_session_accepts_inside_path(tmp_path):
    sd = q.ensure_session_dir("carol@org", "sess-3", root=tmp_path)
    artifact = sd / "state.sls"
    artifact.write_text("nope: true")
    resolved = q.assert_within_session(artifact, "carol@org", "sess-3", root=tmp_path)
    assert resolved == artifact.resolve()


def test_assert_within_session_rejects_outside_path(tmp_path):
    q.ensure_session_dir("dan@org", "sess-4", root=tmp_path)
    outside = tmp_path / "dan@org" / "sess-4" / ".." / "elsewhere.sls"
    with pytest.raises(q.QuarantineError):
        q.assert_within_session(outside, "dan@org", "sess-4", root=tmp_path)


def test_assert_within_session_rejects_symlink(tmp_path):
    sd = q.ensure_session_dir("eve@org", "sess-5", root=tmp_path)
    target = tmp_path / "secret.txt"
    target.write_text("secret")
    link = sd / "link.sls"
    link.symlink_to(target)
    with pytest.raises(q.QuarantineError):
        q.assert_within_session(link, "eve@org", "sess-5", root=tmp_path)


def test_dir_size_bytes(tmp_path):
    sd = q.ensure_session_dir("fay@org", "sess-6", root=tmp_path)
    (sd / "a.sls").write_text("x" * 100)
    (sd / "b.sls").write_text("y" * 50)
    assert q.dir_size_bytes(sd) == 150
    assert q.dir_size_bytes(tmp_path / "nope") == 0


def test_quota_contract_constants():
    assert q.SESSION_QUOTA_BYTES == 5 * 1024 * 1024
    assert q.USER_QUOTA_BYTES == 50 * 1024 * 1024
    assert q.TTL_SECONDS == 24 * 60 * 60
    assert q.DIR_MODE == 0o700


def test_default_root_is_env_configurable(monkeypatch):
    # Importing fresh with the env set should pick up the override.
    import importlib

    monkeypatch.setenv("AGENT_QUARANTINE_ROOT", "/tmp/kri-quarantine-test")
    reloaded = importlib.reload(q)
    try:
        assert str(reloaded.QUARANTINE_ROOT) == "/tmp/kri-quarantine-test"
    finally:
        monkeypatch.delenv("AGENT_QUARANTINE_ROOT", raising=False)
        importlib.reload(reloaded)
