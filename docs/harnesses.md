# Installing wc3-mcp in other agent harnesses

wc3-mcp is a standard MCP server (stdio) plus an Agent Skill (`skills/wc3-map-making/SKILL.md`). Any harness that
runs local MCP servers can use it; the ones with a plugin or extension format get the skill too.

Requirements everywhere: Windows 10/11 with Warcraft III installed (the editor and game tools drive them through
the Win32 API; the file tools work anywhere Python runs), Python 3.13 and [uv](https://docs.astral.sh/uv/).

The repository carries these manifests:

| File | Read by |
|---|---|
| `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` | Claude Code (and GitHub Copilot CLI as a fallback) |
| `plugin.json` + `mcp.json` + `skills/` (Agent Plugins 1.0) | OpenAI Codex and ChatGPT, GitHub Copilot CLI, Cursor, and every other client of the [Agent Plugins](https://agent-plugins.org) standard |
| `.agents/plugins/marketplace.json` | Codex / ChatGPT marketplace (`codex plugin marketplace add`) |
| `.cursor-plugin/marketplace.json` | Cursor team marketplace |
| `gemini-extension.json` + `AGENTS.md` | Gemini CLI extensions |

How each was checked (2026-09-30): every manifest parses and follows the schema in its harness's documentation;
the exact command of `mcp.json` (Agent Plugins) and of `gemini-extension.json` was run and answered MCP
`initialize`, `tools/list` (73 tools) and a tool call. None of these harnesses was installed on the machine that
wrote this, so the install commands below come from their documentation and have not been run.

## Claude Code

```
/plugin marketplace add BenqsXd/wc3-mcp
/plugin install wc3-mcp@wc3-mcp
```

## OpenAI Codex (CLI, IDE, app) and ChatGPT

```bash
codex plugin marketplace add BenqsXd/wc3-mcp
```

Then `/plugins` in Codex (or the Plugins Directory in ChatGPT desktop) and install **wc3-mcp**. The plugin brings the
MCP server and the skill.

Without the plugin, add the server to `~/.codex/config.toml`:

```toml
[mcp_servers.wc3]
command = "uvx"
args = ["--from", "git+https://github.com/BenqsXd/wc3-mcp", "wc3-mcp"]
startup_timeout_sec = 60
```

## GitHub Copilot CLI

```bash
copilot plugin install BenqsXd/wc3-mcp
```

Copilot reads the root `plugin.json` (Agent Plugins 1.0), with `mcp.json` and `skills/`.

## Cursor

Add `https://github.com/BenqsXd/wc3-mcp` as a team marketplace (Customize > Plugins), or install the plugin folder
directly; Cursor reads the Agent Plugins `plugin.json`. MCP only, in `.cursor/mcp.json` or `~/.cursor/mcp.json`:

```json
{ "mcpServers": { "wc3": { "command": "uvx", "args": ["--from", "git+https://github.com/BenqsXd/wc3-mcp", "wc3-mcp"] } } }
```

## Gemini CLI

```bash
gemini extensions install https://github.com/BenqsXd/wc3-mcp
```

The extension starts the server with `uv run --directory ${extensionPath}` and loads `AGENTS.md`, which points the
model at the skill.

## DeepSeek

DeepSeek's own agents take MCP servers and Agent Skills rather than a plugin manifest:

- **DeepSeek Harness (`dsh`)**: add a local stdio server named `wc3` in the MCP settings (dsh-mcp-manager) with
  command `uvx` and arguments `--from git+https://github.com/BenqsXd/wc3-mcp wc3-mcp`. Tools appear as
  `mcp__wc3__*`.
- **DeepSeek-TUI** and **Deep Code**: add the same stdio server to their MCP configuration, and copy
  `skills/wc3-map-making` into their skills folder.
- DeepSeek models inside another harness (Claude Code, Copilot CLI, OpenCode and others, see DeepSeek's agent
  integration guides) use that harness's install above.

## Others (OpenCode, Cline, Roo, Windsurf, Kiro, Amp, Goose, Zed, Continue, ...)

Any MCP client can start the server with:

```
command: uvx
args:    --from git+https://github.com/BenqsXd/wc3-mcp wc3-mcp
```

or, from a clone, `uv run --directory <clone> --quiet --no-dev python -m wc3mcp.server` with
`PYTHONPATH=<clone>/src`. OpenCode example (`opencode.json`):

```json
{ "mcp": { "wc3": { "type": "local", "command": ["uvx", "--from", "git+https://github.com/BenqsXd/wc3-mcp", "wc3-mcp"] } } }
```

For the skill, copy `skills/wc3-map-making` into the harness's skills folder if it reads Agent Skills
(`SKILL.md`), or point its rules/context file at `AGENTS.md`.

## Clients with a tool limit

The server offers 73 tools. For a client that caps tools per server, `WC3MCP_TOOLS` exposes only tools starting
with the listed prefixes (`wc3_help` and `wc3_batch` always stay, and `wc3_batch` still reaches every tool):

```
WC3MCP_TOOLS=map_,objdata_,triggers_,data_,script_
```

Tool descriptions are kept under 1,024 characters (OpenAI models' limit; Claude Code cuts at 2,048); the details
live in `wc3_help(topic)`.
