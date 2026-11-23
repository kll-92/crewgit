"""Deterministic mock agents: prove the plumbing offline, no model, no keys."""

from __future__ import annotations

import json
from pathlib import Path

from ..models import AgentError, Task
from .base import Adapter, AgentResult, RunContext

UNMETERED = {
    "input_tokens": None,
    "output_tokens": None,
    "cost_usd": None,
    "note": "mock adapter is unmetered",
}


def _safe_path(worktree: Path, relative: str) -> Path:
    target = (worktree / relative).resolve()
    root = worktree.resolve()
    if root not in target.parents and target != root:
        raise AgentError(f"mock action escapes the worktree: {relative}")
    return target


def _evidence(prompt: str) -> dict[str, str]:
    evidence: dict[str, str] = {}
    for line in prompt.splitlines():
        if line.startswith("CREWGIT_EVIDENCE "):
            for token in line.removeprefix("CREWGIT_EVIDENCE ").split("|"):
                token = token.strip()
                if "=" in token:
                    key, _, value = token.partition("=")
                    evidence[key.strip()] = value.strip()
    return evidence


class MockAdapter(Adapter):
    name = "mock"

    @property
    def model_label(self) -> str:
        return "mock/deterministic"

    def describe(self, ctx: RunContext) -> str:
        return f"mock:{ctx.agent.role or 'coder'} (in-process, no command)"

    def run(self, ctx: RunContext) -> AgentResult:
        role = (ctx.agent.role or "coder").lower()
        if role == "reviewer":
            return self._review(ctx)
        if role == "planner":
            return self._plan(ctx)
        return self._code(ctx)

    # ------------------------------------------------------------------ roles

    def _code(self, ctx: RunContext) -> AgentResult:
        actions = ctx.task.mock_actions
        if not actions:
            return AgentResult(
                exit_code=1,
                stderr="mock coder has no mock_actions in the task contract",
                model=self.model_label,
                usage=UNMETERED,
            )
        applied: list[str] = []
        for action in actions:
            op = action["op"]
            path = _safe_path(ctx.worktree, action["path"])
            if op == "write":
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(action["content"], encoding="utf-8")
                applied.append(f"write {action['path']}")
            elif op == "patch":
                if not path.exists():
                    return AgentResult(
                        exit_code=2,
                        stderr=f"patch target missing: {action['path']}",
                        model=self.model_label,
                        usage=UNMETERED,
                    )
                text = path.read_text(encoding="utf-8")
                find = action["find"]
                if find not in text:
                    return AgentResult(
                        exit_code=2,
                        stderr=f"patch anchor not found in {action['path']}: {find!r}",
                        model=self.model_label,
                        usage=UNMETERED,
                    )
                replacement = action.get("replace", "")
                path.write_text(text.replace(find, replacement, 1), encoding="utf-8")
                applied.append(f"patch {action['path']}")
            else:
                if path.exists():
                    path.unlink()
                applied.append(f"delete {action['path']}")
        stdout = "mock coder applied:\n" + "\n".join(f"- {item}" for item in applied)
        return AgentResult(exit_code=0, stdout=stdout, model=self.model_label, usage=UNMETERED)

    def _plan(self, ctx: RunContext) -> AgentResult:
        task: Task = ctx.task
        scope = "\n".join(f"- `{pattern}`" for pattern in task.scope)
        plan = f"""# Plan — {task.id}: {task.title}

## Goal
{task.title}

## Contract
Allowed paths:
{scope}

Definition of done:
- {task.acceptance.tests or "project default tests"}

## Steps
1. Read the files in scope and confirm the failing behaviour.
2. Make the smallest change that satisfies the task.
3. Run the acceptance command locally before handing off.
4. Leave the worktree clean of unrelated edits.

## Risks
- Touching files outside scope will be blocked by the gate.
- Budget: {task.budget.max_files} files / {task.budget.max_lines} lines.
"""
        target = _safe_path(ctx.worktree, f"docs/plan-{task.id}.md")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(plan, encoding="utf-8")
        return AgentResult(
            exit_code=0,
            stdout=f"mock planner wrote docs/plan-{task.id}.md",
            model=self.model_label,
            usage=UNMETERED,
        )

    def _review(self, ctx: RunContext) -> AgentResult:
        evidence = _evidence(ctx.prompt)
        blocking = [f"{key}={value}" for key, value in evidence.items() if value in ("fail", "error")]
        if blocking:
            verdict = {
                "verdict": "revise",
                "notes": [f"evidence not green: {', '.join(blocking)}"],
            }
        else:
            verdict = {
                "verdict": "approve",
                "notes": ["scope and tests are green; diff is within budget"],
            }
        return AgentResult(
            exit_code=0,
            stdout=json.dumps(verdict),
            model=self.model_label,
            usage=UNMETERED,
        )
