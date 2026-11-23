from __future__ import annotations

import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from crewgit.cli import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "crewgit" in result.stdout


def test_init_and_board(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], check=True, capture_output=True)
    result = runner.invoke(app, ["init", "-C", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / ".crewgit" / "config.yaml").exists()

    board = runner.invoke(app, ["board", "-C", str(tmp_path), "--json"])
    assert board.exit_code == 0
    assert "project" in board.stdout


def test_task_new_and_check(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], check=True, capture_output=True)
    assert runner.invoke(app, ["init", "-C", str(tmp_path)]).exit_code == 0
    created = runner.invoke(
        app,
        ["task", "new", "-C", str(tmp_path), "--id", "T-001", "--title", "x", "--scope", "src/**"],
    )
    assert created.exit_code == 0
    check = runner.invoke(app, ["task", "check", "-C", str(tmp_path)])
    assert check.exit_code == 0
    assert "1 contract" in check.stdout

    shown = runner.invoke(app, ["task", "show", "T-001", "-C", str(tmp_path), "--json"])
    assert shown.exit_code == 0
    payload = json.loads(shown.stdout)
    assert payload["task"]["id"] == "T-001"
    assert payload["runs"] == []


def test_dry_run_does_not_execute(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], check=True, capture_output=True)
    assert runner.invoke(app, ["init", "-C", str(tmp_path)]).exit_code == 0
    assert runner.invoke(
        app, ["task", "new", "-C", str(tmp_path), "--id", "T-001", "--title", "x", "--scope", "src/**"]
    ).exit_code == 0
    plan = runner.invoke(app, ["run", "T-001", "-C", str(tmp_path), "--dry-run", "--json"])
    assert plan.exit_code == 0
    assert "prompt_sha256" in plan.stdout
    assert not (tmp_path / ".crewgit" / "worktrees").exists() or not any((tmp_path / ".crewgit" / "worktrees").iterdir())
