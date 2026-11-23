from __future__ import annotations

import json
from pathlib import Path

from crewgit.gitops import Git


def test_worktree_commit_diff_note_merge(workspace: Path) -> None:
    git = Git(workspace)
    base = git.head()
    worktree = workspace / ".crewgit" / "worktrees" / "T-9-R-1"
    git.add_worktree(worktree, "crewgit/T-9/R-1", base)
    assert git.is_clean()

    (worktree / "cart.py").write_text('MESSAGE = "hello"\n', encoding="utf-8")
    commit = git.commit_all(worktree, "feat(T-9): hello\n\nCrewgit-Task: T-9")
    assert commit
    assert git.changed_files(base, commit) == ["cart.py"]
    stat = git.numstat(base, commit)
    assert stat["files"] == 1 and stat["insertions"] == 1

    git.note_add(commit, json.dumps({"run_id": "R-1"}), lock_path=workspace / ".crewgit" / "notes.lock")
    note = git.note_show(commit)
    assert note is not None and json.loads(note)["run_id"] == "R-1"

    merge_commit = git.merge_no_ff("crewgit/T-9/R-1", "merge: T-9")
    assert merge_commit
    assert (workspace / "cart.py").read_text(encoding="utf-8").strip() == 'MESSAGE = "hello"'

    git.remove_worktree(worktree)
    git.delete_branch("crewgit/T-9/R-1")
    assert len(git.worktrees()) == 1


def test_commit_all_returns_none_without_changes(workspace: Path) -> None:
    git = Git(workspace)
    base = git.head()
    worktree = workspace / ".crewgit" / "worktrees" / "empty"
    git.add_worktree(worktree, "crewgit/T-0/R-0", base)
    assert git.commit_all(worktree, "nothing") is None
    git.remove_worktree(worktree)


def test_ensure_excluded_keeps_runtime_out_of_status(workspace: Path) -> None:
    git = Git(workspace)
    git.ensure_excluded()
    exclude = (workspace / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert ".crewgit/worktrees/" in exclude
    assert ".crewgit/" not in exclude.split()
    # config stays committable while runtime dirs disappear
    runtime = workspace / ".crewgit" / "worktrees" / "x"
    runtime.mkdir(parents=True, exist_ok=True)
    assert git.is_clean() is True
    assert ".crewgit" not in git.porcelain()
