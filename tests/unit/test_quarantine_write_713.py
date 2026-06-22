"""Unit tests for quarantine write surface: quotas, TTL sweep, listing (#713)."""

from __future__ import annotations

import os
import time

import pytest

from fleet_platform.services import agent_quarantine as q


def test_write_and_read_roundtrip(tmp_path):
    meta = q.write_artifact("op@x.com", "sess1", "play.yml", "- hosts: all\n", root=tmp_path)
    assert meta["filename"] == "play.yml"
    assert meta["id"] == "sess1:play.yml"
    content, read_meta = q.read_artifact("op@x.com", "sess1", "play.yml", root=tmp_path)
    assert content == "- hosts: all\n"
    assert read_meta["filename"] == "play.yml"


def test_artifact_files_are_0600(tmp_path):
    q.write_artifact("op@x.com", "sess1", "play.yml", "x: 1\n", root=tmp_path)
    target = q.session_dir("op@x.com", "sess1", root=tmp_path) / "play.yml"
    assert oct(os.stat(target).st_mode & 0o777) == oct(q.FILE_MODE)


def test_oversize_artifact_rejected(tmp_path):
    big = "a" * (q.ARTIFACT_MAX_BYTES + 1)
    with pytest.raises(q.QuarantineError, match="cap"):
        q.write_artifact("op@x.com", "sess1", "big.yml", big, root=tmp_path)


def test_session_quota_enforced(tmp_path, monkeypatch):
    monkeypatch.setattr(q, "SESSION_QUOTA_BYTES", 100)
    monkeypatch.setattr(q, "ARTIFACT_MAX_BYTES", 1000)
    q.write_artifact("op@x.com", "s", "a.yml", "a" * 60, root=tmp_path)
    with pytest.raises(q.QuarantineError, match="session quota"):
        q.write_artifact("op@x.com", "s", "b.yml", "b" * 60, root=tmp_path)


def test_user_quota_enforced(tmp_path, monkeypatch):
    monkeypatch.setattr(q, "USER_QUOTA_BYTES", 100)
    monkeypatch.setattr(q, "SESSION_QUOTA_BYTES", 1000)
    monkeypatch.setattr(q, "ARTIFACT_MAX_BYTES", 1000)
    q.write_artifact("op@x.com", "s1", "a.yml", "a" * 60, root=tmp_path)
    with pytest.raises(q.QuarantineError, match="user quota"):
        q.write_artifact("op@x.com", "s2", "b.yml", "b" * 60, root=tmp_path)


def test_reserved_meta_suffix_rejected(tmp_path):
    with pytest.raises(q.QuarantineError, match="reserved"):
        q.write_artifact("op@x.com", "s", "evil.meta.json", "x: 1", root=tmp_path)


def test_path_traversal_filename_rejected(tmp_path):
    with pytest.raises(q.QuarantineError):
        q.write_artifact("op@x.com", "s", "../../etc/passwd", "x", root=tmp_path)


def test_list_artifacts_across_sessions(tmp_path):
    q.write_artifact("op@x.com", "s1", "a.yml", "x: 1", root=tmp_path)
    time.sleep(0.01)
    q.write_artifact("op@x.com", "s2", "b.yml", "y: 2", root=tmp_path)
    items = q.list_artifacts("op@x.com", root=tmp_path)
    names = {i["filename"] for i in items}
    assert names == {"a.yml", "b.yml"}
    # newest first
    assert items[0]["filename"] == "b.yml"
    # meta sidecars are never listed as artifacts
    assert all(not i["filename"].endswith(".meta.json") for i in items)


def test_sweep_removes_expired_only(tmp_path):
    q.write_artifact("op@x.com", "old", "a.yml", "x: 1", root=tmp_path)
    q.write_artifact("op@x.com", "new", "b.yml", "y: 2", root=tmp_path)
    old_dir = q.session_dir("op@x.com", "old", root=tmp_path)
    # Backdate the old session's files well past the TTL.
    past = time.time() - q.TTL_SECONDS - 3600
    for f in old_dir.rglob("*"):
        os.utime(f, (past, past))
    os.utime(old_dir, (past, past))
    removed = q.sweep_expired(root=tmp_path)
    assert str(old_dir) in removed
    assert not old_dir.exists()
    assert q.session_dir("op@x.com", "new", root=tmp_path).exists()


def test_list_empty_for_unknown_user(tmp_path):
    assert q.list_artifacts("nobody@x.com", root=tmp_path) == []
