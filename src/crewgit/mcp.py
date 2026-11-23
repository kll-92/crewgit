"""Minimal MCP stdio server: let any agent join the team without a plugin."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .models import CrewGitError
from .runner import Runner

PROTOCOL_VERSION = "2024-11-05"

TOOLS: list[dict[str, Any]] = [
    {
        "name": "crewgit_list_tasks",
        "description": "List task contracts with their derived board status and dependencies.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "crewgit_get_task",
        "description": "Read one task contract (scope, acceptance, budget, context) plus its latest run.",
        "inputSchema": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "crewgit_get_board",
        "description": "Read the whole board: counts, cost totals, and task statuses.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "crewgit_submit_run",
        "description": (
            "Submit a branch you already committed as a run for a task. CrewGit runs the gates "
            "(scope, budget, lint, tests, review) and records provenance; it never merges for you."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "agent": {"type": "string"},
                "branch": {"type": "string"},
                "commit": {"type": "string"},
                "summary": {"type": "string"},
            },
            "required": ["task_id", "agent", "branch", "commit"],
            "additionalProperties": False,
        },
    },
]


def _ok(message: dict[str, Any], result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message.get("id"), "result": result}


def _error(message: dict[str, Any], code: int, text: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": code, "message": text}}


def _compact_run(run) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "status": run.status,
        "agent": run.agent,
        "gates": [{"name": gate.name, "status": gate.status} for gate in run.gates],
        "diff_stat": run.diff_stat,
        "commit": run.commit,
        "error": run.error,
    }


def call_tool(runner: Runner, name: str, arguments: dict[str, Any]) -> Any:
    if name == "crewgit_list_tasks":
        board = runner.board()
        return {
            "project": board["project"],
            "tasks": [
                {
                    "id": item["id"],
                    "title": item["title"],
                    "status": item["status"],
                    "agent": item["agent"],
                    "depends_on": item["depends_on"],
                    "scope": item["scope"],
                    "latest_run": item["latest_run"]["run_id"] if item["latest_run"] else None,
                }
                for item in board["tasks"]
            ],
        }
    if name == "crewgit_get_task":
        task_id = str(arguments.get("task_id", ""))
        task = runner.task(task_id)
        board = runner.board()
        item = next((entry for entry in board["tasks"] if entry["id"] == task_id), None)
        return {
            "contract": task.to_dict(),
            "contract_hash": task.contract_hash,
            "status": item["status"] if item else "todo",
            "latest_run": item["latest_run"] if item else None,
        }
    if name == "crewgit_get_board":
        board = runner.board()
        return {
            "project": board["project"],
            "branch": board["branch"],
            "counts": board["counts"],
            "totals": board["totals"],
            "tasks": [
                {"id": item["id"], "status": item["status"], "title": item["title"]}
                for item in board["tasks"]
            ],
        }
    if name == "crewgit_submit_run":
        run = runner.register_external(
            task_id=str(arguments.get("task_id", "")),
            agent_name=str(arguments.get("agent", "")),
            branch=str(arguments.get("branch", "")),
            commit=str(arguments.get("commit", "")),
            summary=str(arguments.get("summary", "")),
        )
        return {"run": _compact_run(run)}
    raise CrewGitError(f"unknown tool '{name}'")


def dispatch(runner: Runner, message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    if method == "initialize":
        return _ok(
            message,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "crewgit", "version": __version__},
            },
        )
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return _ok(message, {})
    if method == "tools/list":
        return _ok(message, {"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params") or {}
        name = str(params.get("name", ""))
        arguments = params.get("arguments") or {}
        try:
            data = call_tool(runner, name, arguments)
            return _ok(
                message,
                {
                    "content": [
                        {"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2)}
                    ],
                    "isError": False,
                },
            )
        except CrewGitError as exc:
            return _ok(
                message,
                {
                    "content": [
                        {"type": "text", "text": json.dumps(exc.to_dict(), ensure_ascii=False)}
                    ],
                    "isError": True,
                },
            )
        except Exception as exc:  # a tool crash must not kill the server
            return _ok(
                message, {"content": [{"type": "text", "text": f"error: {exc}"}], "isError": True}
            )
    return _error(message, -32601, f"method not found: {method}")


def serve_stdio(root: Path) -> None:
    try:
        runner = Runner(Path(root))
    except CrewGitError as exc:
        print(f"crewgit mcp: {exc.message}", file=sys.stderr)
        raise SystemExit(2) from exc
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            sys.stdout.write(json.dumps(_error({"id": None}, -32700, f"parse error: {exc}")) + "\n")
            sys.stdout.flush()
            continue
        if not isinstance(message, dict) or "id" not in message:
            continue
        response = dispatch(runner, message)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
