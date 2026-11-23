## What changed

<!-- One paragraph. What behavior is different, and why. -->

## Related issue / spec

<!-- Link the issue, task id, or spec section. Behavior changes should update specs/ in this PR. -->

## How it was tested

- [ ] `make lint`
- [ ] `make test`
- [ ] Manual check (describe the repository, task, and command)

## Risk

<!-- What could break? Scope gate false positives, gate ordering, provenance format, API shape, CLI flags. -->

## Checklist

- [ ] One logical change per commit; commits are individually reviewable.
- [ ] New behavior is documented (README, docs/, or specs/).
- [ ] Regression test added for the bug or edge case.
- [ ] No secrets, tokens, cookies, or machine-specific paths.
- [ ] Runtime state (`.crewgit/runs/`, `.crewgit/worktrees/`, `board.db*`) is not committed.
