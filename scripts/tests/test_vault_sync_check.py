"""vault_sync_check against real git repositories in a temp dir."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

import vault_sync_check as vsc

DAY = 86400


def git(cwd: Path, *args: str, when: float | None = None) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    if when is not None:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"{int(when)} +0000"
    subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True)


def commit(vault: Path, name: str, when: float) -> None:
    (vault / name).write_text(name)
    git(vault, "add", "-A")
    git(vault, "commit", "-m", name, when=when)


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--bare", "-b", "main", str(remote))
    repo = tmp_path / "vault"
    git(tmp_path, "clone", str(remote), str(repo))
    git(repo, "checkout", "-b", "main")
    commit(repo, "first.md", time.time() - 100 * DAY)
    git(repo, "push", "-u", "origin", "main")
    return repo


def test_synced_vault_is_healthy(vault: Path) -> None:
    assert vsc.problems(vsc.inspect(vault)) == []


def test_recent_unpushed_commit_is_not_yet_a_problem(vault: Path) -> None:
    commit(vault, "note.md", time.time() - 600)
    state = vsc.inspect(vault)
    assert state["unpushed"] == 1
    assert vsc.problems(state) == []


def test_commits_stuck_for_months_are_reported(vault: Path) -> None:
    commit(vault, "june.md", time.time() - 95 * DAY)
    commit(vault, "july.md", time.time() - 84 * DAY)
    found = vsc.problems(vsc.inspect(vault))
    assert len(found) == 1
    assert "2 commits have not reached the remote" in found[0]
    assert "95 days" in found[0]


def test_files_left_uncommitted_are_reported(vault: Path) -> None:
    stale = vault / "SOUL.md"
    stale.write_text("changed")
    old = time.time() - 3 * DAY
    os.utime(stale, (old, old))
    (vault / "fresh.md").write_text("just now")
    found = vsc.problems(vsc.inspect(vault))
    assert found == ["2 changed files are uncommitted (oldest waiting 3 days)"]


def test_file_changed_minutes_ago_is_not_a_problem(vault: Path) -> None:
    (vault / "fresh.md").write_text("just now")
    assert vsc.problems(vsc.inspect(vault)) == []


def test_branch_without_a_remote_is_reported(tmp_path: Path) -> None:
    repo = tmp_path / "solo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    commit(repo, "a.md", time.time())
    assert vsc.problems(vsc.inspect(repo)) == ["the vault branch has no remote to back up to"]


def test_message_says_what_is_at_risk() -> None:
    message = vsc.build_message(["418 commits have not reached the remote"])
    assert "418 commits" in message
    assert "only on this Mac" in message
