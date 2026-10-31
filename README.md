# ClassPart AI

IS469 Gen AI with LLMs group project (SMU, August Term 2026).

<!-- One paragraph: the problem, who it is for, and what the system does. -->

## Project layout

```
src/classpartai/   the system: shared code that notebooks, eval and the app import
app.py             Streamlit demo
notebooks/         exploration and experiments
eval/              evaluation scripts and results
data/              small datasets; sources documented in data/README.md
tests/             pytest tests
```

## Setup

Prerequisite: [uv](https://docs.astral.sh/uv/) (`brew install uv`, or `curl -LsSf https://astral.sh/uv/install.sh | sh`). uv installs the right Python version for you.

```bash
gh repo clone kohqingjia/classpartai
cd classpartai
uv sync                  # creates .venv and installs everything from uv.lock
cp .env.example .env     # then fill in your API key
```

## Running

```bash
uv run streamlit run app.py      # demo at http://localhost:8501
uv run jupyter lab               # notebooks (add jupyter first: uv add --dev jupyterlab)
```

## Checks

Run these before every push; CI runs the same three.

```bash
uv run ruff check .              # lint (add --fix to auto-fix)
uv run ruff format .             # format
uv run pytest                    # tests
```

## Reproducibility

All randomness goes through `classpartai.config.set_seed()` (seed from `SEED` in `.env`, default 42). Dependencies are pinned in `uv.lock`; add new ones with `uv add <package>` so the lockfile stays in sync.

## Contributing

See [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md). New teammates start with [docs/TEAMMATE-SETUP.md](docs/TEAMMATE-SETUP.md).
