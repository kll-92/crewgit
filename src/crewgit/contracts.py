"""Task loading, deterministic prompt construction, and review prompts."""

from __future__ import annotations

import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .config import Config, Paths
from .models import ContractError, Task, load_tasks, sha256_text

HARD_RULES = """\
# Hard rules
- You are in an isolated git worktree. CrewGit stages and commits for you: do NOT run `git commit`,
  `git push`, `git checkout`, `git reset`, or any command that rewrites history.
- Change only files inside the scope above. Anything else fails the scope gate and the run is blocked.
- Never edit `.crewgit/`, `tasks/`, or the default branch.
- Keep the diff minimal. Prefer the smallest change that satisfies the definition of done.
- If the task is impossible within scope, stop and explain in stdout instead of widening the scope.
"""


def load_workspace_tasks(root: Path, config: Config) -> dict[str, Task]:
    return load_tasks(Paths(root).tasks_dir, default_budget=config.gates.budget)


def get_task(root: Path, config: Config, task_id: str) -> Task:
    tasks = load_workspace_tasks(root, config)
    if task_id not in tasks:
        known = ", ".join(sorted(tasks)) or "none"
        raise ContractError(f"unknown task '{task_id}' (known: {known})", detail={"field": "task"})
    return tasks[task_id]


def new_run_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return f"R-{stamp}-{secrets.token_hex(2)}"


def branch_name(task_id: str, run_id: str) -> str:
    return f"crewgit/{task_id}/{run_id}"


def worktree_name(task_id: str, run_id: str) -> str:
    return f"{task_id}-{run_id}"


def build_prompt(task: Task, project: str, agent_name: str) -> str:
    scope_lines = "\n".join(f"- {pattern}" for pattern in task.scope)
    forbid = list(task.forbid)
    forbid_text = "\n".join(f"- {pattern}" for pattern in forbid) if forbid else "- (none beyond the always-forbidden paths)"
    budget = task.budget
    if task.acceptance.tests_specified and task.acceptance.tests:
        tests = task.acceptance.tests
    elif task.acceptance.tests_specified:
        tests = None
    else:
        tests = "project default (see .crewgit/config.yaml)"
    tests_text = f"`{tests}`" if tests else "no test command declared"
    context = task.context.strip() or "(none)"

    return f"""You are "{agent_name}", a contributor on the CrewGit team for project "{project}".

# Task
{task.id} — {task.title}

# Scope — you may ONLY change these paths
{scope_lines}

Never change these paths:
{forbid_text}

# Definition of done
- Required command must pass: {tests_text}
- Budget: at most {budget.max_files} files and {budget.max_lines} changed lines.
- The final diff must directly serve the task title above.

# Context
{context}

{HARD_RULES}
"""


def prompt_hash(prompt: str) -> str:
    return sha256_text(prompt.strip())


def review_prompt(task: Task, diff_text: str, evidence: str) -> str:
    return f"""You are the reviewer agent. Review a diff for task {task.id} — {task.title}.

# Task scope (the diff must stay inside it)
{chr(10).join(f"- {pattern}" for pattern in task.scope)}

# Evidence collected by CrewGit
{evidence}
CREWGIT_EVIDENCE {evidence.replace(chr(10), " | ")}

# Diff under review
```diff
{diff_text}
```

Respond with exactly one JSON object and no surrounding prose:
{{"verdict": "approve" | "revise", "notes": ["short reason", "..."]}}
Approve only when the diff is inside scope and the evidence supports the task. Otherwise return revise.
"""


def extract_verdict(text: str) -> dict[str, Any] | None:
    """Find the last parseable JSON object in reviewer output."""
    import json

    text = text or ""
    decoder = json.JSONDecoder()
    start = 0
    best: dict[str, Any] | None = None
    while True:
        index = text.find("{", start)
        if index < 0:
            break
        try:
            value, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            start = index + 1
            continue
        if isinstance(value, dict) and "verdict" in value:
            best = value
        start = index + 1
    return best


def task_summary(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "agent": task.agent,
        "depends_on": list(task.depends_on),
        "scope": list(task.scope),
        "forbid": list(task.forbid),
        "budget": task.budget.to_dict(),
        "context": task.context,
        "contract_hash": task.contract_hash,
    }


def dump_task_yaml(task: Task) -> str:
    return yaml.safe_dump(task.to_dict(), sort_keys=False, allow_unicode=True)


def write_task_file(path: Path, data: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path
