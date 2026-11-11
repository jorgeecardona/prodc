# MCP server

Run prodc as an MCP server so an agent in any MCP client (Claude Code, Cursor, VS Code, Codex)
can read and edit the board through tools. It wraps the same commands as the CLI.

## Install

1. Register the server in your repo. This writes `.mcp.json` (Claude Code):

   ```bash
   prodc mcp install
   ```

2. Commit `.mcp.json`. Every agent that opens the repo loads the server.

3. Start a new agent session. Claude Code asks once to approve a project server.

The command written is `uvx --from "prodc[mcp]" prodc mcp serve`. It runs the latest prodc in
its own environment, so it does not clash with other tools in your venv.

Other clients:

```bash
prodc mcp install --client cursor    # .cursor/mcp.json
prodc mcp install --client vscode    # .vscode/mcp.json
prodc mcp install --client codex     # prints the codex command and TOML; writes nothing
prodc mcp install --scope user       # prints `claude mcp add --scope user ...`; writes nothing
```

Pin the project's own prodc instead of the latest:

```bash
prodc mcp install --command "uv run prodc mcp serve"
```

This needs `prodc[mcp]` in the project's dependencies.

## What install does

- It changes only the `prodc` entry. Every other server and key stays as it was.
- It prints the diff. `--dry-run` prints it and writes nothing.
- A second run prints `unchanged`.
- A file it cannot parse (for example JSON with comments) is refused, exit 2. Add the entry by
  hand.
- `prodc mcp uninstall` removes only the `prodc` entry. It deletes the file only when nothing
  else is left in it.

## Tools

Read tools (marked read-only for the client):

| Tool | CLI |
|---|---|
| `status` | `prodc status` (`client`, `goal`, `tag`, `only_must`, `include_drafts`, `stale_days`) |
| `show` | `prodc show <id>` |
| `plan` | `prodc plan` |
| `lint` | `prodc lint` |
| `inbox` | `prodc inbox` |
| `brief` | `prodc brief <client>` |
| `issues` | `prodc issues` |
| `suggest` | `prodc suggest` (never applies) |
| `review` | `prodc review` (lists drafts) |
| `dupes` | `prodc dupes` |

Write tools:

| Tool | CLI |
|---|---|
| `add_need` | `prodc add need` (`kind`: `secondary` or `assumption` only) |
| `add_decision` | `prodc add decision` |
| `set` | `prodc set <id> key=value` |
| `capture` | `prodc capture` (`kind`: `secondary` or `assumption` only) |
| `promote` | `prodc review --promote` |

Every tool returns `{exit_code, data, notices}`. `data` is the command's `--json` output.
`notices` is stderr. Exit 1 (a gate failed) is a normal result. Exit 2 is a tool error.

Every write returns `sha_before` and `sha_after`. Pass the last `sha_after` as `expect_sha` to
the next write: it is refused if the file changed in between.

## What is not exposed

- `capture` with `primary`. A primary source is a person's own words. The person adds it by
  editing the YAML.
- `accept`, `outcome`, `attest`. They record a person's judgement.
- `withdraw`, `reinstate`, `revise`, `add principle`, `add role`, `review --drop`. Product
  decisions stay with a person on the CLI.
- `sync`. It runs the shell commands in `[callbacks]`.

## The playbook

The server sends short instructions with the two rules. The full agent playbook (`prodc agent`)
is the `playbook` prompt and the `prodc://playbook` resource.

## Run it by hand

```bash
prodc mcp serve
```

It speaks MCP on stdin and stdout, so a terminal shows nothing. A bare `prodc mcp` prints help.
