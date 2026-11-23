# Contributing to CrewGit

CrewGit is deliberately small: a git-native collaboration layer, not an agent framework. Contributions that keep it small, observable, and honest are welcome.

Before writing code, read [`specs/000-constitution.md`](specs/000-constitution.md). It is the contract this repository holds itself to.

## Development setup

Requires Python 3.10+ and Git 2.30+.

```bash
git clone https://github.com/kll-92/crewgit.git
cd crewgit
make install
make test
make lint
```

`make install` creates `.venv` (uv if available, otherwise `python3 -m venv`) and installs the package in editable mode with dev extras. If your shell has a different Python layout:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
pytest -q
ruff check src tests
```

The full suite is offline. It builds real temporary git repositories and never calls a model API. Keep it that way.

## What to work on

Good first contributions:

- **A new adapter** in `src/crewgit/agents/`: Codex CLI, Gemini CLI, OpenCode, or a well-documented generic recipe.
- **A gate plugin proposal**: an issue describing the signal, the failure semantics, and why it belongs in the default path.
- **Docs and examples**: a real repository walkthrough, a screencast, a translation fix.
- **Bug reports with a failing test**: the fastest route to a fix.

Open an issue before large changes. For anything that changes behavior, the spec changes first (Constitution, Article I).

## Commit rules

One logical change per commit. Every commit must be independently reviewable and leave the tree working.

Use a conventional prefix: `feat`, `fix`, `test`, `docs`, `refactor`, `chore`, `perf`, `ci`.

If you are working through a task contract, append the step trailer:

```text
feat(runner): refuse empty diffs before gates run

An empty run wastes gates and produces a meaningless provenance record.

Crewgit-Step: 12-runner
```

Do not commit generated runtime state (`.crewgit/runs/`, `.crewgit/worktrees/`, `board.db*`). `crewgit init` writes those to `.git/info/exclude`; keep it that way. Commit `.crewgit/config.yaml` and `.crewgit/tasks/*.yaml`.

## Adding an adapter

An adapter is a small class implementing `Adapter.run(ctx)` and returning `AgentResult`.

1. Read `src/crewgit/agents/base.py` and copy the shape of `generic.py`.
2. Register it in `src/crewgit/agents/registry.py` and the `agent add --adapter` choices.
3. Add a unit test with a fake executable or a deterministic stub. Never require network or a paid key in CI.
4. Document the command shape in `README.md` and `docs/quickstart.md`.
5. Add a task contract example under `examples/` if the adapter needs one.

Adapters must not merge, push, or touch the main worktree. They run inside the worktree CrewGit gives them and return.

## Tests

- Put unit tests next to the behavior they protect: `tests/test_models.py`, `test_gitops.py`, `test_store.py`, `test_runner.py`, `test_api.py`, `test_cli.py`, `test_demo.py`.
- Use the `repo` fixture in `tests/conftest.py`. It creates a real git repository with a failing test and a valid contract.
- Every bug fix gets a regression test. The error budget rule is literal: the second occurrence of the same class of mistake adds a rule or a test.
- Tests must not depend on wall-clock timing, network, or a developer's global git config.

## Pull request checklist

- [ ] The change is described in the PR body, including what could break.
- [ ] `make lint` is clean.
- [ ] `make test` is green.
- [ ] Behavior changes update `specs/` in the same PR.
- [ ] New user-facing behavior is documented in `README.md` or `docs/`.
- [ ] No secrets, tokens, cookies, or machine-specific paths in code, tests, or docs.
- [ ] Commits are scoped and individually meaningful.

## Code style

- Python 3.10+, type hints on public functions.
- Ruff with the repository config (line length 100; `E501` and `B008` ignored for Typer/FastAPI defaults).
- Prefer small modules and explicit data shapes over clever abstractions.
- Errors: raise `CrewGitError` (or a subclass) with an actionable message. The CLI prints `✗ message` and exits 1.
- No new runtime dependency without a short note in the PR explaining why the standard library is insufficient.

## Security

Do not report vulnerabilities in a public issue. See [`SECURITY.md`](SECURITY.md).

## License

By contributing, you agree that your contribution is licensed under the MIT License.
