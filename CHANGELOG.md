# Changelog

All notable changes to CrewGit are documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: [SemVer](https://semver.org/).

## [0.1.0] — 2026-11-23

First public MVP. Local-first, offline-testable, no hosted service.

### Added

- **Task contracts.** YAML tasks with scope globs, forbidden paths, budgets, acceptance commands, dependencies, context, and deterministic mock actions.
- **Isolated runs.** One `git worktree` and branch per run (`crewgit/<task>/<run>`), with scope locks and TTL-based stale lock recovery.
- **Five gates.** `scope → budget → lint → tests → review`, fail-fast by default. Scope and budget are computed from the real diff.
- **Machine-readable review.** Reviewer agents must return a JSON verdict; unparseable output escalates to `needs_human`, and reviewer edits are a boundary violation.
- **Provenance.** Merge commits carry `Crewgit-Task`, `Crewgit-Run`, `Crewgit-Agent`, `Crewgit-Contract-Hash` trailers. Manifests live in `refs/notes/crewgit` and `.crewgit/runs/`.
- **Replay.** Re-execute a run and compare diff hashes: identical, or explicitly `diverged`.
- **Local board.** FastAPI board API and a single-page UI; `--read-only` mode for demos.
- **MCP stdio server.** `crewgit_list_tasks`, `crewgit_get_task`, `crewgit_get_board`, `crewgit_submit_run`. External agents can submit branches; merging stays human.
- **CLI.** `init`, `agent`, `task`, `run`, `board`, `show`, `merge`, `reject`, `replay`, `stats`, `doctor`, `gc`, `serve`, `mcp`, `demo`, `version`; `--json` on read commands.
- **Adapters.** `mock` (deterministic, offline), `generic` (any CLI via a command template), `claude` (Claude Code command shape).
- **Offline demo.** `crewgit demo` builds a throwaway repo, hires three mock agents, blocks an out-of-scope edit, merges the rest, and prints the provenance chain. No API key, no network.
- **44 tests** covering models, git operations, store/locks, runner, gates, API, CLI, and the demo; GitHub Actions CI on Python 3.10–3.13 plus a wheel build.

### Design decisions

- Git is the source of truth. The board and manifests are indexes, never the record.
- Agents are trusted like a Makefile. No container isolation in P0; environment is scrubbed and redacted.
- Merging is always explicit and human. `--force --reason` is allowed, counted, and audited.
- Unknown usage stays unknown (`null` / `unmetered`), never a fabricated `$0`.

### Known limitations

- Single host only; no remote runner.
- No sandbox or per-agent identity.
- No auto-merge, rebase, or merge queue yet.
- Replay is exact for deterministic adapters; LLM agents may diverge.
- PyPI publication not done; install from source.
- Windows is best-effort until Phase 2.

[0.1.0]: https://github.com/kll-92/crewgit/releases/tag/v0.1.0
