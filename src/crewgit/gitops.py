"""Git primitives CrewGit depends on: worktrees, commits, diffs, notes, merges."""

from __future__ import annotations

import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

from .models import GitError, sha256_text

try:  # pragma: no cover - platform specific
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

NOTES_REF = "crewgit"
DEFAULT_TIMEOUT = 120
DEFAULT_EXCLUDES = (
    ".crewgit/worktrees/",
    ".crewgit/runs/",
    ".crewgit/board.db",
    ".crewgit/board.db-wal",
    ".crewgit/board.db-shm",
    ".crewgit/notes.lock",
    ".crewgit/server.log",
    "__pycache__/",
    "*.py[cod]",
    ".pytest_cache/",
    ".ruff_cache/",
    "node_modules/",
    ".venv/",
    ".DS_Store",
)


@contextmanager
def file_lock(path: Path | None) -> Iterator[None]:
    """Serialise note writes across threads/processes; no-op when path is None."""
    if path is None:
        yield
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+", encoding="utf-8") as handle:
        try:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class Git:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    # ------------------------------------------------------------------ plumbing

    def _run(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> subprocess.CompletedProcess[str]:
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=str(cwd or self.root),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError as exc:  # pragma: no cover
            raise GitError("git is not installed or not on PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise GitError(f"git {' '.join(args)} timed out after {timeout}s") from exc
        if check and proc.returncode != 0:
            message = (proc.stderr or proc.stdout or "").strip()
            raise GitError(
                f"git {' '.join(args)} failed: {message}",
                detail={"args": args, "returncode": proc.returncode},
            )
        return proc

    def is_repo(self) -> bool:
        proc = self._run(["rev-parse", "--is-inside-work-tree"], check=False)
        return proc.returncode == 0 and proc.stdout.strip() == "true"

    def init(self, branch: str = "main") -> None:
        path = self.root
        if self.is_repo():
            return
        path.mkdir(parents=True, exist_ok=True)
        self._run(["init", "-b", branch])

    def head(self) -> str:
        return self._run(["rev-parse", "HEAD"]).stdout.strip()

    def has_head(self) -> bool:
        return self._run(["rev-parse", "--verify", "--quiet", "HEAD"], check=False).returncode == 0

    def branch_name(self, cwd: Path | None = None) -> str:
        return self._run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd).stdout.strip()

    def ensure_excluded(self, patterns: tuple[str, ...] = DEFAULT_EXCLUDES) -> None:
        """Keep runtime state and common junk out of `git status` without touching .gitignore."""
        proc = self._run(["rev-parse", "--git-path", "info/exclude"], check=False)
        if proc.returncode != 0:
            return
        exclude = Path(proc.stdout.strip())
        if not exclude.is_absolute():
            exclude = self.root / exclude
        exclude.parent.mkdir(parents=True, exist_ok=True)
        existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        lines = {line.strip() for line in existing.splitlines()}
        additions = [pattern for pattern in patterns if pattern not in lines]
        if not additions:
            return
        separator = "" if not existing or existing.endswith("\n") else "\n"
        block = "" if "CrewGit runtime" in existing else "# CrewGit runtime and common agent junk\n"
        exclude.write_text(existing + separator + block + "\n".join(additions) + "\n", encoding="utf-8")

    def has_changes(self, worktree: Path, *, include_untracked: bool = True) -> bool:
        args = ["status", "--porcelain"]
        if not include_untracked:
            args.append("--untracked-files=no")
        proc = self._run(args, cwd=worktree)
        return bool(proc.stdout.strip())

    def is_clean(self, cwd: Path | None = None) -> bool:
        return not self._run(["status", "--porcelain"], cwd=cwd).stdout.strip()

    def porcelain(self, cwd: Path | None = None) -> str:
        return self._run(["status", "--porcelain"], cwd=cwd).stdout

    def short(self, sha: str) -> str:
        return self._run(["rev-parse", "--short", sha], check=False).stdout.strip() or sha[:7]

    def rev_parse(self, ref: str) -> str:
        return self._run(["rev-parse", ref]).stdout.strip()

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        proc = self._run(["merge-base", "--is-ancestor", ancestor, descendant], check=False)
        return proc.returncode == 0

    def merge_base(self, left: str, right: str) -> str | None:
        proc = self._run(["merge-base", left, right], check=False)
        return proc.stdout.strip() if proc.returncode == 0 else None

    def branch_exists(self, branch: str) -> bool:
        proc = self._run(["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], check=False)
        return proc.returncode == 0

    def delete_branch(self, branch: str, *, force: bool = True) -> None:
        self._run(["branch", "-D" if force else "-d", branch], check=False)

    def log_oneline(self, rev_range: str = "-8") -> str:
        return self._run(["log", "--oneline", "--decorate", rev_range]).stdout

    def commit_subject(self, sha: str) -> str:
        return self._run(["log", "-1", "--pretty=%s", sha], check=False).stdout.strip()

    # ------------------------------------------------------------------ worktrees

    def add_worktree(self, path: Path, branch: str, base: str | None = None) -> None:
        path = Path(path)
        if path.exists():
            raise GitError(f"worktree path already exists: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        if base:
            self._run(["worktree", "add", "-b", branch, str(path), base])
        else:
            self._run(["worktree", "add", str(path), branch])

    def add_worktree_detached(self, path: Path, ref: str) -> None:
        path = Path(path)
        if path.exists():
            raise GitError(f"worktree path already exists: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._run(["worktree", "add", "--detach", str(path), ref])

    def remove_worktree(self, path: Path, *, force: bool = True) -> None:
        proc = self._run(["worktree", "remove", *(["--force"] if force else []), str(path)], check=False)
        if proc.returncode != 0:
            self._run(["worktree", "prune"], check=False)

    def prune_worktrees(self) -> None:
        self._run(["worktree", "prune"], check=False)

    def worktrees(self) -> list[dict[str, str]]:
        proc = self._run(["worktree", "list", "--porcelain"], check=False)
        entries: list[dict[str, str]] = []
        current: dict[str, str] = {}
        for line in proc.stdout.splitlines():
            if not line.strip():
                if current:
                    entries.append(current)
                    current = {}
                continue
            key, _, value = line.partition(" ")
            current[key] = value
        if current:
            entries.append(current)
        return entries

    # ------------------------------------------------------------------ commits

    def commit_all(self, worktree: Path, message: str, *, dry_run: bool = False) -> str | None:
        """Stage everything and commit. Returns None when there is nothing to commit."""
        self._run(["add", "-A"], cwd=worktree)
        staged = self._run(["diff", "--cached", "--quiet", "HEAD"], cwd=worktree, check=False)
        if staged.returncode == 0:
            return None
        if dry_run:
            return None
        self._run(["commit", "-m", message], cwd=worktree)
        return self._run(["rev-parse", "HEAD"], cwd=worktree).stdout.strip()

    # ------------------------------------------------------------------ diffs

    def changed_files(self, base: str, ref: str) -> list[str]:
        proc = self._run(["diff", "--no-renames", "--name-only", f"{base}..{ref}"], check=False)
        if proc.returncode != 0:
            raise GitError(f"cannot diff {base}..{ref}: {proc.stderr.strip()}")
        return [line.strip() for line in proc.stdout.splitlines() if line.strip()]

    def numstat(self, base: str, ref: str) -> dict[str, int]:
        proc = self._run(["diff", "--no-renames", "--numstat", f"{base}..{ref}"], check=False)
        if proc.returncode != 0:
            raise GitError(f"cannot diff {base}..{ref}: {proc.stderr.strip()}")
        files = insertions = deletions = 0
        for line in proc.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            files += 1
            added, removed, _path = parts
            insertions += int(added) if added.isdigit() else 0
            deletions += int(removed) if removed.isdigit() else 0
        return {"files": files, "insertions": insertions, "deletions": deletions}

    def diff_text(self, base: str, ref: str, *, max_chars: int | None = None) -> str:
        proc = self._run(["diff", "--no-renames", "--no-color", f"{base}..{ref}"], check=False)
        if proc.returncode != 0:
            raise GitError(f"cannot diff {base}..{ref}: {proc.stderr.strip()}")
        text = proc.stdout
        if max_chars and len(text) > max_chars:
            text = text[:max_chars] + f"\n\n... truncated at {max_chars} characters ...\n"
        return text

    def diff_sha256(self, base: str, ref: str) -> str:
        return sha256_text(self.diff_text(base, ref))

    # ------------------------------------------------------------------ merge

    def merge_no_ff(self, branch: str, message: str) -> str:
        if not self.is_clean():
            raise GitError("main worktree is dirty; commit or stash your changes first")
        proc = self._run(["merge", "--no-ff", "-m", message, branch], check=False)
        if proc.returncode != 0:
            self._run(["merge", "--abort"], check=False)
            detail = (proc.stderr or proc.stdout).strip()
            raise GitError(f"merge of {branch} failed and was aborted: {detail}", detail={"branch": branch})
        return self.head()

    # ------------------------------------------------------------------ notes

    def note_add(self, commit: str, body: str, *, lock_path: Path | None = None) -> None:
        fd, temp_name = tempfile.mkstemp(prefix="crewgit-note-", suffix=".json")
        try:
            with open(fd, "w", encoding="utf-8") as handle:
                handle.write(body)
            with file_lock(lock_path):
                last_error = ""
                for _attempt in range(3):
                    proc = self._run(
                        ["notes", "--ref", NOTES_REF, "add", "-f", "-F", temp_name, commit],
                        check=False,
                    )
                    if proc.returncode == 0:
                        return
                    last_error = (proc.stderr or proc.stdout).strip()
                    time.sleep(0.25)
                raise GitError(f"failed to write git note on {commit}: {last_error}")
        finally:
            with suppress(OSError):
                Path(temp_name).unlink(missing_ok=True)

    def note_show(self, commit: str) -> str | None:
        proc = self._run(["notes", "--ref", NOTES_REF, "show", commit], check=False)
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        return proc.stdout

    def find_note(self, needle: str) -> str | None:
        """Scan notes for a substring; used to recover a run after a fresh clone."""
        proc = self._run(["notes", "--ref", NOTES_REF, "list"], check=False)
        if proc.returncode != 0:
            return None
        for line in proc.stdout.splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            body = self.note_show(parts[-1])
            if body and needle in body:
                return body
        return None

    def has_notes_ref(self) -> bool:
        proc = self._run(["rev-parse", "--verify", "--quiet", f"refs/notes/{NOTES_REF}"], check=False)
        return proc.returncode == 0
