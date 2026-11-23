"""Workspace configuration, path layout, and environment hygiene."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .models import Budget, ContractError

CONFIG_FILENAME = "config.yaml"
DEFAULT_BRANCH = "main"
SENSITIVE_MARKERS = ("TOKEN", "KEY", "SECRET", "PASSWORD", "CREDENTIAL")
ENV_KEEP_EXACT = {"PATH", "HOME", "LANG", "TERM", "TZ", "TMPDIR", "USER", "SHELL"}
ENV_KEEP_PREFIX = ("LC_", "CREWGIT_")

DEFAULT_CONFIG_TEMPLATE = """version: 1
project: {project}
default_branch: {branch}

gates:
  fail_fast: true
  timeout_s: 600
  budget:
    max_files: 6
    max_lines: 300
  lint:
    command: null
  tests:
    command: "python -m pytest -q"
  review:
    mode: agent
    agent: reviewer

agents:
  planner:
    adapter: mock
    role: planner
  coder:
    adapter: mock
    role: coder
  reviewer:
    adapter: mock
    role: reviewer

environment:
  passthrough: []
"""


@dataclass
class AgentConfig:
    name: str
    adapter: str
    role: str = ""
    command: str | None = None
    model: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> AgentConfig:
        if not isinstance(data, dict):
            raise ContractError(f"agent {name} must be a mapping", detail={"field": f"agents.{name}"})
        adapter = data.get("adapter")
        if not isinstance(adapter, str) or not adapter:
            raise ContractError(f"agent {name} requires an adapter", detail={"field": f"agents.{name}.adapter"})
        role = data.get("role", "") or ""
        if not isinstance(role, str):
            raise ContractError(f"agent {name} role must be a string", detail={"field": f"agents.{name}.role"})
        command = data.get("command")
        if command is not None and not isinstance(command, str):
            raise ContractError(f"agent {name} command must be a string", detail={"field": f"agents.{name}.command"})
        model = data.get("model")
        if model is not None and not isinstance(model, str):
            raise ContractError(f"agent {name} model must be a string", detail={"field": f"agents.{name}.model"})
        extra = {key: value for key, value in data.items() if key not in {"adapter", "role", "command", "model"}}
        return cls(name=name, adapter=adapter, role=role, command=command, model=model, extra=extra)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"adapter": self.adapter}
        if self.role:
            out["role"] = self.role
        if self.command:
            out["command"] = self.command
        if self.model:
            out["model"] = self.model
        out.update(self.extra)
        return out


@dataclass
class GateConfig:
    fail_fast: bool = True
    timeout_s: int = 600
    budget: Budget = field(default_factory=Budget)
    lint_cmd: str | None = None
    tests_cmd: str | None = None
    review_mode: str = "agent"
    review_agent: str | None = "reviewer"

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> GateConfig:
        data = data or {}
        if not isinstance(data, dict):
            raise ContractError("gates must be a mapping", detail={"field": "gates"})
        fail_fast = data.get("fail_fast", True)
        if not isinstance(fail_fast, bool):
            raise ContractError("gates.fail_fast must be a boolean", detail={"field": "gates.fail_fast"})
        timeout_s = data.get("timeout_s", 600)
        if not isinstance(timeout_s, int) or timeout_s <= 0:
            raise ContractError("gates.timeout_s must be a positive integer", detail={"field": "gates.timeout_s"})

        lint = data.get("lint") or {}
        tests = data.get("tests") or {}
        review = data.get("review") or {}
        lint_cmd = (lint or {}).get("command") if isinstance(lint, dict) else None
        tests_cmd = (tests or {}).get("command") if isinstance(tests, dict) else None
        for name, value in (("lint", lint_cmd), ("tests", tests_cmd)):
            if value is not None and not isinstance(value, str):
                raise ContractError(f"gates.{name}.command must be a string or null", detail={"field": f"gates.{name}.command"})

        mode = (review or {}).get("mode", "agent") if isinstance(review, dict) else "agent"
        if mode not in ("off", "agent"):
            raise ContractError("gates.review.mode must be off|agent", detail={"field": "gates.review.mode"})
        review_agent = (review or {}).get("agent", "reviewer") if isinstance(review, dict) else "reviewer"

        return cls(
            fail_fast=fail_fast,
            timeout_s=timeout_s,
            budget=Budget.from_dict(data.get("budget")),
            lint_cmd=lint_cmd,
            tests_cmd=tests_cmd,
            review_mode=mode,
            review_agent=review_agent,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "fail_fast": self.fail_fast,
            "timeout_s": self.timeout_s,
            "budget": self.budget.to_dict(),
            "lint": {"command": self.lint_cmd},
            "tests": {"command": self.tests_cmd},
            "review": {"mode": self.review_mode, "agent": self.review_agent},
        }


@dataclass
class Config:
    version: int
    project: str
    default_branch: str
    gates: GateConfig
    agents: dict[str, AgentConfig]
    passthrough: list[str]
    raw: dict[str, Any] = field(default_factory=dict)

    def agent(self, name: str) -> AgentConfig:
        if name not in self.agents:
            known = ", ".join(sorted(self.agents)) or "none"
            raise ContractError(f"unknown agent '{name}' (known: {known})", detail={"field": "agents"})
        return self.agents[name]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "project": self.project,
            "default_branch": self.default_branch,
            "gates": self.gates.to_dict(),
            "agents": {name: cfg.to_dict() for name, cfg in self.agents.items()},
            "environment": {"passthrough": list(self.passthrough)},
        }


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def crewgit_dir(self) -> Path:
        return self.root / ".crewgit"

    @property
    def config_file(self) -> Path:
        return self.crewgit_dir / CONFIG_FILENAME

    @property
    def tasks_dir(self) -> Path:
        return self.root / "tasks"

    @property
    def worktrees_dir(self) -> Path:
        return self.crewgit_dir / "worktrees"

    @property
    def runs_dir(self) -> Path:
        return self.crewgit_dir / "runs"

    @property
    def board_db(self) -> Path:
        return self.crewgit_dir / "board.db"

    @property
    def notes_lock(self) -> Path:
        return self.crewgit_dir / "notes.lock"

    def ensure(self) -> None:
        self.crewgit_dir.mkdir(parents=True, exist_ok=True)
        self.worktrees_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)


def find_root(start: Path | None = None) -> Path:
    """Walk upward until a CrewGit workspace is found."""
    current = Path(start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".crewgit" / CONFIG_FILENAME).exists():
            return candidate
    raise ContractError(
        "not a CrewGit workspace: run `crewgit init` first, or change into a project that has .crewgit/config.yaml"
    )


def load_config(root: Path) -> Config:
    path = Path(root) / ".crewgit" / CONFIG_FILENAME
    if not path.exists():
        raise ContractError(f"missing config: {path}", detail={"file": str(path)})
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ContractError(f"invalid YAML in config: {exc}", detail={"file": str(path)}) from exc
    if not isinstance(raw, dict):
        raise ContractError("config must be a mapping", detail={"file": str(path)})

    version = raw.get("version", 1)
    if version != 1:
        raise ContractError(f"unsupported config version {version}; expected 1", detail={"field": "version"})
    project = raw.get("project") or Path(root).name
    if not isinstance(project, str):
        raise ContractError("project must be a string", detail={"field": "project"})
    branch = raw.get("default_branch", DEFAULT_BRANCH)
    if not isinstance(branch, str) or not branch:
        raise ContractError("default_branch must be a non-empty string", detail={"field": "default_branch"})

    agents_raw = raw.get("agents") or {}
    if not isinstance(agents_raw, dict) or not agents_raw:
        raise ContractError("config.agents must define at least one agent", detail={"field": "agents"})
    agents = {name: AgentConfig.from_dict(name, data) for name, data in agents_raw.items()}

    environment = raw.get("environment") or {}
    passthrough = (environment or {}).get("passthrough", []) if isinstance(environment, dict) else []
    if not isinstance(passthrough, list) or not all(isinstance(item, str) for item in passthrough):
        raise ContractError("environment.passthrough must be a list of strings", detail={"field": "environment.passthrough"})

    gates = GateConfig.from_dict(raw.get("gates"))
    if gates.review_mode == "agent" and gates.review_agent and gates.review_agent not in agents:
        raise ContractError(
            f"review agent '{gates.review_agent}' is not defined in agents",
            detail={"field": "gates.review.agent"},
        )

    return Config(
        version=1,
        project=project,
        default_branch=branch,
        gates=gates,
        agents=agents,
        passthrough=list(passthrough),
        raw=dict(raw),
    )


def write_default_config(root: Path, project: str, branch: str = DEFAULT_BRANCH) -> Path:
    paths = Paths(Path(root))
    paths.ensure()
    content = DEFAULT_CONFIG_TEMPLATE.format(project=project, branch=branch)
    paths.config_file.write_text(content, encoding="utf-8")
    return paths.config_file


def scrubbed_env(passthrough: list[str] | None = None, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Environment allowlist for agents: no API keys by accident."""
    allowed = set(passthrough or [])
    env = {
        key: value
        for key, value in os.environ.items()
        if key in ENV_KEEP_EXACT or key.startswith(ENV_KEEP_PREFIX) or key in allowed
    }
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin")
    env.setdefault("LANG", "en_US.UTF-8")
    if extra:
        env.update(extra)
    return env


def redact(text: str) -> str:
    """Replace the values of sensitive env vars if they leak into text."""
    if not text:
        return text
    for key, value in os.environ.items():
        if not value or len(value) < 6:
            continue
        if any(marker in key.upper() for marker in SENSITIVE_MARKERS):
            text = text.replace(value, "***redacted***")
    return text
