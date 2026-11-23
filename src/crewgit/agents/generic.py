"""Bring your own CLI agent through a command template."""

from __future__ import annotations

import shlex
import subprocess

from ..models import AgentError
from .base import Adapter, AgentResult, RunContext


class GenericAdapter(Adapter):
    name = "generic"

    def describe(self, ctx: RunContext) -> str:
        return self._expand(ctx)

    def _expand(self, ctx: RunContext) -> str:
        template = self.config.command
        if not template:
            raise AgentError(
                f"agent '{ctx.agent_name}' uses the generic adapter but has no `command` in .crewgit/config.yaml"
            )
        values = {
            "prompt_file": shlex.quote(str(ctx.prompt_path)),
            "worktree": shlex.quote(str(ctx.worktree)),
            "task_id": shlex.quote(ctx.task.id),
            "run_id": shlex.quote(ctx.run_id),
            "agent": shlex.quote(ctx.agent_name),
            "base_commit": shlex.quote(ctx.base_commit),
            "repo_root": shlex.quote(str(ctx.repo_root)),
        }
        try:
            return template.format(**values)
        except KeyError as exc:
            raise AgentError(
                f"unknown placeholder {{{exc.args[0]}}} in agent command template"
            ) from exc

    def run(self, ctx: RunContext) -> AgentResult:
        command = self._expand(ctx)
        try:
            proc = subprocess.run(
                command,
                cwd=str(ctx.worktree),
                env=ctx.env,
                shell=True,
                capture_output=True,
                text=True,
                timeout=ctx.timeout_s,
            )
        except subprocess.TimeoutExpired:
            return AgentResult(
                exit_code=124,
                stderr=f"agent command timed out after {ctx.timeout_s}s",
                model=self.model_label,
                command=command,
            )
        except OSError as exc:
            raise AgentError(f"cannot start agent command: {exc}") from exc
        return AgentResult(
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            model=self.model_label,
            command=command,
        )
