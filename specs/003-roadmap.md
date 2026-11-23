# 003 — Roadmap · 产品路线文档

> **Version:** 0.1 · **Horizon:** 6 months · **Last updated:** 2026-11-23
> **Rule:** every phase has an exit criterion, and a phase that misses it twice is re-scoped, not
> extended. Stars are a lagging indicator of utility; we optimise the leading indicators.

---

## Phase 0 — Provable MVP (Day 0)

**Thesis:** if the demo cannot convince a stranger in 60 seconds, nothing else matters.

| Deliverable | Definition of done |
|---|---|
| SDD spec set | constitution, PRD, this roadmap, task breakdown, technical design — committed before code |
| Core engine | contracts, git worktrees, run manifests, notes, SQLite board |
| Gates | scope, budget, lint, tests, review, with typed failures |
| CLI | `init agent task run board merge replay show stats doctor gc demo serve mcp` |
| Board UI | five columns, gate chips, diff viewer, run/merge actions |
| MCP server | `list_tasks`, `get_task`, `get_board`, `submit_run` |
| Demo | deterministic, offline, blocks one scope violation, ends green on `main` |
| Quality | ruff clean, pytest green, CI workflow, ≥ 80% coverage of core modules |
| Docs | README (EN + ZH), quickstart, SECURITY, CONTRIBUTING, screenshots |

**Exit criteria**
1. `git clone && pipx install . && crewgit demo` finishes in < 90 s on a clean machine.
2. 100% of merged commits carry the four provenance trailers; `git notes` round-trips after clone.
3. A deliberately out-of-scope run is blocked and cannot be merged.
4. `crewgit replay` on the mock run reports an identical diff hash.

**Ship:** tag `v0.1.0`, repository public, README hero + GIF.

---

## Phase 1 — Team-ready (Week 1–4, Dec 2026)

Goal: usable by two strangers on a real repo without reading the source.

| Workstream | Scope | Exit |
|---|---|---|
| Distribution | PyPI release, `pipx`/`uvx` one-liners, Homebrew tap (stretch) | `pip install crewgit` works on macOS + Linux |
| CI integration | `crewgit-gate` GitHub Action: runs gates on a copied branch, comments gate chips on the PR | One real PR gated end-to-end |
| Adapters | `codex`, `aider`, `gemini` + fixture-based tests; documented adapter SDK | Adding an adapter is a < 1 h job with docs |
| Merge ergonomics | `crewgit rebase <run>`, merge queue for > 3 concurrent merges, conflict pre-check | No manual `git` needed in the happy path |
| Observability | `crewgit stats --json` schema, cost caps per task, `serve --read-only` for sharing | A team dashboard runs from Docker one-liner |
| Content | 90-second video, GIF in README, "Why worktrees" post, comparison page | 3 pieces published |
| Onboarding | 3 real examples (FastAPI service, Next.js app, Python library) | Each example runs `demo` in CI |

**Exit:** 300+ stars, ≥ 1 000 PyPI installs, ≥ 10 external issues, ≥ 3 outside contributors, median
first response < 24 h.

**Kill criteria:** if after 4 weeks < 50 stars and < 100 installs, re-examine the problem framing
(not the code) before investing in Phase 2.

---

## Phase 2 — Ecosystem (Month 2–3)

Goal: other people extend CrewGit without us.

1. **Plugin SDK for gates** (`crewgit.gates` entry points): policy packs for Django, Terraform,
   migrations, dependency diffs; `diffledger`-style evidence tools can plug in as a gate.
2. **Signed provenance:** per-agent keys sign manifests; `crewgit verify <run>` checks the chain
   offline. Answers "who really wrote this line?" without trusting the platform.
3. **Remote runners:** `crewgit runner --host` executes runs on another machine with a USD cap and
   a hard timeout; the board stays local.
4. **Monorepo scopes:** scope patterns address sub-packages; per-package owners and gates.
5. **Windows GA** and Git LFS/submodule handling; `doctor` becomes a real diagnostic suite.
6. **Docs site** with searchable command reference and adapter gallery.

