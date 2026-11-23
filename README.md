<div align="center">

# CrewGit

**Agents write code. Git keeps them honest.**

Git-native collaboration for multiple coding agents: task contracts, isolated worktrees,
quality gates, provenance on every commit, and replay.

</div>

> Status: v0.1.0 in development. Full README lands with the release commit.

## Why

Running three coding agents at once should not mean merge hell, unreviewable diffs, and
"trust me, the tests pass". CrewGit gives every agent a task contract, its own worktree, a
gate pipeline, and a provenance trail you can audit with plain `git`.

## Quick start

```bash
pipx install .
crewgit demo
```

## Docs

- [Product requirements](specs/001-prd.md)
- [Technical design](specs/002-technical-design.md)
- [Roadmap](specs/003-roadmap.md)
- [Constitution](specs/000-constitution.md)
