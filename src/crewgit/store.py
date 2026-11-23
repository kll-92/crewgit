"""SQLite board: run manifests cache and file-scope locks. Disposable, never authoritative."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from .gitops import file_lock
from .models import Run, StoreError

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    task_id     TEXT NOT NULL,
    agent       TEXT,
    status      TEXT,
    branch      TEXT,
    commit_sha  TEXT,
    created_at  TEXT,
    manifest    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_task ON runs(task_id, created_at);

CREATE TABLE IF NOT EXISTS locks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern     TEXT NOT NULL,
    run_id      TEXT NOT NULL,
    task_id     TEXT NOT NULL,
    acquired_at REAL NOT NULL,
    expires_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_locks_expiry ON locks(expires_at);
"""


def _segment_compatible(left: str, right: str) -> bool:
    if left == "**" or right == "**":
        return True
    if any(char in left for char in "*?") or any(char in right for char in "*?"):
        return True  # conservative: treat wildcard segments as possibly overlapping
    return left.casefold() == right.casefold()


def patterns_overlap(left: str, right: str) -> bool:
    """Conservatively decide whether two scope globs could touch the same path."""
    left_segments = [seg for seg in left.replace("\\", "/").strip("/").split("/") if seg]
    right_segments = [seg for seg in right.replace("\\", "/").strip("/").split("/") if seg]
    for index in range(min(len(left_segments), len(right_segments))):
        if left_segments[index] == "**" or right_segments[index] == "**":
            return True
        if not _segment_compatible(left_segments[index], right_segments[index]):
            return False
    return True


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        try:
            conn = sqlite3.connect(self.path, timeout=15)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            return conn
        except sqlite3.Error as exc:  # pragma: no cover
            raise StoreError(f"cannot open board database: {exc}", detail={"path": str(self.path)}) from exc

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    # ------------------------------------------------------------------ runs

    def upsert_run(self, run: Run) -> None:
        manifest = json.dumps(run.to_dict(), ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (run_id, task_id, agent, status, branch, commit_sha, created_at, manifest)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status=excluded.status, commit_sha=excluded.commit_sha, manifest=excluded.manifest
                """,
                (
                    run.run_id,
                    run.task_id,
                    run.agent,
                    run.status,
                    run.branch,
                    run.commit,
                    run.started_at,
                    manifest,
                ),
            )

    def get_run(self, run_id: str) -> Run | None:
        with self._connect() as conn:
            row = conn.execute("SELECT manifest FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return Run.from_dict(json.loads(row["manifest"]))

    def list_runs(self, task_id: str | None = None) -> list[Run]:
        query = "SELECT manifest FROM runs"
        params: tuple[Any, ...] = ()
        if task_id:
            query += " WHERE task_id = ?"
            params = (task_id,)
        query += " ORDER BY created_at ASC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [Run.from_dict(json.loads(row["manifest"])) for row in rows]

    def runs_by_task(self) -> dict[str, list[Run]]:
        grouped: dict[str, list[Run]] = {}
        for run in self.list_runs():
            grouped.setdefault(run.task_id, []).append(run)
        return grouped

    def delete_run(self, run_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))

    # ------------------------------------------------------------------ locks

    def acquire_locks(self, run_id: str, task_id: str, patterns: list[str], ttl_s: int) -> list[str]:
        now = time.time()
        expires = now + max(int(ttl_s), 1)
        # Serialise the read-check-write across processes; SQLite alone cannot.
        with file_lock(self.path.with_name(self.path.name + ".lock")), self._connect() as conn:
                conn.execute("DELETE FROM locks WHERE expires_at < ?", (now,))
                rows = conn.execute(
                    "SELECT pattern, run_id, task_id FROM locks WHERE run_id != ?",
                    (run_id,),
                ).fetchall()
                conflicts = [
                    f"{row['pattern']} held by {row['run_id']} ({row['task_id']})"
                    for row in rows
                    if any(patterns_overlap(pattern, row["pattern"]) for pattern in patterns)
                ]
                if conflicts:
                    return conflicts
                conn.executemany(
                    "INSERT INTO locks (pattern, run_id, task_id, acquired_at, expires_at) VALUES (?, ?, ?, ?, ?)",
                    [(pattern, run_id, task_id, now, expires) for pattern in patterns],
                )
        return []

    def release_locks(self, run_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM locks WHERE run_id = ?", (run_id,))

    def active_locks(self) -> list[dict[str, Any]]:
        now = time.time()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT pattern, run_id, task_id, acquired_at, expires_at FROM locks WHERE expires_at >= ?",
                (now,),
            ).fetchall()
        return [dict(row) for row in rows]

    def expire_locks(self) -> int:
        now = time.time()
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM locks WHERE expires_at < ?", (now,))
        return cursor.rowcount

    def clear_locks(self) -> int:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM locks")
        return cursor.rowcount

    def task_locked_by(self, task_id: str) -> list[dict[str, Any]]:
        return [lock for lock in self.active_locks() if lock["task_id"] == task_id]
