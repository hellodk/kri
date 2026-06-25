"""Behavioral tests for the `kri deploy` staleness guard (#902).

`kri deploy` ships both the code and the VERSION banner straight from the local
working tree, so a forgotten/stale feature branch silently deploys old code.
`deploy_freshness_guard` compares HEAD against origin/master and blocks (or
warns) accordingly. These tests build throwaway git repos and drive the guard
directly by `source`-ing scripts/kri (its `main` only runs when executed, not
sourced), so we assert real behavior rather than scraping the source string.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

KRI = Path("scripts/kri").resolve()


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _run_guard(repo: Path, allow_stale: int, no_fetch: int, env: dict | None = None):
    """Source scripts/kri inside `repo` and invoke the guard once.

    Returns the CompletedProcess. stdin is /dev/null so prompt_confirm (which
    reads /dev/tty) fails closed — i.e. an un-confirmed stale deploy aborts.
    """
    script = repo / "scripts" / "kri"
    cmd = f'source "{script}"; deploy_freshness_guard {allow_stale} {no_fetch}'
    return subprocess.run(
        ["bash", "-c", cmd],
        cwd=str(repo),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.fixture
def repos(tmp_path: Path):
    """Create a `work` repo with an `origin` whose master is 1 commit ahead.

    Layout: work/ is checked out on a `stale` branch pointing at the first
    commit, while origin/master has advanced — so work is behind + off-master.
    scripts/kri is copied into work/scripts/ so REPO_DIR resolves to work/.
    """
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    origin.mkdir()
    work.mkdir()
    _git(origin, "init", "--bare", "-b", "master")
    _git(work, "init", "-b", "master")
    _git(work, "config", "user.email", "t@t")
    _git(work, "config", "user.name", "t")

    (work / "VERSION").write_text("0.1.1\n")
    _git(work, "add", "VERSION")
    _git(work, "commit", "-m", "v0.1.1")
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "push", "-u", "origin", "master")

    # Mark the first commit, then advance master and push so origin/master leads.
    first = subprocess.run(
        ["git", "-C", str(work), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    (work / "VERSION").write_text("0.1.2\n")
    _git(work, "commit", "-am", "v0.1.2")
    _git(work, "push", "origin", "master")

    # Drop the working tree onto a stale branch behind origin/master.
    _git(work, "checkout", "-b", "stale", first)
    (work / "VERSION").write_text("0.1.1\n")  # banner would show the stale ver

    scripts = work / "scripts"
    scripts.mkdir()
    shutil.copy(KRI, scripts / "kri")
    return work


def test_stale_off_master_aborts_without_confirmation(repos: Path):
    """A stale/off-master checkout must abort (non-zero) when not confirmed."""
    proc = _run_guard(repos, allow_stale=0, no_fetch=1)
    assert proc.returncode != 0, proc.stdout + proc.stderr
    combined = proc.stdout + proc.stderr
    assert "STALE" in combined
    assert "aborted" in combined.lower()


def test_allow_stale_flag_overrides(repos: Path):
    """--allow-stale (arg=1) proceeds past the gate despite being stale."""
    proc = _run_guard(repos, allow_stale=1, no_fetch=1)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Proceeding anyway" in (proc.stdout + proc.stderr)


def test_kri_allow_stale_env_overrides(repos: Path):
    """KRI_ALLOW_STALE=1 in the environment also bypasses the gate."""
    import os

    env = {**os.environ, "KRI_ALLOW_STALE": "1"}
    proc = _run_guard(repos, allow_stale=0, no_fetch=1, env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_up_to_date_master_passes(repos: Path):
    """On master and level with origin/master the guard passes silently."""
    _git(repos, "checkout", "master")
    proc = _run_guard(repos, allow_stale=0, no_fetch=1)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "up to date" in (proc.stdout + proc.stderr)


def test_not_a_git_checkout_is_a_noop(tmp_path: Path):
    """Outside a git repo (e.g. release tarball) the guard is a no-op."""
    work = tmp_path / "plain"
    (work / "scripts").mkdir(parents=True)
    (work / "VERSION").write_text("9.9.9\n")
    shutil.copy(KRI, work / "scripts" / "kri")
    proc = _run_guard(work, allow_stale=0, no_fetch=1)
    assert proc.returncode == 0, proc.stdout + proc.stderr
