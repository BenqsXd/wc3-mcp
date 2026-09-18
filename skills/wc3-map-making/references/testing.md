# Game tests and the World Editor

## game_test

- The run ends as soon as every file listed in `results` exists under `Documents\Warcraft III\CustomMapData`. The map script writes such a file with `PreloadGenClear()` / `PreloadGenStart()` / `Preload("text")` / `PreloadGenEnd("mymap\\results.txt")`. A run whose files never appear lasts the full `timeout` and lists them under `missing`.
- `probe=true` needs no reporting trigger of your own. It runs a throwaway copy that reports, `probe_seconds` into the game, the units, heroes, gold and lumber of every playing slot, plus the text the map shows (`probe.messages`). Use it to check that a map loads and runs.
- `probe_script` (or `probe_script_file`) adds statements in the map's language (JASS locals first) that run in the throwaway copy at `probe_seconds`. They can call the map's own functions (the probe trigger comes after all map triggers), read its `udg_` globals and wait with `TriggerSleepAction` (700 s of waits in one probe worked). `ProbeReport(text)` writes text of any length, returned in `probe.reports` in order. One run can hold a whole balance simulation, reporting when the round changes. A probe that does not compile ends the call before the game starts (`probe_script_failed`).
- `probe_functions` adds whole functions (callbacks for your own triggers) before the probe code, and `ProbeCountEvent(EVENT_PLAYER_UNIT_CONSTRUCT_START, "starts")` / `ProbeEventCount("starts")` count a player-unit event without a callback of your own:
  ```
  call ProbeCountEvent(EVENT_PLAYER_UNIT_CONSTRUCT_START, "starts")
  call IssueBuildOrderById(builder, 'h000', 900, -300)
  call TriggerSleepAction(8)
  call ProbeReport("starts=" + I2S(ProbeEventCount("starts")) + " gold=" + I2S(GetPlayerState(Player(0), PLAYER_STATE_RESOURCE_GOLD)))
  ```
- `probe.messages` holds the text of `BJDebugMsg`, `DisplayTextToPlayer`, `DisplayTimedTextToPlayer`, `DisplayTextToForce` and `DisplayTimedTextToForce`. The real map never gets test triggers, so there is nothing to remove before shipping.
- **`wait=false` starts the run in the background** and returns at once; `game_status` then reports it under `run` (`state`, `seconds`, which result files it has) and, when it ends, its whole result under `run.result`. The probe runs on a throwaway copy, so the working copy is free meanwhile: write the next trigger or edit object data while a long simulation runs, instead of idling. A second `game_test` while one run is going is refused (`run_active`); `game_close` ends it.
- The game keeps about 259 characters of one `Preload` string and silently drops the rest. `game_test` lists result lines that reach that length under `truncated`. Split long reports into several `Preload` calls, or use `ProbeReport`. Result strings come back unescaped (single backslashes).
- A run that writes its result file ends as soon as the file exists: 34–124 seconds in practice, most of it launch and map load (probes with 160, 415 and 700 s of waits took 189, 469 and 776 s).
- An open dialog pauses a single-player game, so a map that shows a dialog early (a hero draft) never reaches a later `probe_seconds` or test timer on its own. Run the test code before the dialog opens (`probe_seconds` 0.3 worked). A timed-out run's hint mentions this; `screenshot=true` shows the dialog.
- A map with `loading_screen` `title`, `subtitle` or `text` waits on "PRESS ANY KEY TO CONTINUE" after loading. `game_test` presses space when it sees that screen and reports `loading_screen_keys`.
- To capture the hero learn menu: in the test code, `SelectUnit(h, true)`, `TriggerSleepAction(0.5)`, `ForceUIKey("O")`, then report; `screenshot=true` captures it. A user click in the game window meanwhile changes what is captured.
- `screenshot=true` saves a PNG of the game window. When the window will not come to the front, the tools draw it from the window itself; `screenshot_of` says what was captured, or why nothing was. `focus` says how often the window was raised.
- `log` holds the useful `War3Log.txt` lines, `missing_files` the files the game could not load, and `benign_log` counts shipped-data lines such as `model creation failed - C:/Users/<builder>/Perforce/.../GuardTowerBirth.mdl` or `Solid texture substituted - Units\_skeletons\Gore_Diffuse.tif`. Do not chase benign lines as map defects.
- `game_status` returns recent `War3Log.txt` lines even with no game running, including runs started from the World Editor's own test command. `War3Log.txt` is buffered, so it says little about a run that is still going.

## Logins

- **Every new launch can hit the Battle.net login screen.** Two sessions in a row needed a login on roughly every second launch (6 launches: none, login, continued, none, login, continued), and the user may not be able to log in again and again.
- `game_test` recognises the login screen and returns `login_required: true` after about 30 seconds, leaving the game open. Ask the user to log in there, then call `game_test` again with **the same arguments**: it continues in that game (`continued_game: true`) instead of launching a new one. A different test closes that game and launches again.
- So: put all checks of a session into as few runs as possible, use `script_validate lint=true` before launching (each rule that fires is usually a run saved), and use `wait=false` to keep working while a long run goes.
- **Never type credentials.** Ask the user to log in (with "Keep me logged in") and to approve any authenticator request.

## World Editor

`editor_launch`, `editor_status`, `editor_map` (open/save/reload/close/quit), `editor_menu`, `editor_dialogs`, `editor_dialog_act`, `editor_input`, `editor_screenshot`, `editor_log`.

- Take turns with the user: never discard unsaved work in the editor. `map_save` refuses while the editor has the same map with unsaved changes; ask the user first.
- The editor holds a lock on the map file whenever it shows the map, even with no unsaved changes, so `map_save` cannot replace it (`editor_holds_map`). The safe round trip is: **MCP edits → `editor_map action=close` → `map_save` → `editor_map action=open` → `editor_map action=save`**. That save recomputes pathing, shadows and minimap icons and compiles the script.
- `editor_map action=save` returns per-trigger script errors and the triggers the editor disabled. Empty `errors` and `disabled_triggers` mean the script compiled.
- `editor_map action=open` starts the editor with the map: an editor that shows another map, or none after `close`, is quit and relaunched (`previous_instance: "relaunched"`). Only an editor already showing that map is reused.
- `map_open` of a map whose working copy has no unsaved edits reloads it after an editor save (`source_changed` becomes `false`).
- An editor save rewrites the map file, so the next `map_save` of a working copy with its own edits fails with `source_changed`. Use `map_save merge_external=true`: it keeps the working copy's changed files and takes everything else from the map file (the recomputed pathing, shadows and minimap), then saves. `force=true` would overwrite what the editor recomputed, and `map_close discard=true` would drop your edits. Saving the working copy **before** handing the map to the editor avoids the question.
- The editor writes its log only when it quits. `editor_log` parses the last session: `missing_files`, `messages` and a count of benign ones; `note` says when a running editor makes the log stale. For missing models, use `map_validate` instead of waiting for the editor.
- `Failed to load Environment Map for tileset A` and `Referencing unknown database field: 'netsafe' / 'occlusion' / 'teamColor' ...` appear for every map. They are not map defects.
