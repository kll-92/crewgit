"""The runner: locks, worktree, agent call, commit, gates, provenance, board state."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .agents.base import AgentResult, RunContext
from .agents.registry import build_adapter
from .config import Config, Paths, load_config, redact, scrubbed_env
from .contracts import (
    branch_name,
    build_prompt,
    get_task,
    load_workspace_tasks,
    new_run_id,
    prompt_hash,
    worktree_name,
)
from .gates import DiffInfo, GateEngine
from .gitops import Git
from .models import (
    AgentError,
    ContractError,
    CrewGitError,
    GateError,
    GitError,
    Run,
    Task,
    iso_now,
    sha256_text,
    task_status,
)
from .store import Store


class Runner:
    def __init__(self, root: Path, config: Config | None = None):
        self.root = Path(root).resolve()
        self.config = config or load_config(self.root)
        self.paths = Paths(self.root)
        self.paths.ensure()
        self.git = Git(self.root)
        self.store = Store(self.paths.board_db)
        self.env = scrubbed_env(self.config.passthrough)
        self.git.ensure_excluded()

    # ------------------------------------------------------------------ helpers

    def tasks(self) -> dict[str, Task]:
        return load_workspace_tasks(self.root, self.config)

    def task(self, task_id: str) -> Task:
        return get_task(self.root, self.config, task_id)

    def runs_by_task(self) -> dict[str, list[Run]]:
        return self.store.runs_by_task()

    def deps_ok(self, task: Task, runs_by_task: dict[str, list[Run]] | None = None) -> bool:
        grouped = runs_by_task if runs_by_task is not None else self.runs_by_task()
        for dependency in task.depends_on:
            runs = grouped.get(dependency, [])
            if not any(run.status in ("merged", "forced") for run in runs):
                return False
        return True

    def _agent_for(self, task: Task, agent_name: str | None):
        name = agent_name or task.agent or "coder"
        config = self.config.agent(name)
        return name, config, build_adapter(config)

    def _next_run_id(self, task_id: str) -> str:
        for _attempt in range(50):
            candidate = new_run_id()
            if self.store.get_run(candidate):
                continue
            if (self.paths.worktrees_dir / worktree_name(task_id, candidate)).exists():
                continue
            return candidate
        raise CrewGitError("could not allocate a unique run id; try again")

    # ------------------------------------------------------------------ dry run

    def plan(self, task_id: str, agent_name: str | None = None) -> dict[str, Any]:
        task = self.task(task_id)
        name, agent_config, adapter = self._agent_for(task, agent_name)
        prompt = build_prompt(task, self.config.project, name)
        base = self.git.head() if self.git.has_head() else ""
        return {
            "task": task.id,
            "title": task.title,
            "agent": name,
            "adapter": agent_config.adapter,
            "scope": list(task.scope),
            "branch": branch_name(task.id, "<run-id>"),
            "worktree": str(self.paths.worktrees_dir / worktree_name(task.id, "<run-id>")),
            "prompt_sha256": prompt_hash(prompt),
            "command": adapter.describe(
                RunContext(
                    task=task,
                    agent_name=name,
                    agent=agent_config,
                    run_id="<run-id>",
                    worktree=self.paths.worktrees_dir / worktree_name(task.id, "<run-id>"),
                    prompt=prompt,
                    prompt_path=self.paths.runs_dir / "<run-id>" / "prompt.md",
                    base_commit=base,
                    timeout_s=self.config.gates.timeout_s,
                    env=self.env,
                    repo_root=self.root,
                )
            ),
            "dry_run": True,
        }

    # ------------------------------------------------------------------ run

    def run_task(
        self,
        task_or_id: Task | str,
        agent_name: str | None = None,
        *,
        replay_of: str | None = None,
        base_commit: str | None = None,
        prompt_text: str | None = None,
        check_deps: bool = True,
        dry_run: bool = False,
    ) -> Run:
        task = task_or_id if isinstance(task_or_id, Task) else self.task(str(task_or_id))
        name, agent_config, adapter = self._agent_for(task, agent_name)

        if dry_run:
            return self._build_dry_run(task, name, agent_config, adapter)

        if not self.git.has_head():
            raise GitError("repository has no commits yet; make an initial commit before running agents")
        if not self.git.is_clean():
            raise GitError(
                "the main worktree is dirty; commit or stash your changes before running agents "
                "(CrewGit never touches your uncommitted work)"
            )
        if check_deps and replay_of is None:
            grouped = self.runs_by_task()
            missing = [
                dependency
                for dependency in task.depends_on
                if not any(run.status in ("merged", "forced") for run in grouped.get(dependency, []))
            ]
            if missing:
                raise ContractError(
                    f"task {task.id} is blocked by unmerged dependencies: {', '.join(missing)}",
                    detail={"field": "depends_on"},
                )

        run_id = self._next_run_id(task.id)
        branch = branch_name(task.id, run_id)
        worktree = self.paths.worktrees_dir / worktree_name(task.id, run_id)
        ttl = self.config.gates.timeout_s + 600
        conflicts = self.store.acquire_locks(run_id, task.id, list(task.scope), ttl)
        if conflicts:
            raise ContractError(
                f"scope is locked for task {task.id}: {'; '.join(conflicts)}",
                detail={"code": "scope_locked", "conflicts": conflicts},
            )

        base = base_commit or self.git.head()
        run = Run(
            run_id=run_id,
            task_id=task.id,
            title=task.title,
            agent=name,
            adapter=agent_config.adapter,
            base_commit=base,
            branch=branch,
            worktree=str(worktree),
            prompt_sha256="",
            contract_hash=task.contract_hash,
            model=agent_config.model,
            status="running",
        )
        self.store.upsert_run(run)

        try:
            prompt = prompt_text or build_prompt(task, self.config.project, name)
            run.prompt = prompt
            run.prompt_sha256 = prompt_hash(prompt)
            run_dir = self.paths.runs_dir / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            prompt_path = run_dir / "prompt.md"
            prompt_path.write_text(prompt, encoding="utf-8")

            self.git.add_worktree(worktree, branch, base)

            context = RunContext(
                task=task,
                agent_name=name,
                agent=agent_config,
                run_id=run_id,
                worktree=worktree,
                prompt=prompt,
                prompt_path=prompt_path,
                base_commit=base,
                timeout_s=self.config.gates.timeout_s,
                env=scrubbed_env(
                    self.config.passthrough,
                    extra={"CREWGIT_RUN": run_id, "CREWGIT_TASK": task.id, "CREWGIT_AGENT": name},
                ),
                repo_root=self.root,
            )
            started = time.monotonic()
            try:
                result = adapter.run(context)
            except AgentError as exc:
                result = AgentResult(exit_code=1, stderr=f"{exc.message}\n{exc.detail or ''}".strip())
            except Exception as exc:  # an adapter crash is a failed run, not a crashed CLI
                result = AgentResult(exit_code=1, stderr=f"adapter crashed: {exc}")
            run.duration_ms = int((time.monotonic() - started) * 1000)
            run.finished_at = iso_now()
            run.exit_code = result.exit_code
            run.usage = result.usage or {
                "input_tokens": None,
                "output_tokens": None,
                "cost_usd": None,
                "note": "adapter did not report usage",
            }
            run.model = result.model or run.model

            self._finalise_run(run, task, worktree, result)
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
            run.finished_at = run.finished_at or iso_now()
            self._persist(run)
            raise
        finally:
            self.store.release_locks(run_id)

        return run

    def _finalise_run(self, run: Run, task: Task, worktree: Path, result: AgentResult) -> None:
        run.status = "failed" if result.exit_code != 0 else "passed"
        if result.exit_code != 0:
            run.error = f"agent exited with {result.exit_code}"
            if result.stderr:
                run.error = run.error + "\n" + result.stderr.strip()[-2000:]

        if self.git.has_changes(worktree):
            message = self._commit_message(run, task, result)
            run.commit = self.git.commit_all(worktree, message)

        if not run.commit:
            run.status = "failed"
            run.error = (run.error + "\n" if run.error else "") + "agent produced no changes"
            self._persist(run)
            return

        diff = DiffInfo(
            base=run.base_commit,
            ref=run.commit,
            files=self.git.changed_files(run.base_commit, run.commit),
            stat=self.git.numstat(run.base_commit, run.commit),
            text=self.git.diff_text(run.base_commit, run.commit, max_chars=60_000),
            sha=self.git.diff_sha256(run.base_commit, run.commit),
        )
        run.changed_files = diff.files
        run.diff_stat = diff.stat
        run.diff_sha256 = diff.sha

        gate_engine = GateEngine(
            config=self.config,
            task=task,
            worktree=worktree,
            env=scrubbed_env(self.config.passthrough),
            git=self.git,
            review_runner=self._review_runner(task, worktree, run),
        )
        gates, gate_status = gate_engine.evaluate(diff)
        run.gates = gates
        run.status = gate_status
        if gate_status != "passed":
            failing = [gate for gate in gates if gate.status in ("fail", "error")]
            run.error = "; ".join(f"{gate.name}: {gate.detail.splitlines()[0]}" for gate in failing)[:1000]

        if result.exit_code != 0:
            run.status = "failed"
            run.error = f"agent exited with {result.exit_code}" + (f": {run.error}" if run.error else "")

        self._persist(run)

    def _build_dry_run(self, task: Task, name: str, agent_config, adapter) -> Run:
        prompt = build_prompt(task, self.config.project, name)
        return Run(
            run_id="dry-run",
            task_id=task.id,
            title=task.title,
            agent=name,
            adapter=agent_config.adapter,
            base_commit=self.git.head() if self.git.has_head() else "",
            branch=branch_name(task.id, "dry-run"),
            worktree=str(self.paths.worktrees_dir / worktree_name(task.id, "dry-run")),
            prompt_sha256=prompt_hash(prompt),
            prompt=prompt,
            contract_hash=task.contract_hash,
            status="passed",
            error="dry run: nothing executed",
        )

    def _review_runner(self, task: Task, worktree: Path, run: Run):
        reviewer_name = self.config.gates.review_agent
        if not reviewer_name or reviewer_name not in self.config.agents:
            return None
        reviewer_config = self.config.agents[reviewer_name]
        adapter = build_adapter(reviewer_config)

        def _run_review(prompt: str):
            review_path = self.paths.runs_dir / run.run_id / "review-prompt.md"
            review_path.parent.mkdir(parents=True, exist_ok=True)
            review_path.write_text(prompt, encoding="utf-8")
            return adapter.run(
                RunContext(
                    task=task,
                    agent_name=reviewer_name,
                    agent=reviewer_config,
                    run_id=run.run_id,
                    worktree=worktree,
                    prompt=prompt,
                    prompt_path=self.paths.runs_dir / run.run_id / "review-prompt.md",
                    base_commit=run.base_commit,
                    timeout_s=self.config.gates.timeout_s,
                    env=scrubbed_env(
                        self.config.passthrough,
                        extra={"CREWGIT_RUN": run.run_id, "CREWGIT_TASK": task.id, "CREWGIT_AGENT": reviewer_name},
                        ),
                    repo_root=self.root,
                )
            )

        return _run_review

    def _commit_message(self, run: Run, task: Task, result: AgentResult) -> str:
        body_lines = [f"Agent: {run.agent} ({run.adapter})", f"Run: {run.run_id}"]
        if result.stdout.strip():
            body_lines.append("")
            body_lines.append(redact(result.stdout.strip())[:1500])
        trailers = [
            f"Crewgit-Task: {task.id}",
            f"Crewgit-Run: {run.run_id}",
            f"Crewgit-Agent: {run.agent}",
            f"Crewgit-Contract-Hash: {task.contract_hash}",
        ]
        return "\n".join(
            [f"feat({task.id}): {task.title}", "", *body_lines, "", *trailers, ""]
        )

    def _persist(self, run: Run) -> None:
        payload = json.dumps(run.to_dict(), ensure_ascii=False, indent=2)
        manifest_path = self.paths.runs_dir / f"{run.run_id}.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(payload, encoding="utf-8")
        if run.commit:
            try:
                self.git.note_add(run.commit, payload, lock_path=self.paths.notes_lock)
            except GitError as exc:  # provenance failure must be visible, not silent
                run.error = (run.error + "; " if run.error else "") + f"provenance note failed: {exc.message}"
        self.store.upsert_run(run)

    # ------------------------------------------------------------------ parallel

    def run_ready(self, *, parallel: int = 3, limit: int | None = None) -> list[Run]:
        if parallel < 1:
            raise ContractError("--parallel must be >= 1")
        tasks = self.tasks()
        grouped = self.runs_by_task()
        ready: list[Task] = []
        for task in sorted(tasks.values(), key=lambda item: item.id):
            if not self.deps_ok(task, grouped):
                continue
            status, _reason = task_status(task, grouped.get(task.id, []), True)
            if status in ("done", "running", "review"):
                continue
            ready.append(task)
        if limit:
            ready = ready[:limit]
        if not ready:
            return []

        results: list[Run] = []
        with ThreadPoolExecutor(max_workers=min(parallel, len(ready))) as pool:
            futures = {pool.submit(self.run_task, task): task for task in ready}
            for future, task in futures.items():
                try:
                    results.append(future.result())
                except Exception as exc:
                    results.append(self._error_run(task, exc))
        return results

    def _error_run(self, task: Task, exc: Exception) -> Run:
        run = Run(
            run_id=f"R-error-{int(time.time())}-{task.id}",
            task_id=task.id,
            title=task.title,
            agent=task.agent or "unknown",
            adapter="none",
            base_commit="",
            branch="",
            worktree="",
            prompt_sha256="",
            prompt="",
            status="failed",
            error=str(exc),
            finished_at=iso_now(),
        )
        self._persist(run)
        return run

    # ------------------------------------------------------------------ external runs

    def register_external(
        self,
        task_id: str,
        agent_name: str,
        branch: str,
        commit: str,
        summary: str = "",
    ) -> Run:
        """Register a branch produced outside CrewGit (another agent, a CI job, a human)."""
        task = self.task(task_id)
        if branch == self.config.default_branch:
            raise ContractError("cannot submit the default branch as a run")
        if not self.git.branch_exists(branch):
            raise ContractError(f"branch '{branch}' does not exist")
        head = self.git.rev_parse(branch)
        commit_sha = self.git.rev_parse(f"{commit}^{{commit}}")
        if not self.git.is_ancestor(commit_sha, head):
            raise ContractError(f"commit {commit_sha[:8]} is not an ancestor of {branch}")
        base = self.git.merge_base(self.config.default_branch, commit_sha)
        if not base:
            raise ContractError("cannot find a merge base with the default branch")
        if not agent_name:
            raise ContractError("agent is required for an external submission")

        run_id = self._next_run_id(task.id)
        worktree = self.paths.worktrees_dir / worktree_name(task.id, run_id)
        ttl = self.config.gates.timeout_s + 600
        conflicts = self.store.acquire_locks(run_id, task.id, list(task.scope), ttl)
        if conflicts:
            raise ContractError(
                f"scope is locked for task {task.id}: {'; '.join(conflicts)}",
                detail={"code": "scope_locked", "conflicts": conflicts},
            )
        prompt = summary or f"external submission of {branch} at {commit_sha[:8]}"
        run = Run(
            run_id=run_id,
            task_id=task.id,
            title=task.title,
            agent=agent_name,
            adapter="external",
            base_commit=base,
            branch=branch,
            worktree=str(worktree),
            prompt_sha256=sha256_text(prompt),
            prompt=prompt,
            contract_hash=task.contract_hash,
            status="running",
            started_at=iso_now(),
        )
        self.store.upsert_run(run)
        created = False
        try:
            self.git.add_worktree_detached(worktree, commit_sha)
            created = True
            diff = DiffInfo(
                base=base,
                ref=commit_sha,
                files=self.git.changed_files(base, commit_sha),
                stat=self.git.numstat(base, commit_sha),
                text=self.git.diff_text(base, commit_sha, max_chars=60_000),
                sha=self.git.diff_sha256(base, commit_sha),
            )
            run.changed_files = diff.files
            run.diff_stat = diff.stat
            run.diff_sha256 = diff.sha
            run.commit = commit_sha
            run.finished_at = iso_now()
            if not diff.files:
                run.status = "failed"
                run.error = "external run has no changes relative to the merge base"
            else:
                gates, status = GateEngine(
                    config=self.config,
                    task=task,
                    worktree=worktree,
                    env=scrubbed_env(self.config.passthrough),
                    git=self.git,
                    review_runner=self._review_runner(task, worktree, run),
                ).evaluate(diff)
                run.gates = gates
                run.status = status
                if status != "passed":
                    failing = [gate for gate in gates if gate.status in ("fail", "error")]
                    run.error = "; ".join(
                        f"{gate.name}: {gate.detail.splitlines()[0]}" for gate in failing
                    )[:1000]
            self._persist(run)
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
            self._persist(run)
            raise
        finally:
            self.store.release_locks(run_id)
            if created:
                self.git.remove_worktree(worktree)
        return run

    # ------------------------------------------------------------------ merge / reject

    def load_run(self, run_id: str) -> Run:
        run = self.store.get_run(run_id)
        if run:
            return run
        path = self.paths.runs_dir / f"{run_id}.json"
        if path.exists():
            return Run.from_dict(json.loads(path.read_text(encoding="utf-8")))
        note = self.git.find_note(f'"run_id": "{run_id}"')
        if note:
            run = Run.from_dict(json.loads(note))
            self.store.upsert_run(run)
            return run
        raise ContractError(f"unknown run '{run_id}'")

    def merge(self, run_id: str, *, force: bool = False, reason: str | None = None) -> dict[str, Any]:
        run = self.load_run(run_id)
        if not force and run.status not in ("passed",):
            raise GateError(
                f"run {run_id} is not mergeable (status={run.status}); fix the gates or use --force --reason"
            )
        if force and not reason:
            raise ContractError("--force requires --reason so the override is auditable")
        if not self.git.branch_exists(run.branch):
            raise GitError(f"branch {run.branch} no longer exists")
        if not self.git.has_head():
            raise GitError("repository has no commits yet; make an initial commit before running agents")
        if not self.git.is_clean():
            raise GitError("main worktree is dirty; commit or stash before merging")

        run.status = "forced" if force else "merged"
        run.override = reason if force else None
        trailers = [
            f"Crewgit-Task: {run.task_id}",
            f"Crewgit-Run: {run.run_id}",
            f"Crewgit-Agent: {run.agent}",
            f"Crewgit-Contract-Hash: {run.contract_hash}",
        ]
        if force:
            trailers.append(f"Crewgit-Override: {reason}")
        message = "\n".join(
            [
                f"merge: {run.task_id} {run.title}",
                "",
                f"CrewGit merge of {run.run_id} by {run.agent} ({run.adapter}).",
                "",
                *trailers,
                "",
            ]
        )
        merge_commit = self.git.merge_no_ff(run.branch, message)
        self._persist(run)
        self.git.remove_worktree(Path(run.worktree))
        self.git.delete_branch(run.branch)
        return {"run": run, "commit": merge_commit, "branch": run.branch}

    def reject(self, run_id: str, reason: str) -> Run:
        run = self.load_run(run_id)
        if not reason:
            raise ContractError("reject requires a reason")
        run.status = "rejected"
        run.error = reason
        self._persist(run)
        return run

    def replay(self, run_id: str) -> Run:
        original = self.load_run(run_id)
        if not original.prompt:
            raise ContractError(f"run {run_id} has no stored prompt; cannot replay")
        tasks = self.tasks()
        if original.task_id not in tasks:
            raise ContractError(f"task {original.task_id} no longer exists; cannot replay")
        task = tasks[original.task_id]
        replay = self.run_task(
            task,
            original.agent,
            replay_of=run_id,
            base_commit=original.base_commit,
            prompt_text=original.prompt,
            check_deps=False,
        )
        replay.reproduced = replay.diff_sha256 == original.diff_sha256
        self._persist(replay)
        return replay

    # ------------------------------------------------------------------ views

    def _run_view(self, run: Run) -> dict[str, Any]:
        return {
            "run_id": run.run_id,
            "task_id": run.task_id,
            "agent": run.agent,
            "adapter": run.adapter,
            "status": run.status,
            "branch": run.branch,
            "commit": run.commit,
            "commit_short": self.git.short(run.commit) if run.commit else None,
            "gates": [gate.to_dict() for gate in run.gates],
            "diff_stat": run.diff_stat,
            "changed_files": run.changed_files,
            "cost_usd": run.total_cost,
            "duration_ms": run.duration_ms,
            "started_at": run.started_at,
            "replay_of": run.replay_of,
            "reproduced": run.reproduced,
            "error": run.error,
        }

    def board(self) -> dict[str, Any]:
        tasks = self.tasks()
        grouped = self.runs_by_task()
        items = []
        counts = {status: 0 for status in ("todo", "blocked", "running", "review", "done")}
        total_cost = 0.0
        unmetered = 0
        for task in sorted(tasks.values(), key=lambda item: item.id):
            runs = sorted(grouped.get(task.id, []), key=lambda run: run.started_at)
            deps_ok = self.deps_ok(task, grouped)
            status, reason = task_status(task, runs, deps_ok)
            counts[status] = counts.get(status, 0) + 1
            for run in runs:
                if run.total_cost is not None:
                    total_cost += run.total_cost
                elif run.status not in ("running",):
                    unmetered += 1
            items.append(
                {
                    **{
                        "id": task.id,
                        "title": task.title,
                        "agent": task.agent,
                        "scope": list(task.scope),
                        "depends_on": list(task.depends_on),
                        "budget": task.budget.to_dict(),
                        "contract_hash": task.contract_hash,
                    },
                    "status": status,
                    "status_reason": reason,
                    "latest_run": self._run_view(runs[-1]) if runs else None,
                    "runs": [self._run_view(run) for run in runs],
                }
            )
        return {
            "project": self.config.project,
            "branch": self.config.default_branch,
            "tasks": items,
            "counts": counts,
            "totals": {
                "runs": sum(len(runs) for runs in grouped.values()),
                "cost_usd": round(total_cost, 4),
                "unmetered_runs": unmetered,
            },
        }

    def stats(self) -> dict[str, Any]:
        grouped = self.runs_by_task()
        agents: dict[str, dict[str, Any]] = {}
        overrides = 0
        for runs in grouped.values():
            for run in runs:
                entry = agents.setdefault(
                    run.agent,
                    {"runs": 0, "passed": 0, "failed": 0, "merged": 0, "cost_usd": 0.0, "duration_ms": 0, "unmetered": 0},
                )
                entry["runs"] += 1
                if run.status in ("passed", "merged", "forced"):
                    entry["passed"] += 1
                if run.status in ("failed", "needs_human"):
                    entry["failed"] += 1
                if run.status in ("merged", "forced"):
                    entry["merged"] += 1
                if run.override:
                    overrides += 1
                if run.total_cost is not None:
                    entry["cost_usd"] = round(entry["cost_usd"] + run.total_cost, 6)
                else:
                    entry["unmetered"] += 1
                entry["duration_ms"] += run.duration_ms
        tasks = []
        for task_id, runs in sorted(grouped.items()):
            latest = sorted(runs, key=lambda run: run.started_at)[-1]
            tasks.append(
                {
                    "task_id": task_id,
                    "runs": len(runs),
                    "status": latest.status,
                    "cost_usd": round(sum(run.total_cost or 0 for run in runs), 6),
                }
            )
        return {
            "agents": agents,
            "tasks": tasks,
            "overrides": overrides,
            "totals": {
                "runs": sum(entry["runs"] for entry in agents.values()),
                "cost_usd": round(sum(entry["cost_usd"] for entry in agents.values()), 6),
                "unmetered_runs": sum(entry["unmetered"] for entry in agents.values()),
            },
        }

    def doctor(self) -> list[dict[str, str]]:
        checks: list[dict[str, str]] = []

        def add(name: str, status: str, detail: str) -> None:
            checks.append({"name": name, "status": status, "detail": detail})

        add("repo", "pass" if self.git.is_repo() else "fail", str(self.root))
        add("main worktree", "pass" if self.git.is_clean() else "warn", "clean" if self.git.is_clean() else "uncommitted changes present")
        add("notes ref", "pass" if self.git.has_notes_ref() else "warn", "refs/notes/crewgit" if self.git.has_notes_ref() else "missing; run a task to create it")

        locks = self.store.active_locks()
        add("locks", "pass" if not locks else "warn", f"{len(locks)} active lock(s)")

        registered = {item.get("worktree") for item in self.git.worktrees()}
        orphans = []
        if self.paths.worktrees_dir.exists():
            for path in self.paths.worktrees_dir.iterdir():
                if path.is_dir() and str(path) not in registered:
                    orphans.append(path.name)
        add("worktrees", "pass" if not orphans else "warn", f"{len(orphans)} orphan worktree(s)" if orphans else "ok")

        runs = self.store.list_runs()
        running = [run for run in runs if run.status == "running"]
        add("stale runs", "pass" if not running else "warn", f"{len(running)} run(s) marked running")

        missing_task = sorted({run.task_id for run in runs if run.task_id not in self.tasks()})
        add("task contracts", "pass" if not missing_task else "warn", f"missing contracts: {', '.join(missing_task)}" if missing_task else "all runs have contracts")

        return checks

    def gc(self) -> dict[str, int]:
        expired = self.store.expire_locks()
        self.git.prune_worktrees()
        removed = 0
        registered = {item.get("worktree") for item in self.git.worktrees()}
        if self.paths.worktrees_dir.exists():
            for path in self.paths.worktrees_dir.iterdir():
                if path.is_dir() and str(path) not in registered:
                    self.git.remove_worktree(path)
                    removed += 1
        return {"expired_locks": expired, "worktrees_removed": removed}
