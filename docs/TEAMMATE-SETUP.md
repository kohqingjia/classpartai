# ClassPart AI: teammate setup

## Before you start

1. **Accept the GitHub invite** to `kohqingjia/classpartai`: https://github.com/kohqingjia/classpartai/invitations
2. **Accept the Linear invite** to the workspace and join the **CPA** team.
3. Copy everything in the block below into Claude Code or Codex, run it from any folder, and follow what it asks you to do.

## Prompt for your Claude / Codex

```
Set up my machine to work on our group project. Do each step, verify it, and tell me clearly if something needs me (a browser login or an invite I haven't accepted). Don't skip verification.

PROJECT
- Repo: https://github.com/kohqingjia/classpartai (owner: kohqingjia; I'm a collaborator)
- Issue tracker: Linear, team key CPA (issues look like CPA-12). I'm new to Linear.

1. GITHUB ACCESS
- Check `gh --version`; if missing, install the GitHub CLI (on macOS: `brew install gh`).
- Run `gh auth status`. If I'm not logged in, tell me to run `gh auth login` (GitHub.com, HTTPS, login with a web browser) and wait for me.
- Confirm I have push access: `gh api repos/kohqingjia/classpartai --jq .permissions.push` must print true. If it prints false or 404, stop and tell me to accept the collaborator invite at https://github.com/kohqingjia/classpartai/invitations (or ask kohqingjia to send one).
- Check git has my name and email (`git config --global user.name` / `user.email`); if empty, ask me for them and set them.

2. LINEAR MCP (so you can read and update my Linear issues)
- Linear's official remote MCP server is https://mcp.linear.app/mcp. It logs in through the browser (OAuth); no API key needed.
- If you are Claude Code: run `claude mcp add --transport http --scope user linear https://mcp.linear.app/mcp`, then tell me to type `/mcp` in Claude Code, pick "linear" and sign in in the browser. When signing in, choose the workspace that has the CPA team.
- If you are Codex CLI: add the server with `codex mcp add linear --url https://mcp.linear.app/mcp` and sign in with `codex mcp login linear`. If this Codex version doesn't support remote servers, add this to ~/.codex/config.toml instead and restart Codex:
    [mcp_servers.linear]
    command = "npx"
    args = ["-y", "mcp-remote", "https://mcp.linear.app/mcp"]
  The first run opens a browser to sign in.
- Verify: list the Linear teams and confirm a team with key CPA appears, then list the issues assigned to me. If CPA is missing, I'm signed into the wrong workspace or haven't been added to the team. Tell me which.

3. CLONE AND SET UP
- Clone into a folder I choose (ask me where): `gh repo clone kohqingjia/classpartai`.
- Read AGENTS.md, README.md and docs/CONTRIBUTING.md first. Follow the setup steps in README.md exactly instead of guessing commands.
- The project uses Python 3.12 managed by uv. Check `uv --version`; if missing, install it (on macOS: `brew install uv`). uv installs the right Python itself.
- Run `uv sync`, then copy .env.example to .env. Ask me for any API key it needs; never invent one.
- Verify the setup: `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` must all pass on a fresh main. If one fails, show me the error rather than changing code.
- Start the demo with `uv run streamlit run app.py` and confirm it opens in the browser.

4. PROVE I CAN PUSH (then clean up)
- Create a throwaway branch `chore/setup-check-<my-github-username>`, push it, confirm it appears on GitHub, then delete it locally and remotely. Don't open a PR and don't push to main (main is protected).

5. HOW WE WORK (remember this for later tasks)
- Pick a Linear CPA issue, then use Linear's "Copy git branch name" for the branch (e.g. yourname/cpa-12). Always branch off an up-to-date main.
- Conventional Commits (feat:, fix:, chore:, docs:, test:, refactor:).
- Open a PR to main using the repo's template, with "Implements CPA-<n>" in the body. Linear then moves the issue automatically: opened → In Progress, review → In Review, merged → Done.
- Copilot reviews every PR automatically. Address its comments. Squash merge only.
- Run ruff check, ruff format and pytest before every push.
- Never push to main directly, never force-push shared branches, never commit .env or secrets.

When done, give me a short checklist of what's set up, what passed, and anything I still need to do.
```
