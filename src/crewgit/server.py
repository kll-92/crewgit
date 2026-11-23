"""FastAPI board: JSON API plus a static single-page UI. No build step."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .config import load_config
from .models import ContractError, CrewGitError
from .runner import Runner

WEB_DIR = Path(__file__).parent / "web"


class RunRequest(BaseModel):
    agent: str | None = None


class MergeRequest(BaseModel):
    force: bool = False
    reason: str | None = None


class RejectRequest(BaseModel):
    reason: str


def _run_payload(runner: Runner, run) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "task_id": run.task_id,
        "agent": run.agent,
        "adapter": run.adapter,
        "status": run.status,
        "branch": run.branch,
        "commit": run.commit,
        "commit_short": runner.git.short(run.commit) if run.commit else None,
        "gates": [gate.to_dict() for gate in run.gates],
        "diff_stat": run.diff_stat,
        "changed_files": run.changed_files,
        "cost_usd": run.total_cost,
        "duration_ms": run.duration_ms,
        "error": run.error,
        "replay_of": run.replay_of,
        "reproduced": run.reproduced,
    }


def create_app(root: Path, *, read_only: bool = False) -> FastAPI:
    workspace = Path(root).resolve()
    app = FastAPI(
        title="CrewGit board",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    def runner() -> Runner:
        return Runner(workspace)

    @app.exception_handler(CrewGitError)
    async def crewgit_error(_request: Request, exc: CrewGitError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"ok": False, "error": exc.to_dict()})

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        config = load_config(workspace)
        return {
            "ok": True,
            "version": __version__,
            "project": config.project,
            "branch": config.default_branch,
            "read_only": read_only,
        }

    @app.get("/api/board")
    def board() -> dict[str, Any]:
        return runner().board()

    @app.get("/api/agents")
    def agents() -> dict[str, Any]:
        config = load_config(workspace)
        return {
            name: {"adapter": cfg.adapter, "role": cfg.role, "model": cfg.model}
            for name, cfg in config.agents.items()
        }

    @app.get("/api/tasks/{task_id}")
    def task(task_id: str) -> dict[str, Any]:
        data = runner().board()
        for item in data["tasks"]:
            if item["id"] == task_id:
                return item
        raise HTTPException(status_code=404, detail=f"unknown task {task_id}")

    def load_run(run_id: str):
        try:
            return runner().load_run(run_id)
        except ContractError as exc:
            if exc.message.startswith("unknown run"):
                raise HTTPException(status_code=404, detail=exc.message) from exc
            raise

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str) -> dict[str, Any]:
        r = runner()
        item = load_run(run_id)
        payload = _run_payload(r, item)
        payload["prompt"] = item.prompt
        payload["usage"] = item.usage
        payload["contract_hash"] = item.contract_hash
        return payload

    @app.get("/api/runs/{run_id}/diff")
    def run_diff(run_id: str) -> PlainTextResponse:
        r = runner()
        item = load_run(run_id)
        if not item.commit:
            raise HTTPException(status_code=404, detail="this run has no commit")
        return PlainTextResponse(r.git.diff_text(item.base_commit, item.commit))

    def _guard_read_only() -> None:
        if read_only:
            raise HTTPException(status_code=403, detail="board is read-only")

    @app.post("/api/tasks/{task_id}/run")
    def start_run(task_id: str, payload: RunRequest | None = Body(default=None)) -> dict[str, Any]:
        _guard_read_only()
        r = runner()
        item = r.run_task(task_id, payload.agent if payload else None)
        return {"ok": True, "run": _run_payload(r, item)}

    @app.post("/api/runs/{run_id}/merge")
    def merge_run(run_id: str, payload: MergeRequest | None = Body(default=None)) -> dict[str, Any]:
        _guard_read_only()
        r = runner()
        result = r.merge(run_id, force=bool(payload and payload.force), reason=payload.reason if payload else None)
        return {
            "ok": True,
            "commit": result["commit"],
            "run": _run_payload(r, result["run"]),
        }

    @app.post("/api/runs/{run_id}/reject")
    def reject_run(run_id: str, payload: RejectRequest) -> dict[str, Any]:
        _guard_read_only()
        r = runner()
        item = r.reject(run_id, payload.reason)
        return {"ok": True, "run": _run_payload(r, item)}

    if WEB_DIR.exists():
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")

    return app
