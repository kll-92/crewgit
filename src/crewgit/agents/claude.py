"""Claude Code CLI adapter (flags may evolve; generic adapter is the fallback)."""

from __future__ import annotations

import json
import shutil
import subprocess

from ..models import AgentError
from .base import Adapter, AgentResult, RunContext


class ClaudeAdapter(Adapter):
    name = "claude"

    def describe(self, ctx: RunContext) -> str:
        binary = shutil.which("claude") or "claude"
        return f"{binary} -p <prompt> --output-format json --permission-mode acceptEdits"

    def run(self, ctx: RunContext) -> AgentResult:
        binary = shutil.which("claude")
        if not binary:
            raise AgentError("claude CLI not found on PATH; install it or use the generic adapter")
        permission = str(self.config.extra.get("permission_mode", "acceptEdits"))
        command = [
            binary,
            "-p",
            ctx.prompt,
            "--output-format",
            "json",
            "--permission-mode",
            permission,
        ]
        try:
            proc = subprocess.run(
                command,
                cwd=str(ctx.worktree),
                env=ctx.env,
                capture_output=True,
                text=True,
                timeout=ctx.timeout_s,
            )
        except subprocess.TimeoutExpired:
            return AgentResult(
                exit_code=124,
                stderr=f"claude timed out after {ctx.timeout_s}s",
                model=self.model_label,
            )

        stdout = proc.stdout or ""
        result_text = stdout
        usage = None
        model = self.model_label
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            result_text = str(data.get("result") or data.get("text") or stdout)
            raw_usage = data.get("usage") or {}
            usage = {
                "input_tokens": raw_usage.get("input_tokens"),
                "output_tokens": raw_usage.get("output_tokens"),
                "cost_usd": data.get("total_cost_usd"),
                "note": "reported by claude CLI",
            }
            model = data.get("model") or model
        return AgentResult(
            exit_code=proc.returncode,
            stdout=result_text,
            stderr=proc.stderr,
            usage=usage,
            model=model,
            command="claude -p <prompt> --output-format json",
        )
