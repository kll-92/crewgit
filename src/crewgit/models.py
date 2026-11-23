"""Core data models for CrewGit: tasks, gates, runs, and small shared helpers."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$")
RUN_ID_RE = re.compile(r"^R-[0-9]{8}-[0-9]{4}-[0-9a-f]{4}$")

GATE_STATUSES = ("pass", "fail", "skip", "error")
RUN_STATUSES = ("running", "passed", "failed", "needs_human", "merged", "rejected", "forced")
TASK_STATUSES = ("todo", "blocked", "running", "review", "done")

ALWAYS_FORBIDDEN = (".crewgit/", "tasks/")

# --------------------------------------------------------------------------- errors


class CrewGitError(RuntimeError):
    """Base class for every typed error CrewGit raises."""

    code = "crewgit_error"

    def __init__(self, message: str, *, detail: Any = None):
        super().__init__(message)
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.detail is not None:
            out["detail"] = self.detail
        return out


class ContractError(CrewGitError):
    code = "contract_error"


class GitError(CrewGitError):
    code = "git_error"


class GateError(CrewGitError):
    code = "gate_error"


class StoreError(CrewGitError):
    code = "store_error"


class AgentError(CrewGitError):
    code = "agent_error"


# --------------------------------------------------------------------------- helpers


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _segment_regex(segment: str) -> str:
    out = []
    for ch in segment:
        if ch == "*":
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(ch))
    return "".join(out)


def glob_to_regex(pattern: str) -> str:
    """Translate a path glob to a regex where `*` never crosses `/` and `**` does."""
    pattern = pattern.strip().replace("\\", "/")
    if pattern.endswith("/"):
        pattern += "**"
    segments = [seg for seg in pattern.split("/") if seg]
    if not segments:
        return r".*"
    parts: list[str] = []
    for index, segment in enumerate(segments):
        last = index == len(segments) - 1
        if segment == "**":
            parts.append(r".*" if last else r"(?:[^/]+/)*")
        else:
            parts.append(_segment_regex(segment) + ("" if last else "/"))
    return "".join(parts)


def glob_match(path: str, pattern: str) -> bool:
    return re.fullmatch(glob_to_regex(pattern), path.strip().replace("\\", "/")) is not None


def scope_violations(paths: Iterable[str], scope: Iterable[str], forbid: Iterable[str] = ()) -> list[str]:
    """Return paths that fall outside the declared scope (or inside forbid)."""
    scope_list = list(scope)
    forbid_list = list(forbid)
    bad: list[str] = []
    for raw in paths:
        path = raw.replace("\\", "/")
        if path.startswith(ALWAYS_FORBIDDEN):
            bad.append(path)
            continue
        if any(glob_match(path, pattern) for pattern in forbid_list):
            bad.append(path)
            continue
        if not any(glob_match(path, pattern) for pattern in scope_list):
            bad.append(path)
    return bad


def find_cycles(depends: dict[str, list[str]]) -> list[list[str]]:
    """Return dependency cycles as paths, if any."""
    colors: dict[str, int] = {node: 0 for node in depends}
    stack: list[str] = []
    cycles: list[list[str]] = []

    def visit(node: str) -> None:
        colors[node] = 1
        stack.append(node)
        for child in depends.get(node, []):
            if child not in colors:
                continue
            if colors[child] == 1:
                index = stack.index(child)
                cycles.append(stack[index:] + [child])
            elif colors[child] == 0:
                visit(child)
        stack.pop()
        colors[node] = 2

    for node in depends:
        if colors[node] == 0:
            visit(node)
    return cycles


# --------------------------------------------------------------------------- contracts


@dataclass
class Budget:
    max_files: int = 6
    max_lines: int = 300

    def __post_init__(self) -> None:
        for name in ("max_files", "max_lines"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ContractError(f"budget.{name} must be a positive integer", detail={"field": f"budget.{name}"})

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None, defaults: "Budget | None" = None) -> "Budget":
        base = defaults or cls()
        if not data:
            return Budget(base.max_files, base.max_lines)
        if not isinstance(data, dict):
            raise ContractError("budget must be a mapping", detail={"field": "budget"})
        return Budget(
            max_files=data.get("max_files", base.max_files),
            max_lines=data.get("max_lines", base.max_lines),
        )

    def to_dict(self) -> dict[str, int]:
        return {"max_files": self.max_files, "max_lines": self.max_lines}


@dataclass
class Acceptance:
    tests: str | None = None
    lint: str | None = None
    review: bool = True
    tests_specified: bool = False
    lint_specified: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Acceptance":
        if data is None:
            return Acceptance()
        if not isinstance(data, dict):
            raise ContractError("acceptance must be a mapping", detail={"field": "acceptance"})
        for key in ("tests", "lint"):
            value = data.get(key)
            if value is not None and not isinstance(value, str):
                raise ContractError(f"acceptance.{key} must be a string or null", detail={"field": f"acceptance.{key}"})
        review = data.get("review", True)
        if not isinstance(review, bool):
            raise ContractError("acceptance.review must be a boolean", detail={"field": "acceptance.review"})
        return cls(
            tests=data.get("tests"),
            lint=data.get("lint"),
            review=review,
            tests_specified="tests" in data,
            lint_specified="lint" in data,
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"review": self.review}
        if self.tests_specified:
            out["tests"] = self.tests
        if self.lint_specified:
            out["lint"] = self.lint
        return out


@dataclass
class Task:
    id: str
    title: str
    scope: list[str]
    depends_on: list[str] = field(default_factory=list)
    forbid: list[str] = field(default_factory=list)
    agent: str | None = None
    acceptance: Acceptance = field(default_factory=Acceptance)
    budget: Budget = field(default_factory=Budget)
    context: str = ""
    mock_actions: list[dict[str, Any]] = field(default_factory=list)
    path: Path | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        *,
        path: Path | None = None,
        default_budget: Budget | None = None,
    ) -> "Task":
        if not isinstance(data, dict):
            raise ContractError("task contract must be a mapping", detail={"field": "$"})
        task_id = data.get("id")
        if not isinstance(task_id, str) or not TASK_ID_RE.match(task_id):
            raise ContractError("task.id must match ^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$", detail={"field": "id"})
        title = data.get("title")
        if not isinstance(title, str) or not 1 <= len(title) <= 120:
            raise ContractError("task.title must be 1-120 characters", detail={"field": "title"})

        scope = data.get("scope")
        if not isinstance(scope, list) or not scope or not all(isinstance(item, str) and item.strip() for item in scope):
            raise ContractError("task.scope must be a non-empty list of path globs", detail={"field": "scope"})

        depends_on = data.get("depends_on", []) or []
        if not isinstance(depends_on, list) or not all(isinstance(item, str) for item in depends_on):
            raise ContractError("task.depends_on must be a list of task ids", detail={"field": "depends_on"})

        forbid = data.get("forbid", []) or []
        if not isinstance(forbid, list) or not all(isinstance(item, str) for item in forbid):
            raise ContractError("task.forbid must be a list of path globs", detail={"field": "forbid"})

        agent = data.get("agent")
        if agent is not None and not isinstance(agent, str):
            raise ContractError("task.agent must be a string or null", detail={"field": "agent"})

        context = data.get("context", "")
        if not isinstance(context, str):
            raise ContractError("task.context must be a string", detail={"field": "context"})

        actions = data.get("mock_actions", []) or []
        _validate_mock_actions(actions)

        return cls(
            id=task_id,
            title=title,
            scope=list(scope),
            depends_on=list(depends_on),
            forbid=list(forbid),
            agent=agent,
            acceptance=Acceptance.from_dict(data.get("acceptance")),
            budget=Budget.from_dict(data.get("budget"), default_budget),
            context=context,
            mock_actions=list(actions),
            path=path,
            raw=dict(data),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "title": self.title, "scope": list(self.scope)}
        if self.depends_on:
            out["depends_on"] = list(self.depends_on)
        if self.forbid:
            out["forbid"] = list(self.forbid)
        if self.agent:
            out["agent"] = self.agent
        acceptance = self.acceptance.to_dict()
        if acceptance:
            out["acceptance"] = acceptance
        out["budget"] = self.budget.to_dict()
        if self.context:
            out["context"] = self.context
        if self.mock_actions:
            out["mock_actions"] = list(self.mock_actions)
        return out

    @property
    def contract_hash(self) -> str:
        return sha256_text(canonical_json(self.raw))


def _validate_mock_actions(actions: Any) -> None:
    if not isinstance(actions, list):
        raise ContractError("mock_actions must be a list", detail={"field": "mock_actions"})
    for index, action in enumerate(actions):
        field_name = f"mock_actions[{index}]"
        if not isinstance(action, dict):
            raise ContractError(f"{field_name} must be a mapping", detail={"field": field_name})
        op = action.get("op")
        if op not in ("write", "patch", "delete"):
            raise ContractError(f"{field_name}.op must be write|patch|delete", detail={"field": f"{field_name}.op"})
        path = action.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ContractError(f"{field_name}.path is required", detail={"field": f"{field_name}.path"})
        if op == "write" and not isinstance(action.get("content"), str):
            raise ContractError(f"{field_name}.content is required for write", detail={"field": f"{field_name}.content"})
        if op == "patch" and not isinstance(action.get("find"), str):
            raise ContractError(f"{field_name}.find is required for patch", detail={"field": f"{field_name}.find"})


def load_task_file(path: Path, *, default_budget: Budget | None = None) -> Task:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - exercised via CLI
        raise ContractError(f"invalid YAML in {path.name}: {exc}", detail={"file": str(path)}) from exc
    return Task.from_dict(data, path=path, default_budget=default_budget)


def load_tasks(tasks_dir: Path, *, default_budget: Budget | None = None) -> dict[str, Task]:
    tasks: dict[str, Task] = {}
    directory = Path(tasks_dir)
    if not directory.exists():
        return tasks
    for path in sorted(list(directory.glob("*.yaml")) + list(directory.glob("*.yml"))):
        task = load_task_file(path, default_budget=default_budget)
        if task.id in tasks:
            raise ContractError(f"duplicate task id: {task.id}", detail={"field": "id", "file": str(path)})
        tasks[task.id] = task
    check_dependencies(tasks)
    return tasks


def check_dependencies(tasks: dict[str, Task]) -> None:
    depends = {task.id: [dep for dep in task.depends_on if dep] for task in tasks.values()}
    for task_id, deps in depends.items():
        for dep in deps:
            if dep == task_id:
                raise ContractError(f"task {task_id} depends on itself", detail={"field": "depends_on"})
            if dep not in tasks:
                raise ContractError(
                    f"task {task_id} depends on unknown task {dep}",
                    detail={"field": "depends_on", "task": task_id},
                )
    cycles = find_cycles(depends)
    if cycles:
        readable = " -> ".join(cycles[0])
        raise ContractError(f"dependency cycle detected: {readable}", detail={"field": "depends_on"})


# --------------------------------------------------------------------------- runs


VALID_GATE_STATUS = set(GATE_STATUSES)


@dataclass
class GateResult:
    name: str
    status: str
    detail: str = ""
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status, "detail": self.detail, "duration_ms": self.duration_ms}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GateResult":
        return cls(
            name=str(data.get("name", "gate")),
            status=str(data.get("status", "error")),
            detail=str(data.get("detail", "")),
            duration_ms=int(data.get("duration_ms", 0)),
        )


@dataclass
class Run:
    run_id: str
    task_id: str
    title: str
    agent: str
    adapter: str
    base_commit: str
    branch: str
    worktree: str
    prompt_sha256: str
    prompt: str = ""
    contract_hash: str = ""
    model: str | None = None
    started_at: str = field(default_factory=iso_now)
    finished_at: str | None = None
    duration_ms: int = 0
    exit_code: int | None = None
    usage: dict[str, Any] | None = None
    commit: str | None = None
    changed_files: list[str] = field(default_factory=list)
    diff_stat: dict[str, int] = field(default_factory=dict)
    diff_sha256: str | None = None
    gates: list[GateResult] = field(default_factory=list)
    status: str = "running"
    error: str | None = None
    override: str | None = None
    replay_of: str | None = None
    reproduced: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": 1,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "title": self.title,
            "agent": self.agent,
            "adapter": self.adapter,
            "model": self.model,
            "base_commit": self.base_commit,
            "branch": self.branch,
            "worktree": self.worktree,
            "prompt_sha256": self.prompt_sha256,
            "prompt": self.prompt,
            "contract_hash": self.contract_hash,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "exit_code": self.exit_code,
            "usage": self.usage,
            "commit": self.commit,
            "changed_files": list(self.changed_files),
            "diff_stat": dict(self.diff_stat),
            "diff_sha256": self.diff_sha256,
            "gates": [gate.to_dict() for gate in self.gates],
            "status": self.status,
            "error": self.error,
            "override": self.override,
            "replay_of": self.replay_of,
            "reproduced": self.reproduced,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Run":
        return cls(
            run_id=data["run_id"],
            task_id=data.get("task_id", ""),
            title=data.get("title", ""),
            agent=data.get("agent", ""),
            adapter=data.get("adapter", ""),
            base_commit=data.get("base_commit", ""),
            branch=data.get("branch", ""),
            worktree=data.get("worktree", ""),
            prompt_sha256=data.get("prompt_sha256", ""),
            prompt=data.get("prompt", ""),
            contract_hash=data.get("contract_hash", ""),
            model=data.get("model"),
            started_at=data.get("started_at", iso_now()),
            finished_at=data.get("finished_at"),
            duration_ms=int(data.get("duration_ms", 0)),
            exit_code=data.get("exit_code"),
            usage=data.get("usage"),
            commit=data.get("commit"),
            changed_files=list(data.get("changed_files", [])),
            diff_stat=dict(data.get("diff_stat", {})),
            diff_sha256=data.get("diff_sha256"),
            gates=[GateResult.from_dict(item) for item in data.get("gates", [])],
            status=data.get("status", "running"),
            error=data.get("error"),
            override=data.get("override"),
            replay_of=data.get("replay_of"),
            reproduced=data.get("reproduced"),
        )

    def gate(self, name: str) -> GateResult | None:
        for result in self.gates:
            if result.name == name:
                return result
        return None

    @property
    def total_cost(self) -> float | None:
        if not self.usage:
            return None
        cost = self.usage.get("cost_usd")
        return float(cost) if isinstance(cost, (int, float)) else None


def task_status(task: Task, runs: list[Run], deps_ok: bool) -> tuple[str, str]:
    """Derive the board column for a task from its runs."""
    ordered = sorted(runs, key=lambda run: run.started_at)
    if any(run.status in ("merged", "forced") for run in ordered):
        return "done", "merged"
    if any(run.status == "running" for run in ordered):
        return "running", "run in progress"
    latest = ordered[-1] if ordered else None
    if latest is None:
        return ("todo", "") if deps_ok else ("blocked", "waiting on dependencies")
    if latest.status == "passed":
        return "review", "ready for merge"
    if latest.status == "needs_human":
        return "review", "needs human review"
    if latest.status == "rejected":
        return "blocked", latest.error or "rejected"
    if latest.status == "failed":
        return "blocked", latest.error or "gate failed"
    return ("todo", "") if deps_ok else ("blocked", "waiting on dependencies")