**Exit:** ≥ 3 community gate plugins, ≥ 8 adapters, 1 500+ stars, 25+ contributors, 5+ downstream
projects linking CrewGit in their docs.

---

## Phase 3 — Scale and organisations (Month 4–6)

Goal: survive a team of 20 humans + 20 agents on one monorepo.

| Theme | Scope |
|---|---|
| Merge queue | serialized integration, batch testing, automatic rebase on green |
| Identity | per-agent commit identity option, SSO-mapped humans, audit export (JSONL) |
| Policy | org-level policy packs, required gates, override quotas, cost budgets per team |
| Hosted board | read-only hosted dashboard (optional paid tier funds the OSS work) |
| Interop | A2A / MCP tool federation, LangGraph node wrapper, CrewAI tool wrapper |
| Resilience | crash-safe run journal, resumable runs, snapshot/restore of worktrees |

**Exit:** one public case study of a team running ≥ 10 agents for a month; 5 000 stars; sustainable
maintainer funding (sponsors or a paid tier that does not paywall core features).

---

## Star flywheel (30-day launch plan)

| Day | Action | Asset |
|---|---|---|
| 0 | Repo public; README with real transcript, diagram, limitations | README, banner, 60 s demo |
| 1 | Show HN: "Git is the original multi-agent protocol" | Technical post + honest Q&A |
| 2 | r/LocalLLaMA + r/ChatGPTCoding | Problem-first title, no hype adjectives |
| 3 | X thread with GIF; tag agent-tool maintainers | 8-post thread |
| 4 | V2EX + 掘金 + 少数派 Chinese write-up | Chinese quickstart |
| 7 | PR to awesome-ai-agents / awesome-mcp-servers | One-line entry |
| 10 | Product Hunt (builder angle: "hire agents, not vibes") | Gallery + 90 s video |
| 14 | Adapter bounty issues (`good first issue`) | 5 issues with fixtures |
| 21 | First community call / office hours; v0.2 release notes | Changelog |
| 30 | Retro post: what worked, what the data says | Metrics snapshot |

**Leading indicators to watch daily:** installs, demo completions (GitHub release downloads),
issue quality, star velocity, inbound PRs. **Lagging:** stars, forks, mentions.

**What actually earns stars (ranked):** solves a problem people already feel → one-command proof →
trustworthy docs → visible provenance → active maintainer. Campaigns only amplify the first four.

---

## Today's time budget (5 hours, Phase 0)

| Slot | Work | Output |
|---|---|---|
| 0:00–0:40 | Spec set (constitution, PRD, tech, roadmap, tasks) | 5 commits |
| 0:40–2:10 | Core engine + gates + adapters | 4–5 commits |
| 2:10–3:10 | CLI + board + MCP | 3 commits |
| 3:10–3:50 | Demo + tests + CI green | 2–3 commits |
| 3:50–4:30 | README, visuals, independent audit | 2 commits |
| 4:30–5:00 | Fix audit findings, push, make public, tag v0.1.0 | 1–2 commits |

If a slot overruns, cut scope in Phase 1, never cut the demo or the provenance trail.

---

## Risk register and phase gates

| Risk | Trigger | Response |
|---|---|---|
| Demo feels staged | Viewers say "it's just mock agents" | Ship a real-LLM example video in Phase 1; keep mock labelled |
| Worktree edge cases | ≥ 3 issues on submodules/LFS | Add `doctor` checks; document limits; P2 hardening |
| Security criticism | "Agents can run anything" | Publish SECURITY.md with trust model and roadmap to containers |
| Framework war fatigue | Low engagement on HN | Pivot messaging from "framework" to "review tool for AI code" |
| Maintainer bandwidth | Issues > 20 open | Adapter bounties, template replies, monthly triage day |
| Scope creep | Roadmap P1 slips twice | Freeze new features, ship distribution and docs only |
