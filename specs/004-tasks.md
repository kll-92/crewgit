# 004 — Task Breakdown · SDD 任务拆解

> **Purpose:** the contract between spec and code. Every task maps to files, a gate, and a commit.
> **Status legend:** `planned` · `doing` · `done` · `cut`

---

## Phase 0 tasks

| ID | Task | Files | Acceptance | Commit step | Status |
|---|---|---|---|---|---|
| P0-01 | Repository skeleton | `pyproject.toml`, `.gitignore`, `LICENSE`, `Makefile` | `pip install -e .` resolves; ruff config loads | `01-bootstrap` | done |
| P0-02 | Constitution | `specs/000-constitution.md` | rules cover spec, commits, gates, provenance, replay, budget, security | `02-constitution` | done |
| P0-03 | PRD | `specs/001-prd.md` | 10 P0 stories with acceptance; metrics and GTM present | `03-prd` | done |
| P0-04 | Technical design | `specs/002-technical-design.md` | schemas match implementation; ADRs recorded | `04-tech-design` | done |
| P0-05 | Roadmap + task breakdown | `specs/003-roadmap.md`, `specs/004-tasks.md` | phases have exit criteria; tasks map to commits | `05-roadmap-tasks` | done |
| P0-06 | Models + config | `src/crewgit/models.py`, `config.py` | contract validation typed; config defaults; cycles rejected | `06-models-config` | planned |
| P0-07 | Git operations | `src/crewgit/gitops.py` | worktree add/remove, commit with trailers, diff hash, notes round-trip, merge | `07-gitops` | planned |
| P0-08 | Board store + locks | `src/crewgit/store.py` | sqlite schema, run upsert, lock acquire/release/expiry, overlap detection | `08-store-locks` | planned |
| P0-09 | Contracts + prompt | `src/crewgit/contracts.py` | deterministic prompt hash; scope matcher; task loader | `09-contracts` | planned |
| P0-10 | Gates | `src/crewgit/gates.py` | scope/budget/lint/tests/review with typed results | `10-gates` | planned |
| P0-11 | Adapters | `src/crewgit/agents/*` | mock deterministic; generic template; claude json parsing | `11-adapters` | planned |
| P0-12 | Runner | `src/crewgit/runner.py` | single run + parallel ready set; manifest; note; locks released | `12-runner` | planned |
| P0-13 | CLI | `src/crewgit/cli.py` | init/agent/task/run/board/merge/replay/show/stats/doctor/gc/demo/serve/mcp | `13-cli` | planned |
| P0-14 | Board API + UI | `src/crewgit/server.py`, `src/crewgit/web/*` | `/api/board` shape; actions work; polling UI | `14-server-ui` | planned |
| P0-15 | MCP server | `src/crewgit/mcp.py` | initialize/tools list/call; submit_run gates a branch | `15-mcp` | planned |
| P0-16 | Demo | `src/crewgit/demo.py` | offline, < 90 s, blocked scope violation, green main | `16-demo` | planned |
| P0-17 | Tests + CI | `tests/*`, `.github/workflows/ci.yml` | ruff + pytest green on 3.10–3.13 | `17-tests-ci` | planned |
| P0-18 | README + assets | `README.md`, `README.zh-CN.md`, `docs/*` | real transcript, diagram, install, comparison, limits | `18-readme` | planned |
| P0-19 | Independent audit | `docs/audit-report.md` | a second agent checks spec↔code consistency; P0 findings fixed | `19-audit` | planned |
| P0-20 | Release | tag `v0.1.0`, repo public | install from clean venv; demo passes | `20-release` | planned |

---

## Gate definitions for this phase

| Gate | Command | Must pass before |
|---|---|---|
| lint | `python -m ruff check src tests` | every commit after P0-09 |
| unit | `python -m pytest tests -q` | every commit after P0-06 |
| demo | `crewgit demo` in a temp dir | P0-16, P0-17, P0-20 |
| docs | `README` transcript matches actual demo output | P0-18, P0-19 |

---

## Cut list (explicitly out of Phase 0)

- `crewgit rebase`, merge queue, GitHub Action, PyPI publication → Phase 1.
- Gate plugins, signed manifests, remote runners → Phase 2.
- Windows support, monorepo scopes → Phase 2/3.
- Hosted board, A2A interop → Phase 3.

If today's clock runs out, these are the things to cut — never the demo, the provenance trail, or the
`scope` gate.

---

## Post-MVP backlog (seed for Phase 1 issues)

1. `crewgit run --ready --parallel N` backpressure when a scope lock is held > TTL.
2. Reviewer prompt quality: two-pass review (intent vs diff).
3. Board: timeline view of runs, cost over time, per-agent leaderboard (cost/latency, not "wins").
4. `crewgit export --format jsonl` for audit tooling.
5. Adapter for MCP-native agents that submit a branch instead of editing files.
6. Contract linter: warn when scope is wider than the task title implies.
7. `crewgit init --from-spec` to generate tasks from a PRD section.
8. Pre-merge conflict radar against `main` (predict conflicts before merge).
