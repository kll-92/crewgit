"""Shared fixtures: a real temporary git repository with one task contract."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from crewgit.config import write_default_config
from crewgit.contracts import write_task_file
from crewgit.gitops import Git


def git_commit(root: Path, message: str) -> str:
    subprocess.run(["git", "add", "-A"], cwd=str(root), check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            message,
        ],
        cwd=str(root),
        check=True,
        capture_output=True,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(root), capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=str(tmp_path), check=True
    )
    (tmp_path / "cart.py").write_text('MESSAGE = "hi"\n', encoding="utf-8")
    (tmp_path / "test_cart.py").write_text(
        'from cart import MESSAGE\n\ndef test_message():\n    assert MESSAGE == "hello"\n',
        encoding="utf-8",
    )
    write_default_config(tmp_path, "test-project")
    write_task_file(
        tmp_path / "tasks" / "T-1.yaml",
        {
            "id": "T-1",
            "title": "say hello",
            "agent": "coder",
            "scope": ["cart.py"],
            "acceptance": {"tests": f"{sys.executable} -m pytest -q test_cart.py"},
            "budget": {"max_files": 2, "max_lines": 20},
            "mock_actions": [
                {
                    "op": "patch",
                    "path": "cart.py",
                    "find": 'MESSAGE = "hi"',
                    "replace": 'MESSAGE = "hello"',
                }
            ],
        },
    )
    Git(tmp_path).ensure_excluded()
    git_commit(tmp_path, "init")
    return tmp_path
