# AGENTS.md

Guidance for AI agents working in this repository.

- `README.md`: layout, setup, run commands, checks.
- `docs/CONTRIBUTING.md`: branches, commits, PRs, dependency and env-var rules.

## Rules

- Python 3.12, managed with uv. Add dependencies with `uv add <pkg>` (dev tools: `uv add --dev <pkg>`); never edit `uv.lock` by hand or use `pip install`.
- Reusable code lives in `src/classpartai/` and is imported by `app.py`, `notebooks/` and `eval/`. Don't copy logic between notebooks.
- Seed every source of randomness through `classpartai.config.set_seed()`.
- Before pushing: `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`. All must pass.
- Never commit `.env`, API keys, or large/licensed data (`data/raw/` is git-ignored).
- Running one test: `uv run pytest tests/test_smoke.py -k repeatable`.
