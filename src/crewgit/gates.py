"""Quality gates: scope, budget, lint, tests, review. Fail-fast by default."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Config
from .contracts import extract_verdict, review_prompt
from .gitops import Git
from .models import GateResult, Task, scope_violations


@dataclass
class DiffInfo:
    base: str
    ref: str
    files: list[str] = field(default_factory=list)
    stat: dict[str, int] = field(default_factory=dict)
    text: str = ""
    sha: str = ""

    @property
    def changed_lines(self) -> int:
        return int(self.stat.get("insertions", 0)) + int(self.stat.get("deletions", 0))


ReviewRunner = Callable[[str], Any]


def _tail(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return "…" + text[-limit:]


def run_command(command: str, cwd: Path, env: dict[str, str], timeout_s: int, tail: int = 4000) -> tuple[int, str]:
    started = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            env=env,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        _ = started
        return 124, f"command timed out after {timeout_s}s"
    output = proc.stdout or ""
    if proc.stderr:
        output = output + ("\n" if output else "") + proc.stderr
    return proc.returncode, _tail(output, tail)


class GateEngine:
    def __init__(
        self,
        *,
        config: Config,
        task: Task,
        worktree: Path,
        env: dict[str, str],
        git: Git,
        review_runner: ReviewRunner | None = None,
    ):
        self.config = config
        self.task = task
        self.worktree = Path(worktree)
        self.env = env
        self.git = git
        self.review_runner = review_runner
        self._previous: list[GateResult] = []

    # ------------------------------------------------------------------ pipeline

    def evaluate(self, diff: DiffInfo) -> tuple[list[GateResult], str]:
        results: list[GateResult] = []
        final_status = "passed"
        checks = (self.gate_scope, self.gate_budget, self.gate_lint, self.gate_tests, self.gate_review)
        for check in checks:
            self._previous = results
            result = check(diff)
            results.append(result)
            if result.status == "error":
                final_status = "needs_human"
                if self.config.gates.fail_fast:
                    break
            elif result.status == "fail":
                final_status = "failed"
                if self.config.gates.fail_fast:
                    break
        return results, final_status

    # ------------------------------------------------------------------ gates

    def gate_scope(self, diff: DiffInfo) -> GateResult:
        started = time.monotonic()
        violations = scope_violations(diff.files, self.task.scope, self.task.forbid)
        if violations:
            detail = "out-of-scope paths: " + ", ".join(violations[:8])
            return GateResult("scope", "fail", detail, int((time.monotonic() - started) * 1000))
        detail = f"{len(diff.files)} file(s) within declared scope"
        return GateResult("scope", "pass", detail, int((time.monotonic() - started) * 1000))

    def gate_budget(self, diff: DiffInfo) -> GateResult:
        started = time.monotonic()
        budget = self.task.budget
        files = int(diff.stat.get("files", len(diff.files)))
        lines = diff.changed_lines
        ms = int((time.monotonic() - started) * 1000)
        if files > budget.max_files:
            return GateResult("budget", "fail", f"{files} files > limit {budget.max_files}", ms)
        if lines > budget.max_lines:
            return GateResult("budget", "fail", f"{lines} changed lines > limit {budget.max_lines}", ms)
        return GateResult("budget", "pass", f"{lines}/{budget.max_lines} lines, {files}/{budget.max_files} files", ms)

    def _command_for(self, name: str) -> tuple[str | None, str]:
        acceptance = self.task.acceptance
        if name == "lint":
            specified = acceptance.lint_specified
            value = acceptance.lint
            default = self.config.gates.lint_cmd
        else:
            specified = acceptance.tests_specified
            value = acceptance.tests
            default = self.config.gates.tests_cmd
        if specified:
            return value, "task contract"
        return default, "config default"

    def _gate_command(self, name: str, tail: int) -> GateResult:
        started = time.monotonic()
        command, source = self._command_for(name)
        if not command:
            return GateResult(name, "skip", "no command configured", int((time.monotonic() - started) * 1000))
        code, output = run_command(command, self.worktree, self.env, self.config.gates.timeout_s, tail=tail)
        ms = int((time.monotonic() - started) * 1000)
        if code == 0:
            summary = _tail(output.splitlines()[-1] if output else "ok", 120)
            return GateResult(name, "pass", f"{source}: {summary}", ms)
        if code == 124:
            return GateResult(name, "error", f"{source}: {output}", ms)
        return GateResult(name, "fail", f"{source}: exit {code}\n{output}", ms)

    def gate_lint(self, diff: DiffInfo) -> GateResult:
        return self._gate_command("lint", tail=2000)

    def gate_tests(self, diff: DiffInfo) -> GateResult:
        return self._gate_command("tests", tail=4000)

    def gate_review(self, diff: DiffInfo) -> GateResult:
        started = time.monotonic()
        if not self.task.acceptance.review:
            return GateResult("review", "skip", "disabled by task contract", 0)
        if self.config.gates.review_mode == "off":
            return GateResult("review", "skip", "disabled by config", 0)
        if self.review_runner is None:
            return GateResult("review", "error", "no reviewer configured", 0)

        evidence_lines = [
            f"{result.name}={result.status}" for result in getattr(self, "_previous", [])
        ]
        evidence = "\n".join(evidence_lines) or "no evidence yet"
        prompt = review_prompt(self.task, diff.text, evidence)
        try:
            agent_result = self.review_runner(prompt)
        except Exception as exc:  # reviewer crash must not auto-approve
            ms = int((time.monotonic() - started) * 1000)
            return GateResult("review", "error", f"reviewer failed: {exc}", ms)
        output = getattr(agent_result, "stdout", "") or ""
        verdict = extract_verdict(output)
        ms = int((time.monotonic() - started) * 1000)

        if self.git.has_changes(self.worktree, include_untracked=False):
            return GateResult("review", "fail", "reviewer_boundary_violation: reviewer modified the worktree", ms)
        if verdict is None:
            return GateResult("review", "error", "review output was not valid JSON; escalating to human", ms)
        decision = str(verdict.get("verdict", "")).lower()
        notes = verdict.get("notes") or []
        notes_text = "; ".join(str(note) for note in notes)[:500]
        if decision == "approve":
            return GateResult("review", "pass", f"approve {notes_text}".strip(), ms)
        if decision == "revise":
            return GateResult("review", "fail", f"revise: {notes_text}", ms)
        return GateResult("review", "error", f"unknown verdict '{decision}'; escalating to human", ms)
