from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from crewgit.models import Run
from crewgit.store import Store, patterns_overlap


def make_run(run_id: str, task_id: str, status: str = "passed") -> Run:
    return Run(
        run_id=run_id,
        task_id=task_id,
        title="task",
        agent="coder",
        adapter="mock",
        base_commit="base",
        branch=f"crewgit/{task_id}/{run_id}",
        worktree="wt",
        prompt_sha256="sha256:x",
        status=status,
    )


def test_run_roundtrip(tmp_path: Path) -> None:
    store = Store(tmp_path / "board.db")
    run = make_run("R-1", "T-1")
    store.upsert_run(run)
    loaded = store.get_run("R-1")
    assert loaded is not None
    assert loaded.task_id == "T-1" and loaded.status == "passed"
    store.delete_run("R-1")
    assert store.get_run("R-1") is None


def test_locks_overlap_and_release(tmp_path: Path) -> None:
    store = Store(tmp_path / "board.db")
    assert store.acquire_locks("R-1", "T-1", ["src/**"], 60) == []
    conflicts = store.acquire_locks("R-2", "T-2", ["src/cart.py"], 60)
    assert conflicts and "held by R-1" in conflicts[0]
    assert store.acquire_locks("R-3", "T-3", ["tests/**"], 60) == []
    assert len(store.active_locks()) == 2
    store.release_locks("R-1")
    assert store.acquire_locks("R-4", "T-4", ["src/cart.py"], 60) == []
    store.clear_locks()
    assert store.active_locks() == []


def test_lock_ttl_expiry(tmp_path: Path) -> None:
    store = Store(tmp_path / "board.db")
    assert store.acquire_locks("R-1", "T-1", ["src/**"], 1) == []
    time.sleep(1.1)
    assert store.expire_locks() >= 1
    assert store.acquire_locks("R-2", "T-2", ["src/**"], 60) == []


def test_patterns_overlap() -> None:
    assert patterns_overlap("src/**", "src/cart.py")
    assert patterns_overlap("src/*", "src/**")
    assert not patterns_overlap("src/**", "tests/**")
    assert not patterns_overlap("docs/a.md", "docs/b.md")
    assert patterns_overlap("src/Cart.py", "src/cart.py")  # macOS/Windows are case-insensitive


def test_store_survives_concurrent_cold_start(tmp_path: Path) -> None:
    db = tmp_path / ".crewgit" / "board.db"
    db.parent.mkdir(parents=True)
    script = f"from pathlib import Path; from crewgit.store import Store; Store(Path(r'{db}'))"
    procs = [subprocess.Popen([sys.executable, "-c", script]) for _ in range(6)]
    for proc in procs:
        assert proc.wait(timeout=20) == 0
    assert db.exists()
