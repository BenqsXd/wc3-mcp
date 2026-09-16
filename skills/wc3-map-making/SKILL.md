---
name: wc3-map-making
description: Use when the user wants to create, edit, inspect, validate or test a Warcraft III map, campaign, AI or model/texture asset, or drive the Warcraft III World Editor or game, through the wc3 MCP tools.
---

# Warcraft III map making with the wc3 tools

The `wc3` MCP server works on real map files (`.w3x`/`.w3m`, map folders, `.w3n` campaigns). Game data comes read-only from the local Warcraft III install.

## Workflow

1. **Open or create.** `map_open` copies the map into a private working copy; `map_new` creates a new melee-ready map (JASS or Lua) and opens it. Edits touch only the working copy, which lives on disk, so the tools resume it after a server restart. If a tool still answers `not_open`, call `map_open`: it starts again from the map file, so only saved work is there.
2. **Look things up.** `data_search` / `data_get` find unit, ability, item, buff, upgrade, doodad, destructible, tile, sound and trigger-function ids. Never guess ids. `tileset="L"` (or `"Lordaeron Summer"`) lists only one tileset's tiles, cliffs, doodads and destructibles. A plain `query="A"` is a text search, not a tileset filter.
3. **Edit with the typed tools.**
   - Map info and imports: `info_get`, `info_edit`, `imports_edit`.
   - Object data: `objdata_list`, `objdata_get`, `objdata_edit`.
   - Triggers: `triggers_tree`, `trigger_get`, `triggers_edit`.
   - World: `terrain_get`, `terrain_edit`, `terrain_render`, `elements_list`/`elements_edit` (regions, cameras, sounds), `placed_list`/`placed_edit` (units, items, doodads, destructibles, start locations).
   - Campaigns: `campaign_new`, `campaign_get`, `campaign_edit`. AI: `ai_get`, `ai_edit`, `ai_export`. Assets: `asset_info`, `asset_convert`, `asset_edit`, `asset_preview`.
   - `map_file_read` / `map_file_write` are raw escape hatches; prefer the typed tools.
