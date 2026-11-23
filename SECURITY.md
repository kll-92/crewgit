# Security policy

CrewGit runs coding agents on a real repository. That is a security-relevant act by design.

## Reporting a vulnerability

**Do not open a public issue for a vulnerability.**

Use GitHub's private vulnerability reporting on this repository:

1. Go to **Security** → **Advisories** → **Report a vulnerability**.
2. Include: affected version, a minimal reproduction, the impact, and any mitigation you know.
3. Expect an acknowledgement within 72 hours and a triage decision within 7 days.

If the advisory flow is unavailable, open a minimal public issue that says only "security report requested — please provide a private channel", without exploit details.

Supported versions: `0.1.x` (current). Older pre-release snapshots are not supported.

## Trust model

CrewGit treats a coding agent as **exactly as trusted as a Makefile in the repository**. It is a contributor with a keyboard, not a sandboxed process.

What CrewGit does:

- Runs the agent inside a dedicated `git worktree`, never in your main working tree.
- Scrubs the child environment: only `PATH`, `HOME`, `LANG`, `TERM`, `TZ`, `TMPDIR`, `USER`, `SHELL`, `LC_*`, `CREWGIT_*`, plus an explicit `environment.passthrough` allowlist.
- Redacts values whose keys look sensitive (`TOKEN`, `KEY`, `SECRET`, `PASSWORD`, `CREDENTIAL`) before they are written to manifests or notes.
- Computes scope/budget from the actual diff, not from what the agent claims.
- Refuses to merge a failed run without `--force --reason`, and records the override.
- Refuses to run on a dirty working tree instead of auto-stashing your changes.

What CrewGit does **not** do (P0):

- It does not containerize, seccomp, or otherwise sandbox the agent process.
- It does not prevent an agent from reading files outside its declared scope, or from running network calls, if the host allows them.
- It does not validate the agent binary or model provider.
- It does not protect against prompt injection inside repository content the agent reads.
- It does not push notes or branches for you; pushing is a separate, explicit action.

## Operating recommendations

- Run agents in a disposable checkout or a dedicated machine/VM, not on a laptop with production credentials.
- Do not export cloud keys, SSH agents, or package tokens into the environment. If a task needs a secret, pass a scoped, short-lived credential through `environment.passthrough` and rotate it.
- Keep `forbid` globs for `.github/**`, `migrations/**`, lockfiles, and deployment config.
- Treat `--force --reason` as an incident: review the diff, then rotate anything the agent could have touched.
- Keep the board bound to `127.0.0.1` unless you put authentication in front of it. `crewgit serve` has no built-in auth; `--read-only` only disables mutations.
- Review the manifest before merging: `crewgit show <run>` prints the gates, diff stat, agent, and command.

## Dependency and supply-chain posture

- Runtime dependencies: Typer, Rich, PyYAML, FastAPI, Uvicorn.
- The test suite is offline and uses no model API.
- CI runs lint, tests, and a wheel build on Python 3.10–3.13.
- PyPI publication is planned for Phase 1; until then install from source and pin a commit.

## Known residual risks

| Risk | Status |
|---|---|
| Agent executes arbitrary commands with your user's privileges | Accepted in P0; documented; container isolation is Phase 2 |
| Prompt injection via repository files | Accepted; scope/budget gates limit blast radius but do not eliminate it |
| Secrets in agent output or diffs | Mitigated by env scrubbing and redaction, not eliminated |
| Board exposed on a public interface | Operator responsibility; bind locally by default |
| Replay divergence for non-deterministic agents | Reported as `diverged`; never silently treated as reproducible |
