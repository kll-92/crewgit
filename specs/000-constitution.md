# 000 — Constitution · 项目铁律

> **Status:** binding · **Version:** 0.1 · **Scope:** every commit, every agent, every document in this repository.
> 任何与本文件冲突的做法，以本文件为准；要改规则，先改这份文档并单独提交。

CrewGit exists to make many coding agents behave like a disciplined team. The rules below are the
same rules the tool enforces on its users, applied to the tool itself.

---

## Article I — Spec before code

1. Every feature starts as a spec change: a PRD requirement (`specs/001-prd.md`), a design section
   (`specs/002-technical-design.md`), or a task contract under `tasks/`.
2. A task contract is the atomic unit of work. It declares `id`, `title`, `depends_on`, `scope`
   (globs the agent may touch), `acceptance` (commands that must pass), `budget` (diff limits), and
   optional `mock_actions` for deterministic demos.
3. Definition of Done = code + tests + docs + green gates + a commit carrying provenance trailers.
   Missing any one of these means the task is not done, regardless of how good the diff looks.

## Article II — Git is the source of truth

1. Every state transition is a commit. Never end a step with a dirty working tree.
2. Commit format: `type(scope): imperative summary` (Conventional Commits). The body explains *why*;
   the diff explains *what*.
3. Merged work must carry these trailers:
   `Crewgit-Task`, `Crewgit-Run`, `Crewgit-Agent`, `Crewgit-Contract-Hash`.
4. A commit that cannot be explained in one sentence is too large. Split it.
5. `main` is append-only. No force-push, no history rewriting on shared branches.

## Article III — One task, one branch, one worktree, one run

1. Branch: `crewgit/<task-id>/<run-id>`; worktree: `.crewgit/worktrees/<task-id>-<run-id>/`.
   A run never edits the main working tree.
2. Agents may only modify files matching their contract `scope`. Touching anything else is a gate
   failure, not a suggestion to be discussed.
3. Shared state (`.crewgit/config.yaml`, `tasks/`, locks, run manifests) is owned by CrewGit.
   Agents never edit it, and a diff that does is rejected by the `scope` gate.

## Article IV — Gates over trust

1. Pipeline order: `scope → budget → lint → tests → review → human`. Fail-fast by default.
2. A red gate blocks merge. The only override is `crewgit merge --force --reason "..."`, and both the
   manifest and the merge commit record the override. Overrides are counted in `crewgit stats`.
3. Gates must be deterministic commands. A review gate must return machine-readable JSON
   (`{"verdict": "approve" | "revise", "notes": [...]}`); unparseable output escalates to a human
   instead of guessing.
4. **Error budget rule:** when the same class of mistake happens twice, add (a) a regression test and
   (b) a rule to this document. Process fixes are cheaper than heroic review.

## Article V — Provenance is a product feature

1. Every run manifest records: prompt hash and text, base commit, agent and adapter, model if known,
   token usage and cost when the provider reports it, diff hash, changed files, gate results,
   duration, and exit code.
2. Manifests live as git notes on the run commit (`refs/notes/crewgit`), so provenance travels with
   the code and can be pushed (`git push origin refs/notes/crewgit`).
3. Never fabricate metrics. Unknown values are `null` with a reason string — never `0`.

## Article VI — Honest determinism

`crewgit replay` must either reproduce the exact diff hash, or explicitly report which files
diverged. It is forbidden to claim "reproducible" from a pass/fail result alone.

## Article VII — Small diffs win

Default budget per task: **≤ 6 files** and **≤ 300 changed lines**. Exceeding it means either split
the task, or raise the budget inside the contract where a reviewer can see the reason. Big diffs are
a review bug, not a productivity signal.

## Article VIII — Security and privacy

1. Agents run with the invoking user's privileges. Register only agents you trust; `crewgit run
   --dry-run` prints the fully resolved command and environment before execution.
2. Secrets never appear in task contracts, prompts, manifests, or git notes. The runner scrubs the
   environment down to an allowlist (`PATH`, `HOME`, `LANG`, `LC_*`, `CREWGIT_*`) plus anything the
   agent config explicitly declares.
3. CrewGit refuses to run in a dirty worktree and never auto-stashes, resets, or discards user
   changes.
4. Runtime state (`.crewgit/runs`, worktrees, `board.db`) is never committed.

## Engineering conventions

- Python ≥ 3.10, type hints on public APIs, no `print()` in library code (return values or raise),
  typed errors via `CrewGitError` subclasses.
- `ruff` clean at line length 100; `pytest` for every core module; tests must not require network.
- CLI is for humans (rich output) and machines (`--json` on every read command).
- Prefer stdlib and Git over new dependencies. Every dependency needs a one-line justification in the
  tech design.

## Agent collaboration protocol (for contributors, human or model)

1. Read `specs/` before touching code. Pick one task from `specs/004-tasks.md`; do not invent scope.
2. Announce the files you will touch, then touch only those.
3. Commit in small steps with `Crewgit-Step: NN-name` so the history reads like the plan.
4. If a gate fails, fix forward with a new commit — never amend a pushed commit.
5. Leave the tree clean and the board honest. A green board with a broken demo is a lie.
