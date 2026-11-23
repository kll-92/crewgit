"""Adapter protocol: anything that can edit a worktree can be a CrewGit agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import AgentConfig
from ..models import Task


@dataclass
class RunContext:
    task: Task
    agent_name: str
    agent: AgentConfig
    run_id: str
    worktree: Path
    prompt: str
    prompt_path: Path
    base_commit: str
    timeout_s: int
    env: dict[str, str]
    repo_root: Path
    dry_run: bool = False


@dataclass
class AgentResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    usage: dict[str, Any] | None = None
    model: str | None = None
    notes: str | None = None
    command: str | None = None


class Adapter:
    name = "adapter"

    def __init__(self, config: AgentConfig):
        self.config = config

    @property
    def model_label(self) -> str | None:
        return self.config.model

    def run(self, ctx: RunContext) -> AgentResult:  # pragma: no cover - abstract
        raise NotImplementedError

    def describe(self, ctx: RunContext) -> str:
        raise NotImplementedError
