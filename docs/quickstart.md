# Quickstart

This walkthrough takes a scratch repository from zero to a merged, provenance-carrying run. It takes about five minutes and does not call a model until step 5.

## 0. Install

```bash
pipx install git+https://github.com/kll-92/crewgit.git
crewgit version    # crewgit 0.1.0
```

Python 3.10+ and Git 2.30+ are required. For a source checkout, use `make install`.

## 1. A scratch repository

```bash
mkdir crewgit-quickstart && cd crewgit-quickstart
git init -b main
printf 'def price(cents):\n    return cents / 100\n' > price.py
printf 'from price import price\n\ndef test_price():\n    assert price(199) == 1.99\n' > test_price.py
git add . && git commit -m "start price helper"
crewgit init --project "Quickstart"
git add .crewgit && git commit -m "chore: add crewgit workspace"
```

`crewgit init` writes `.crewgit/config.yaml` and `tasks/`, and adds runtime paths to `.git/info/exclude`. It does not commit anything.

## 2. Write a contract

```bash
crewgit task new \
  --id T-201 \
  --title "Add a currency formatter" \
  --agent coder \
  --scope "price.py" \
  --scope "test_price.py" \
  --tests "python -m pytest -q test_price.py"
```

Then edit `tasks/T-201.yaml` and add context:

```yaml
context: |
  Add format_price(cents) -> str, e.g. format_price(199) == "$1.99".
  Keep the existing price() API. Use integer cents, no floats.
```

Validate and commit the contract:

```bash
crewgit task check
git add tasks/T-201.yaml
git commit -m "docs(tasks): add T-201 currency formatter contract"
```

A contract is code. Review it like code.

## 3. See the plan without executing

```bash
crewgit run T-201 --dry-run
```

This prints the task, agent, adapter, branch, worktree path, prompt SHA-256, and the exact command that would run. Nothing is executed, no tokens are spent.

For the fully offline version, use a mock agent:

```bash
crewgit agent add coder --adapter mock --role coder
```

Mock agents apply deterministic `mock_actions` from the contract. They exist for demos and CI, not for real work.

## 4. Connect a real agent

Claude Code:

```bash
crewgit agent add coder --adapter claude --model claude-sonnet
crewgit agent add reviewer --adapter claude --model claude-sonnet
```

Any other CLI through a command template:

```bash
crewgit agent add coder \
  --adapter generic \
  --command "aider --yes --no-auto-commits --message-file {prompt_file}"
```

Placeholders: `{prompt_file}`, `{worktree}`, `{task_id}`, `{run_id}`, `{agent}`, `{base_commit}`, `{repo_root}`. The command runs with `cwd` set to the run's worktree and a scrubbed environment.

The reviewer is a separate agent by default (`gates.review.agent: reviewer`). It gets a review prompt and must answer with JSON: `{"verdict": "approve"|"revise", "reason": "..."}`.

## 5. Run, inspect, merge

```bash
crewgit run T-201 --agent coder
crewgit show R-20261123-… --diff
```

A passed run has its gates listed, a diff stat, a commit, and a manifest. If scope or budget fails, fix the contract or the work — do not widen the scope to make a bad diff pass.

```bash
crewgit merge R-20261123-…
```

The merge is `--no-ff` and carries four trailers. `main` stays green because tests ran in the worktree before the merge.

If a run is genuinely wrong but you need it on main (rare, e.g. an emergency revert), the only path is:

```bash
crewgit merge R-… --force --reason "incident 2026-11-23, approved by @kll"
```

Overrides are counted in `crewgit stats` and recorded in the manifest.

## 6. Run the team in parallel

Two independent contracts with non-overlapping scopes can run together:

```bash
crewgit run --ready --parallel 3
```

`--ready` runs every unblocked task. Scope locks prevent two runs from touching the same paths; a conflicting run waits for the lock to expire or fails fast. Start with `--limit 2` on a laptop.

Check the board:

```bash
crewgit board
crewgit serve --open     # http://127.0.0.1:7878
```

## 7. Let an external agent join over MCP

```json
{
  "mcpServers": {
    "crewgit": {
      "command": "crewgit",
      "args": ["mcp", "-C", "/absolute/path/to/crewgit-quickstart"]
    }
  }
}
```

The external agent can read contracts and the board, and submit a branch it already committed with `crewgit_submit_run`. CrewGit runs the gates and records provenance. It cannot merge.

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `working tree has uncommitted changes` | CrewGit refuses to stash your work | Commit or stash manually, then retry. |
| `repository has no commits yet` | A run needs a base commit | Make an initial commit. |
| `scope: out-of-scope paths: …` | The diff touched paths outside the contract | Revert the file, or write a new contract that declares it. |
| `tests: timed out` | The acceptance command hung | Fix the test or raise `gates.timeout_s`. |
| `review: unparseable verdict` | Reviewer did not return JSON | Tighten the reviewer prompt/model; the run needs a human. |
| `lock held by R-…` | Another run owns an overlapping scope | Wait, or inspect with `crewgit board`; stale locks expire by TTL. |
| `merge refused … status=failed` | Red gates | Fix the run, or use `--force --reason` deliberately. |
| Board shows `unmetered` | The adapter did not report usage | Expected for mock agents; do not read it as `$0`. |

Health check and cleanup:

```bash
crewgit doctor
crewgit gc
```

## 9. Where to go next

- [`README.md`](../README.md) for the full command surface and design rationale.
- [`specs/002-technical-design.md`](../specs/002-technical-design.md) for schemas, state machines, and failure handling.
- [`specs/000-constitution.md`](../specs/000-constitution.md) for the rules this project enforces on itself.
- [`CONTRIBUTING.md`](../CONTRIBUTING.md) if you want to add an adapter or a gate.