4. **Check.** `script_build` regenerates `war3map.j`/`war3map.lua`; `script_validate` runs pjass/JassHelper or the Lua checker and reports `ok`; `map_validate` checks cross-file consistency and returns errors and warnings separately. `triggers_edit validate=true` does the build and check in the same call.
5. **Save.** `map_save` rebuilds the script and minimap image when needed, validates, writes a timestamped backup of the previous file (the result names it in `backup`) and replaces the map atomically. `map_snapshot` makes a restore point before risky changes; `map_close` ends the session.
6. **Test in the game.** See [Game tests](#game-tests).

## Large batches

Generated placements and terrain passes are mechanical. Keep them out of the conversation:

- Write the ops array to a local JSON file and pass `ops_file` instead of `ops` (`placed_edit`, `terrain_edit`, `objdata_edit`, `triggers_edit`). A long trigger script can come from `script_file`.
- `placed_edit` compact rows: `{"op": "add", "kind": "destructible", "columns": ["type", "x", "y", "variation", "angle"], "rows": [["LTlt", -1833, -3653, 2, 113], ...]}`. Fields outside `columns` apply to every row.
- `placed_edit` `scatter` places random objects in one op: `{"op": "scatter", "kind": "destructible", "types": {"LTlt": 3, "LTlf": 1}, "count": 200, "rect": [l, b, r, t], "exclude": [{"x": 0, "y": 0, "radius": 1500}], "min_distance": 96, "seed": 7}`. It stays on land by default (`"where": "water"` or `"any"`), picks only variations whose model is installed, and uses the type's fixed facing or a random one. Prefer it over computing coordinates yourself.
- `placed_edit` returns `created` as ranges in op order (`"doodad:422..909"`) plus `created_count`. Refs number on in op order, per file: doodads and destructibles share `war3map.doo`; units, items and start locations share `war3mapUnits.doo`. `verbose=true` lists every ref.
- Batches of several hundred ops in one call are fine.

## Terrain

- A map spans `tiles × 128` world units centred on the origin (96×96: −6144..6144). The playable area is 12 tiles narrower and shorter and is **not** centred (a 96×96 map: `[-5376, -5632, 5376, 5120]`). `placed_list` returns both under `bounds`.
- Every `terrain_edit` op is a flat object: `{"op": "paint", "tile": "Lgrs", "x": 0, "y": 0, "radius": 384}`. A nested form such as `{"paint": {...}}` fails with `bad_op`. Areas: `"x"/"y"/"radius"`, `"rect": [left, bottom, right, top]`, `"path": [[x, y], ...]` with `"width"` (roads), or **no area** for the whole map. Do not send 50 circles for what one rect or path does.
- A map holds at most 16 ground tiles. A new map already holds its tileset's 8 tiles and 2 cliff tiles, which leaves 8 free. `terrain_get` and every `terrain_edit` result report the palette (`tiles`, `free`) and what the edit added (`palette_added`).
- `map_new` fills the map with the tileset's first tile, which is often dirt, not grass (`Ldrt` for Lordaeron Summer, `Adrt` for Ashenvale). Pass `fill_tile` and read `fill_tile` in the result: a road in the ground tile shows nothing.
- Terrain edits leave pathing (`war3map.wpm`), shadows (`war3map.shd`) and minimap icons (`war3map.mmp`) stale; only a World Editor save recomputes them. While that save is owed, `map_validate` (and so `map_save`) warns with check `derived_files`. When the warning is gone, the cycle is done.
- `terrain_render` shows tiles, height, water, regions, start locations, units, items, doodads (magenta), trees (dark green) and other destructibles (orange). Look at it before launching the editor or the game.

## Placed objects and start locations

- `map_new` places the start locations inside the playable area. Move one with `placed_edit` `{"op": "move", "ref": "start_location:N", ...}`: it also moves the player's start in `war3map.w3i` (the position the map script uses) and reports `synced`. `info_edit players[N].start` alone does not move the marker; `map_validate` warns when the two disagree.
- Useful `add` fields: `owner`, `angle`, `variation`, `acquisition: "camp"` (creep camp behaviour), `drops: {"sets": [[{"item": "phea", "chance": 100}]]}`.
- Player 24 is neutral hostile (`Player(24)` in JASS) and 27 is neutral passive.
- Objects in `war3mapUnits.doo` exist before initialization triggers run: `main()` creates them before `InitCustomTriggers` / `RunInitializationTriggers`.

## Missing models

Some doodad and destructible ids in the data files have no model in the installed game. They place without error, render nothing and make the editor print `Could not load file: ...`. Known examples: `LPgp` (Grass Patch), `LSga` (Summer Grass), `YOsp` (Spider Web), `LPwh` (Wheat), `NWfp` (Floating Plank), `LOca` (Cauldron with heads). Shipped ladder maps carry some of them too.

- `data_search` marks these results `model_ok: false`; `data_get` lists `model.files` and `model.missing`. Check `model_ok` before choosing decoration ids.
- `placed_edit` warns when it places one, and `scatter` refuses them.
- `map_validate` warns (check `model`) for every placed doodad, destructible or unit whose model is in neither the game data nor the map's imports.

## Triggers

- A `"script"` trigger runs only through the editor's `InitTrig_<script name>` function, which assigns `gg_trg_<name> = CreateTrigger()`. Send the actions alone and the tools add that wrapper (the result says what was added), or write the whole thing yourself. The script name is the trigger name with every character outside `A-Z a-z 0-9 _` turned into `_` (`gg_trg_<script name>`), so identifier-safe names keep the script readable and unambiguous.
- `run_on_init` makes a script trigger run at map start. A GUI trigger runs at map start through the event `{"fn": "MapInitializationEvent"}`.
- `validate=true` returns pjass / Lua errors straight away, each with `script_line`, its line inside the script you sent. Without it, `triggers_edit` warns that the map script is not regenerated yet; `map_save` or `script_build` regenerates it.
- `variable` ops create GUI globals, emitted as `udg_<Name>`; `array_size` makes an array. Types known to work: `integer`, `real`, `boolean`, `unit`, `leaderboard`, `timer`, `timerdialog`.
- Deleting the default `Melee Initialization` trigger removes all melee behaviour (starting units, victory and defeat), which a non-melee map needs.

## Map info and object data

- `info_edit` `set` of a whole list (`forces`, `players`) replaces it, and every element must be complete, including `unknown_flag_bits`. Read the shape from `info_get` first.
- `objdata_edit` `create` takes an explicit `id` (`"h000"`) or allocates one like the editor. `set` also works on stock ids (`hgtw`), which makes modified standard objects.
- Fields take raw codes, for example `ubui` (structures built), `ureq` (requirements), `ugol` / `ulum` (gold / lumber cost), `ubld` (build time), `umvs` (movement speed), or `Name`. Setting `ureq` to `""` removes a building's tech requirements.

## World Editor

`editor_launch`, `editor_status`, `editor_map` (open/save/reload/close/quit), `editor_menu`, `editor_dialogs`, `editor_dialog_act`, `editor_input`, `editor_screenshot`, `editor_log`.

- Take turns with the user: never discard unsaved work in the editor. `map_save` refuses while the editor has the same map with unsaved changes; ask the user first.
- The editor holds a lock on the map file whenever it shows the map, even with no unsaved changes, so `map_save` cannot replace it (`editor_holds_map`). The safe round trip is: **MCP edits → `editor_map action=close` → `map_save` → `editor_map action=open` → `editor_map action=save`**. That save recomputes pathing, shadows and minimap icons and compiles the script.
- `editor_map action=save` returns per-trigger script errors and the triggers the editor disabled. Empty `errors` and `disabled_triggers` mean the script compiled.
- `editor_map action=open` may start a new editor process; `previous_instance` says whether the running editor was reused or relaunched.
- An editor save rewrites the map file, so the next `map_save` of a working copy with its own edits fails with `source_changed`. Use `map_save merge_external=true`: it keeps the working copy's changed files and takes everything else from the map file (the recomputed pathing, shadows and minimap), then saves. `force=true` would overwrite what the editor recomputed, and `map_close discard=true` would drop your edits. `map_open merge_external=true` does the same merge when reopening. Saving the working copy **before** handing the map to the editor avoids the question.
- The editor writes its log only when it quits. `editor_log` parses the last session: `missing_files` (files it could not load), `messages`, and a count of benign ones; `note` says when a running editor makes the log stale. For missing models, use `map_validate` instead of waiting for the editor.
- `Failed to load Environment Map for tileset A` and `Referencing unknown database field: 'netsafe' / 'occlusion' / 'teamColor' ...` appear for every map. They are not map defects.

## Game tests

- `game_test` launches the map and ends as soon as every file listed in `results` exists under `Documents\Warcraft III\CustomMapData`. The map script writes such a file with `PreloadGenClear()` / `PreloadGenStart()` / `Preload("text")` / `PreloadGenEnd("mymap\\results.txt")`. A run whose files never appear lasts the full `timeout` and lists them under `missing`.
- `game_test probe=true` needs no reporting trigger of your own. It runs a throwaway copy that reports, `probe_seconds` into the game, the units, heroes, gold and lumber of every playing slot, plus the `BJDebugMsg` text (`probe.messages`). Use it to check that a map loads and runs.
- `screenshot=true` saves a PNG of the game window. When the window will not come to the front, the tools draw it from the window itself; `screenshot_of` says what was captured, or why nothing was. `focus` says how often the window was raised.
- `log` holds the useful `War3Log.txt` lines, `missing_files` the files the game could not load, and `benign_log` counts shipped-data lines such as `model creation failed - C:/Users/<builder>/Perforce/.../GuardTowerBirth.mdl`. Do not chase benign lines as map defects.
- `game_status` returns recent `War3Log.txt` lines even with no game running, including runs started from the World Editor's own test command.

## Rules

- The game loads a map only while its window is in front, and Warcraft III can show a Battle.net login first. **Never type credentials**: ask the user to log in (with "Keep me logged in") and approve any authenticator request.
- If `game_test` returns no results and `exited_early`, the login was not completed or the map failed to load: take a screenshot (`screenshot=true`) and tell the user.
- Keep a backup (`map_save` makes one) before replacing a user's map, and say which file changed.

## Common practice (not verified by the tools)

- Create leaderboards, multiboards and timer dialogs from a short timer (for example 0.1 seconds) after map start, not directly at initialization, where they may not display.
- Adding ability `Abun` (Cargo Hold) to a unit is a common way to remove its attack, for example so that creeps walk a path without fighting.
