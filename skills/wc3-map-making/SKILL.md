---
name: wc3-map-making
description: Use when the user wants to create, edit, inspect, validate or test a Warcraft III map, campaign, AI or model/texture asset, or drive the Warcraft III World Editor or game, through the wc3 MCP tools.
---

# Warcraft III map making with the wc3 tools

The `wc3` MCP server works on real map files (`.w3x`/`.w3m`, map folders, `.w3n` campaigns). Game data comes read-only from the local Warcraft III install.

If a parameter or op named here is missing from the tool definitions you see (for example `wait`, `lint` or `probe_functions`), the session still holds an older version of the tools: ask the user to reconnect the `wc3` server (`/mcp`) or start a new session instead of working around it.

## Workflow

1. **Open or create.** `map_open` copies the map into a private working copy; `map_new` creates a new melee-ready map (JASS or Lua) and opens it. Edits touch only the working copy, which lives on disk, so the tools resume it after a server restart. If a tool still answers `not_open`, call `map_open`: it starts again from the map file, so only saved work is there.
2. **Look things up.** `data_search` / `data_get` find unit, ability, item, buff, upgrade, doodad, destructible, tile, sound and trigger-function ids. **Never guess ids.** `tileset="L"` (or `"Lordaeron Summer"`) lists only one tileset's tiles, cliffs, doodads and destructibles; a plain `query="A"` is a text search, not a tileset filter.
3. **Edit with the typed tools.**
   - Map info and imports: `info_get`, `info_edit`, `imports_edit`.
   - Object data: `objdata_list`, `objdata_get`, `objdata_edit`.
   - Triggers: `triggers_tree`, `trigger_get`, `triggers_edit`.
   - World: `terrain_get`, `terrain_edit`, `terrain_render`, `elements_list`/`elements_edit` (regions, cameras, sounds), `placed_list`/`placed_edit` (units, items, doodads, destructibles, start locations).
   - Campaigns: `campaign_new`, `campaign_get`, `campaign_edit`. AI: `ai_get`, `ai_edit`, `ai_export`. Assets: `asset_info`, `asset_convert`, `asset_edit`, `asset_preview`.
   - `map_file_read` / `map_file_write` are raw escape hatches; prefer the typed tools.
4. **Check.** `script_build` regenerates `war3map.j`/`war3map.lua`; `script_validate` runs pjass/JassHelper or the Lua checker (`lint=true` adds runtime traps); `map_validate` checks cross-file consistency and returns errors and warnings separately. `triggers_edit validate=true` does the build and check in the same call.
5. **Save.** `map_save` rebuilds the script and minimap image when needed, validates, writes a timestamped backup of the previous file (named in `backup`) and replaces the map atomically. `map_snapshot` makes a restore point before risky changes; `map_close` ends the session.
6. **Test in the game.** `game_test` (see `references/testing.md`).

## Reference files

Read the one you need before working in that area; each is a list of facts established in real maps, the editor and the game.

| File | What is in it |
|---|---|
| `references/terrain.md` | map size and playable area, `terrain_edit` ops and brushes, buildability, derived pathing, placed objects, start locations, ids whose model does not load |
| `references/objects.md` | `info_edit` shapes, `objdata_edit` fields per kind, what a copy inherits, shops and stock, items, Channel, **order strings** |
| `references/triggers.md` | trigger ops and position, function order, GUI variable types, JASS pitfalls, the `lint` rules |
| `references/game-behaviour.md` | heroes and experience, vision, combat, items, deaths, players and UI, workers and building |
| `references/testing.md` | `game_test`, probes, background runs, logins, the World Editor round trip |

## Keeping calls cheap

- `data_get` / `objdata_get` take a **list of ids** in one call and answer compactly (raw code -> value, empty fields left out); `fields` narrows further, `verbose=true` brings back names, categories and types when you need them.
- Write generated batches to a local JSON file and pass `ops_file` instead of `ops` (`placed_edit`, `terrain_edit`, `objdata_edit`, `triggers_edit`); a long trigger script can come from `script_file`.
- `placed_edit` compact rows: `{"op": "add", "kind": "destructible", "columns": ["type", "x", "y", "variation", "angle"], "rows": [["LTlt", -1833, -3653, 2, 113], ...]}`. Fields outside `columns` apply to every row.
- `placed_edit` `scatter` places random objects in one op: `{"op": "scatter", "kind": "destructible", "types": {"LTlt": 3, "ATtr": 1}, "count": 200, "rect": [l, b, r, t], "exclude": [{"x": 0, "y": 0, "radius": 1500}], "min_distance": 96, "seed": 7}`. It stays on land by default, picks only variations whose model is installed, and beats computing coordinates yourself.
- One `game_test` run can hold many checks; every launch costs a minute or more and can ask for a login.

## Rules

- **Never type credentials.** The game can show a Battle.net login screen at any launch; ask the user to log in (with "Keep me logged in") and to approve any authenticator request. `game_test` returns `login_required: true` and leaves the game open; the same call again continues in it (`continued_game: true`).
- The game loads a map only while its window is in front, so leave the game window alone while a run is loading.
- Take turns with the user in the World Editor and **never discard unsaved work** there; `map_save` refuses while the editor holds the map.
- Keep a backup (`map_save` makes one) before replacing a user's map, and say which file changed.
- If `game_test` returns no results and `exited_early`, the map failed to load: take a screenshot (`screenshot=true`) and tell the user.
- Before a launch, run `script_validate lint=true` and `map_validate`: a rule that fires there is a game run saved.
