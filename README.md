# wc3-mcp

An MCP server and Claude Code plugin for making Warcraft III maps with Claude. It works directly on map files and can also drive the World Editor and the game.

- **Maps:** create maps (JASS or Lua), and edit map info, imports, object data, GUI/JASS/Lua triggers, terrain, regions, cameras, sounds and placed units, items and doodads.
- **Scripts:** build `war3map.j`/`war3map.lua` the way the World Editor does, validate them with pjass/JassHelper, and check maps for errors.
- **More content:** campaigns (`.w3n`), AI files (`.wai`), and models and textures (MDX/MDL, BLP/DDS).
- **Desktop:** drive the World Editor and run maps in the game (`game_test`).

The plugin also installs a skill (`wc3-map-making`) that tells Claude how to use the tools.

## Prerequisites

| Requirement | Why |
|---|---|
| **Windows 10/11** | The editor and game drivers use the Win32 API (pywin32). |
| **Warcraft III 3.x (Reforged), installed with Battle.net** | Game data, pjass and JassHelper are read from the install. The install is found automatically; otherwise set `WC3MCP_INSTALL`. |
| **[uv](https://docs.astral.sh/uv/getting-started/installation/)** | Runs the server. On first start it downloads Python 3.13 (if missing) and the Python packages `mcp`, `pywin32`, `numpy` and `pillow`. |
| **[Claude Code](https://docs.claude.com/en/docs/claude-code)** | Hosts the plugin (any MCP client works with the manual setup below). |
| A Battle.net login (for `game_test` only) | The game may ask you to log in before it loads a map. Log in yourself with "Keep me logged in"; Claude never enters credentials. |

Install uv (PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## Install in Claude Code (plugin)

Run in Claude Code:

```
/plugin marketplace add BenqsXd/wc3-mcp
/plugin install wc3-mcp@wc3-mcp
```

Or from a terminal:

```powershell
claude plugin marketplace add BenqsXd/wc3-mcp
claude plugin install wc3-mcp@wc3-mcp
```

Restart Claude Code. `/mcp` should list the `wc3` server. The first start takes a minute while uv installs the packages.

Try it: *"Create a 64x64 Lordaeron Summer map at C:\Maps\Arena.w3x with a hero for player 1, then test it in the game."*

## Manual setup (any MCP client, no plugin)

```powershell
git clone https://github.com/BenqsXd/wc3-mcp
cd wc3-mcp
uv sync
claude mcp add wc3 --scope user -e PYTHONPATH="$PWD\src" -- uv run --directory "$PWD" python -m wc3mcp.server
```

For other clients, run `uv run --directory <repo> python -m wc3mcp.server` over stdio with `PYTHONPATH=<repo>\src`. With plain pip instead of uv, run `pip install mcp pywin32 numpy pillow` on Python 3.13+, then `python -m wc3mcp.server` with the same `PYTHONPATH`. To get the skill too, copy `skills/wc3-map-making` to `%USERPROFILE%\.claude\skills\`.

## Configuration

All settings are optional environment variables:

| Variable | Default |
|---|---|
| `WC3MCP_INSTALL` | Warcraft III folder from the registry, else `C:\Program Files (x86)\Warcraft III` |
| `WC3MCP_DOCUMENTS` | `Documents\Warcraft III` (follows OneDrive redirection) |
| `WC3MCP_HOME` | `%LOCALAPPDATA%\wc3mcp` (working copies, backups, logs, tool copies) |

The game install is never modified. Maps are edited in working copies; `map_save` backs up the original before replacing it.

## What's new in 0.3

- Bulk work stays out of the conversation: `ops_file` (and `script_file` for triggers), compact `columns`/`rows` adds, a `scatter` op with weights, exclusion zones and spacing, and `created` as ref ranges.
- Missing models are caught before the editor shows them: `data_search` reports `model_ok`, `data_get` lists missing model files, `placed_edit` warns and `map_validate` flags every placed object without a model.
- `map_save merge_external=true` (and `map_open merge_external=true`) keeps working-copy edits and takes what a World Editor save recomputed, instead of a lossy choice.
- Moving a start location with `placed_edit` updates the player start in `war3map.w3i`; `map_validate` warns when they disagree.
- `terrain_render` draws doodads and destructibles; `data_search tileset=` also scopes doodads and destructibles.
- `editor_log` returns the editor's viewport messages and missing files (and says the editor writes its log only on quit); `game_test` reports `missing_files`, captures the game window behind other windows, and the probe adds hero counts and `BJDebugMsg` output.

## What's new in 0.2

- Terrain brushes take a rectangle, a path stroke (roads) or no area at all (the whole map), not only circles; results report the 16-slot tile palette.
- `map_new` takes and reports `fill_tile`, and `data_search kind=tile` can be scoped to a tileset.
- Script triggers get the editor's `InitTrig_` wrapper automatically, and `triggers_edit validate=true` checks the script in the same call.
- `game_test probe=true` reports what a running map looks like without a reporting trigger of your own; screenshots capture the game window only.
- Clearer failures: `map_save` names the World Editor when it holds the map, working copies survive a server restart, and `map_validate` warns while pathing, shadows and the minimap are older than the terrain.

## Development

```powershell
uv sync
uv run pytest              # offline tests (the corpus tests use the local install and ladder maps)
uv run pytest -m editor    # drives the World Editor
uv run pytest -m game      # launches Warcraft III (log in to Battle.net when asked)
```

Design notes and phase plans are in `docs/superpowers`.
