# Contributing

New to the project? Set up GitHub, Linear and your local environment with [TEAMMATE-SETUP.md](./TEAMMATE-SETUP.md).

## Branches

- Base all work off an up-to-date `main`.
- Name a branch for a Linear issue with Linear's "Copy git branch name" button, for example `kohqingjia/cpa-12`. The issue ID in the name links the branch, its commits and its pull request to the issue.
- One Linear issue = one branch = one PR. If your work depends on someone else's unmerged branch, branch off theirs and retarget your PR to `main` after theirs merges.
- For work without an issue, use short, lowercase, hyphen-separated names: `feat/query-rewriting`, `fix/empty-retrieval`, `chore/ci-cache`.

## Commits

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add query rewriting to the retriever
fix: handle empty retrieval results
chore: pin ruff version
```

## Pull requests

- Open the PR against `main` using the template, with `Implements CPA-<n>` in the body.
- Copilot reviews every PR automatically; address its comments.
- Squash merge only.

## Pre-PR verification

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

New logic in `src/classpartai/` needs at least one pytest test covering the core behaviour.

## Adding dependencies

Use `uv add <package>` (or `uv add --dev <package>` for tools only you run) and commit both `pyproject.toml` and `uv.lock`. Every runtime dependency must be used by the project.

## Environment variables

Load them through `src/classpartai/config.py`, and document each new one with a comment in `.env.example`. Mention it in `README.md` if it changes the setup steps.
