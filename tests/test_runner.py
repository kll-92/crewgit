from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from conftest import git_commit

from crewgit.agents import registry
from crewgit.agents.base import Adapter, AgentResult
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


def test_run_can_be_recovered_from_git_notes(workspace: Path) -> None:
    runner = Runner(workspace)
    run = runner.run_task("T-1")
    assert run.commit

    # Simulate a fresh clone: local manifests, the board cache and the note stay.
    shutil.rmtree(workspace / ".crewgit" / "runs")
    (workspace / ".crewgit" / "board.db").unlink(missing_ok=True)
    recovered = Runner(workspace).load_run(run.run_id)
    assert recovered.status == "passed"
    assert recovered.diff_sha256 == run.diff_sha256
    assert recovered.commit == run.commit


def test_reviewer_cannot_write_untracked_files(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class EvilReviewer(Adapter):
        name = "evil"

        def describe(self, ctx) -> str:  # noqa: ANN001 - test double
            return "evil"

        def run(self, ctx):  # noqa: ANN001 - test double
            (ctx.worktree / "EVIL.txt").write_text("reviewer was here", encoding="utf-8")
            return AgentResult(exit_code=0, stdout='{"verdict": "approve"}')

    monkeypatch.setitem(registry.ADAPTERS, "evil", EvilReviewer)
    config_path = workspace / ".crewgit" / "config.yaml"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["agents"]["reviewer"] = {"adapter": "evil"}
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    git_commit(workspace, "evil reviewer")

    run = Runner(workspace).run_task("T-1")
    gate = run.gate("review")
    assert gate is not None
    assert gate.status == "fail"
    assert "reviewer_boundary_violation" in gate.detail
    assert run.status == "failed"


def test_unparseable_review_goes_to_a_human(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class ChattyReviewer(Adapter):
        name = "chatty"

        def describe(self, ctx) -> str:  # noqa: ANN001 - test double
            return "chatty"

        def run(self, ctx):  # noqa: ANN001 - test double
            return AgentResult(exit_code=0, stdout="looks good to me")

    monkeypatch.setitem(registry.ADAPTERS, "chatty", ChattyReviewer)
    config_path = workspace / ".crewgit" / "config.yaml"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["agents"]["reviewer"] = {"adapter": "chatty"}
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    git_commit(workspace, "chatty reviewer")

    run = Runner(workspace).run_task("T-1")
    gate = run.gate("review")
    assert gate is not None and gate.status == "error"
    assert run.status == "needs_human"
    assert "not valid JSON" in gate.detail


def test_stats_does_not_invent_a_zero_cost(workspace: Path) -> None:
    runner = Runner(workspace)
    runner.run_task("T-1")
    stats = runner.stats()
    task = stats["tasks"][0]
    assert task["unmetered_runs"] == 1
    assert task["cost_usd"] is None
    assert stats["totals"]["unmetered_runs"] == 1


def test_replay_reproduces_the_diff(workspace: Path) -> None:
    runner = Runner(workspace)
    run = runner.run_task("T-1")
    replay = runner.replay(run.run_id)
    assert replay.reproduced is True
    assert replay.replay_of == run.run_id
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
