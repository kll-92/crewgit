from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from conftest import git_commit

from crewgit.contracts import write_task_file
from crewgit.models import ContractError, GateError
from crewgit.runner import Runner


def test_run_merge_and_provenance(workspace: Path) -> None:
    runner = Runner(workspace)
    run = runner.run_task("T-1")
    assert run.status == "passed"
    assert {gate.name for gate in run.gates} == {"scope", "budget", "lint", "tests", "review"}
    assert run.commit and run.diff_sha256
    assert runner.git.note_show(run.commit) is not None

    merged = runner.merge(run.run_id)
    body = subprocess.run(
        ["git", "log", "-1", "--format=%B"], cwd=str(workspace), capture_output=True, text=True, check=True
    ).stdout
    assert "Crewgit-Task: T-1" in body
    assert "Crewgit-Run: " in body and "Crewgit-Contract-Hash: " in body
    assert merged["commit"]
    assert (workspace / "cart.py").read_text(encoding="utf-8") == 'MESSAGE = "hello"\n'
    assert runner.board()["counts"]["done"] == 1
    assert runner.git.is_clean()


def test_replay_reproduces_the_diff(workspace: Path) -> None:
    runner = Runner(workspace)
    run = runner.run_task("T-1")
    replay = runner.replay(run.run_id)
    assert replay.reproduced is True
    assert replay.diff_sha256 == run.diff_sha256


def test_scope_violation_is_blocked(workspace: Path) -> None:
    write_task_file(
        workspace / "tasks" / "T-2.yaml",
        {
            "id": "T-2",
            "title": "sneaky packaging edit",
            "scope": ["cart.py"],
            "mock_actions": [{"op": "write", "path": "pyproject.toml", "content": '[project]\nversion = "9"\n'}],
        },
    )
    git_commit(workspace, "task T-2")
    runner = Runner(workspace)
    run = runner.run_task("T-2")
    assert run.status == "failed"
    scope_gate = run.gate("scope")
    assert scope_gate is not None and scope_gate.status == "fail"
    assert "pyproject.toml" in scope_gate.detail
    with pytest.raises(GateError):
        runner.merge(run.run_id)


def test_dependencies_block_a_run(workspace: Path) -> None:
    write_task_file(
        workspace / "tasks" / "T-2.yaml",
        {"id": "T-2", "title": "first", "scope": ["cart.py"], "mock_actions": []},
    )
    write_task_file(
        workspace / "tasks" / "T-3.yaml",
        {"id": "T-3", "title": "second", "scope": ["test_cart.py"], "depends_on": ["T-2"], "mock_actions": []},
    )
    git_commit(workspace, "tasks T-2 T-3")
    with pytest.raises(ContractError) as exc:
        Runner(workspace).run_task("T-3")
    assert "dependencies" in exc.value.message


def test_dirty_main_is_refused(workspace: Path) -> None:
    (workspace / "cart.py").write_text('MESSAGE = "uncommitted"\n', encoding="utf-8")
    with pytest.raises(Exception) as exc:
        Runner(workspace).run_task("T-1")
    assert "dirty" in str(exc.value)


def test_force_merge_records_the_override(workspace: Path) -> None:
    write_task_file(
        workspace / "tasks" / "T-9.yaml",
        {
            "id": "T-9",
            "title": "out of scope on purpose",
            "scope": ["cart.py"],
            "mock_actions": [{"op": "write", "path": "notes.md", "content": "hello\n"}],
        },
    )
    git_commit(workspace, "task T-9")
    runner = Runner(workspace)
    run = runner.run_task("T-9")
    assert run.status == "failed"
    merged = runner.merge(run.run_id, force=True, reason="demo of an audited override")
    assert merged["run"].status == "forced"
    body = subprocess.run(
        ["git", "log", "-1", "--format=%B"], cwd=str(workspace), capture_output=True, text=True, check=True
    ).stdout
    assert "Crewgit-Override: demo of an audited override" in body
