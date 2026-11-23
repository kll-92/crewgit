from __future__ import annotations

import pytest

from crewgit.contracts import build_prompt, prompt_hash
from crewgit.models import (
    Budget,
    ContractError,
    Run,
    Task,
    check_dependencies,
    glob_match,
    scope_violations,
    task_status,
)


@pytest.mark.parametrize(
    ("path", "pattern", "expected"),
    [
        ("src/cart.py", "src/*", True),
        ("src/nested/cart.py", "src/*", False),
        ("src/nested/cart.py", "src/**", True),
        ("anything.py", "**", True),
        ("tests/test_x.py", "tests/**", True),
        ("docs/plan.md", "docs/*.md", True),
        ("docs/plan.txt", "docs/*.md", False),
        ("docs/a/plan.md", "docs/*.md", False),
    ],
)
def test_glob_match(path: str, pattern: str, expected: bool) -> None:
    assert glob_match(path, pattern) is expected


def test_scope_violations_list_outside_paths() -> None:
    bad = scope_violations(
        ["src/cart.py", "pyproject.toml", ".crewgit/config.yaml", "tasks/T-1.yaml"],
        ["src/**"],
    )
    assert bad == ["pyproject.toml", ".crewgit/config.yaml", "tasks/T-1.yaml"]


def test_scope_forbid_wins() -> None:
    assert scope_violations(["docs/private/x.md"], ["docs/**"], ["docs/private/**"]) == [
        "docs/private/x.md"
    ]


def test_task_requires_valid_scope() -> None:
    with pytest.raises(ContractError) as exc:
        Task.from_dict({"id": "T-1", "title": "x", "scope": []})
    assert exc.value.detail == {"field": "scope"}


def test_task_id_validation() -> None:
    with pytest.raises(ContractError):
        Task.from_dict({"id": "bad id", "title": "x", "scope": ["a"]})


def test_dependency_cycle_rejected() -> None:
    tasks = {
        "T-1": Task.from_dict({"id": "T-1", "title": "a", "scope": ["a"], "depends_on": ["T-2"]}),
        "T-2": Task.from_dict({"id": "T-2", "title": "b", "scope": ["b"], "depends_on": ["T-1"]}),
    }
    with pytest.raises(ContractError) as exc:
        check_dependencies(tasks)
    assert "cycle" in exc.value.message


def test_budget_defaults_apply() -> None:
    task = Task.from_dict({"id": "T-1", "title": "x", "scope": ["a"]}, default_budget=Budget(3, 40))
    assert task.budget.to_dict() == {"max_files": 3, "max_lines": 40}


def test_prompt_is_deterministic_and_scope_aware() -> None:
    task = Task.from_dict({"id": "T-1", "title": "x", "scope": ["src/**"], "context": "be careful"})
    first = build_prompt(task, "proj", "coder")
    second = build_prompt(task, "proj", "coder")
    assert prompt_hash(first) == prompt_hash(second)
    assert "src/**" in first and "be careful" in first
    other = build_prompt(task, "proj", "planner")
    assert prompt_hash(first) != prompt_hash(other)


def test_task_status_derivation() -> None:
    task = Task.from_dict({"id": "T-1", "title": "x", "scope": ["a"]})
    assert task_status(task, [], True)[0] == "todo"
    assert task_status(task, [], False)[0] == "blocked"

    running = Run(
        run_id="R-1",
        task_id="T-1",
        title="x",
        agent="coder",
        adapter="mock",
        base_commit="b",
        branch="br",
        worktree="wt",
        prompt_sha256="p",
        status="running",
    )
    assert task_status(task, [running], True)[0] == "running"

    passed = Run(
        run_id="R-2",
        task_id="T-1",
        title="x",
        agent="coder",
        adapter="mock",
        base_commit="b",
        branch="br",
        worktree="wt",
        prompt_sha256="p",
        status="passed",
    )
    assert task_status(task, [passed], True)[0] == "review"

    merged = Run(
        run_id="R-3",
        task_id="T-1",
        title="x",
        agent="coder",
        adapter="mock",
        base_commit="b",
        branch="br",
        worktree="wt",
        prompt_sha256="p",
        status="merged",
    )
    assert task_status(task, [passed, merged], True)[0] == "done"
