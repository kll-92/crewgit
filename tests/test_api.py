from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from crewgit.server import create_app


def test_health_board_and_static(workspace: Path) -> None:
    client = TestClient(create_app(workspace))
    health = client.get("/api/health").json()
    assert health["project"] == "test-project"
    assert health["read_only"] is False

    board = client.get("/api/board").json()
    assert board["counts"]["todo"] == 1

    index = client.get("/")
    assert index.status_code == 200
    assert "CrewGit" in index.text


def test_run_and_merge_via_api(workspace: Path) -> None:
    client = TestClient(create_app(workspace))
    response = client.post("/api/tasks/T-1/run", json={})
    assert response.status_code == 200
    run = response.json()["run"]
    assert run["status"] == "passed"

    diff = client.get(f"/api/runs/{run['run_id']}/diff")
    assert diff.status_code == 200
    assert "MESSAGE" in diff.text

    merged = client.post(f"/api/runs/{run['run_id']}/merge", json={})
    assert merged.status_code == 200
    assert client.get("/api/board").json()["counts"]["done"] == 1


def test_read_only_blocks_actions(workspace: Path) -> None:
    client = TestClient(create_app(workspace, read_only=True))
    response = client.post("/api/tasks/T-1/run", json={})
    assert response.status_code == 403
    assert client.get("/api/board").status_code == 200


def test_unknown_task_and_run(workspace: Path) -> None:
    client = TestClient(create_app(workspace))
    assert client.get("/api/tasks/T-404").status_code == 404
    assert client.get("/api/runs/R-20260101-0000-0000").status_code == 404
