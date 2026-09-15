---
name: wc3-map-making
description: Use when the user wants to create, edit, inspect, validate or test a Warcraft III map, campaign, AI or model/texture asset, or drive the Warcraft III World Editor or game, through the wc3 MCP tools.
---

# Warcraft III map making with the wc3 tools

The `wc3` MCP server works on real map files (`.w3x`/`.w3m`, map folders, `.w3n` campaigns). Game data comes read-only from the local Warcraft III install.

## Workflow

1. **Open or create.** `map_open` copies the map into a private working copy; `map_new` creates a new melee-ready map (JASS or Lua) and opens it. Edits touch only the working copy.
2. **Look things up.** `data_search` / `data_get` find unit, ability, item, buff, upgrade, doodad, destructible, tile, sound and trigger-function ids. Never guess ids.
3. **Edit with the typed tools.**
   - Map info and imports: `info_get`, `info_edit`, `imports_edit`.
   - Object data: `objdata_list`, `objdata_get`, `objdata_edit`.
   - Triggers: `triggers_tree`, `trigger_get`, `triggers_edit`. GUI triggers run at map start through the `MapInitializationEvent` event; `run_on_init` is for script triggers only.
   - World: `terrain_get`, `terrain_edit`, `terrain_render` (look at the render), `elements_list`/`elements_edit` (regions, cameras, sounds), `placed_list`/`placed_edit` (units, items, doodads).
   - Campaigns: `campaign_new`, `campaign_get`, `campaign_edit`. AI: `ai_get`, `ai_edit`, `ai_export`. Assets: `asset_info`, `asset_convert`, `asset_edit`, `asset_preview`.
   - `map_file_read` / `map_file_write` are raw escape hatches; prefer the typed tools.
4. **Check.** `script_build` regenerates `war3map.j`/`war3map.lua`; `script_validate` runs pjass/JassHelper or the Lua checker; `map_validate` checks cross-file consistency.
5. **Save.** `map_save` rebuilds the script and minimap when needed, validates, backs up the original and replaces it atomically. `map_snapshot` makes a restore point before risky changes; `map_close` ends the session.
6. **Test in the game.** `game_test` runs the map and returns the Preload result files the map script writes (`PreloadGenEnd("mymap\\results.txt")`), the useful log lines and an optional screenshot. `game_status` / `game_close` manage the run.

## World Editor

`editor_launch`, `editor_status`, `editor_map` (open/save/reload/close), `editor_menu`, `editor_dialogs`, `editor_dialog_act`, `editor_input`, `editor_screenshot`, `editor_log`.

- Take turns with the user: never discard unsaved work in the editor. `map_save` refuses while the editor has the same map with unsaved changes; ask the user first.
- Open and save a map in the editor to let it recompute pathing, shadows and minimap icons.

## Rules

- The game only loads a map while its window is in front, and Warcraft III can show a Battle.net login first. **Never type credentials**: ask the user to log in (with "Keep me logged in") and approve any authenticator request.
- If `game_test` returns no results and `exited_early`, the login was not completed or the map failed to load: take a screenshot (`screenshot=true`) and tell the user.
- Keep a backup (`map_save` makes one) before replacing a user's map, and say which file changed.
