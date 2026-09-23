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
| The Battle.net desktop app, logged in (for `game_test` only) | A game started on its own has no Battle.net session and asks for a login. `game_test` therefore lets the app start the game, the way its Play button does, and the app hands the game its own session. Log in to the app once yourself with "Keep me logged in"; the tools never type, read or store credentials. The first run stores the map's path in the app's launch options for Warcraft III and restarts the app once; without the app, `game_test` flashes the game window and waits for you to log in there. |

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

## What's new in 1.5

From the arena map's phases 6-7 and two playtests.

- **`game_test` gives the user's launcher back.** Every run - however it ends - puts the Battle.net app's launch
  options back and deletes the launch copy; before, a Play in the app started the last tested map in a window.
  `game_status` reports what a Play would start today, and `game_close` restores after a crashed run.
- **Shops.** `objdata_edit` no longer calls `isto` 0 "unlimited" (it means never in stock) and warns on it;
  `map_validate` reports `shop_stock`, `shop_hotkey` and `icon` (a path the game does not have), and
  `balance_report kind="shop"` reads a whole shop card with what stops each purchase.
- **Order strings.** `data_search kind=order` says whether a shipped ability uses a string (`backed`) and whether
  the game resolved it (`resolves`); `map_validate` reports `channel_order` for a Channel on a string `OrderId`
  does not know, and `channel_levels` for a Channel with no button at some ranks. A game test sweeps every string.
- **Object data.** `upsert`, `quiet=["extended_levels"]`, buttons off the card (`arpy` -11), the classic-graphics
  default the World Editor compares art fields with, and `learn_card` for hero abilities on one learn-menu cell.
- **`game_test probe_init`** runs at map initialization, before any dialog; `ProbeSkipDialogs()` keeps dialogs shut.
- **`data_get kind=native`** carries `observed`: what the game was seen to do where a native's name promises more.
- Smaller: globs for every `data_search` kind (`kind=sound query="*"`), `placed_list type` (one or a list), `.mdl`
  paths resolve in `data_get`, `button_cells` over every ability, `wc3_batch` calls inherit `path`, a snapshot
  without a label names the parameter, and `ui_edit` writes a `.toc` the game can load.

## What's new in 1.4.1

The live World Editor calibration, which 1.4 left open, has run. It confirmed the 1.3 cliff rule - the editor
rewrote none of the levels `terrain_edit` settles - and found one defect in the derived pathing.

- **A cell counts as deep water only where its shallowest point is deep.** The tools judged a cell by the water
  depth at its centre, the editor by the cell's shallowest point, so a sloping shore came back one cell narrower
  than the game has it. Against an editor-saved `war3map.wpm` that took the disagreement from 0.58 % of the cells
  to 0.05 %, with the deep-water threshold unchanged.
- **`editor_map action="save"` answers the Reminder box** a map still named "Just another Warcraft III map" gets on
  every save. It used to wait for that box to close by itself, which hung the save until its timeout.

## What's new in 1.4

The rest of the map-session feedback that 1.3 started.

- **Doodads and destructibles with a fixed rotation** (`dfxr`/`bfxr`) now stand and path at that angle, as the World
  Editor and the game do. Gates and trees no longer leave slits that only existed in the tools' own footprint.
- **`mirror` refuses an image that overlaps its source**, and `axis: "rot4"` fills the other three quadrants from one
  untouched quadrant.
- **A brush area narrower than the 128-unit corner spacing** snaps to the nearest corner line (result: `snapped`)
  instead of failing.
- **`map_flow` warns while the terrain pathing it used is derived**, and `layout_check` reports `narrowest`: the
  tightest gap on the walk between two start locations.
- **Scenery says what it blocks.** `data_search` carries `pathing` and `blocks` per doodad and destructible;
  `scatter` and `cluster` warn about blocking types, and `cluster` warns when it places fewer than `count`.
- **`data_get`** lists field names that matched nothing under `unknown_fields`, and finds an icon or model by its
  bare name (`BTNChainLightning`).
- **`data_search kind=order`**: every order string with its targeting and the abilities that use it.
- **Per-level values from a line or a list**: `{"from": a, "step": s}`, `{"from": a, "to": b}`, `[v1, v2, ...]`, and
  a text field from `{"template": "... {Htb1} ... {level} ..."}` rendered per level from the object's own values.
- **`objdata_edit` warns** about a lowercase hero copy and about more than 5 abilities in `uhab`; the `isit` range
  error names the unlimited-stock shape.
- **`map_validate`** gains `hero_id_case`, `hero_ability_slots`, `hero_skill_points`, `channel_target` and
  `waygate_self`; **`balance_report kind="ability"`** lists abilities sharing a command-card cell.
- **A map with no triggers stays workable**: the Triggers section is put back instead of `not_editor_script`, and
  deleting the last trigger warns.
- **`damage_detection` handles the event as a condition**, inside the damage call; new lint rules cover effect
  leaks, corpses in group enumerations, item-event re-entry and damage handlers registered as actions.
- **Probes write their report at the end** (a `PreloadGenClear()` in probe code no longer loses it) and every run
  reports `handles`, with `ProbeHandleCount()` for sampling around a loop.
- **`editor_map action=quit force=true`** ends an editor stuck in a long operation; **`map_status`** reports file
  sizes and custom/modified object counts per kind.

## What's new in 1.3

- **Cliff steps settle themselves.** The World Editor keeps neighbouring corners (diagonals included) at most 2 cliff
  levels apart and rewrites anything steeper when it loads a map. `terrain_edit` now does it first: an op's own
  corners keep the level asked for, the ground around them steps, and the result reports `cliffs` per op. A carved
  corridor keeps its full width, a 2-tile doorway stays open, and what the tools read is what the editor keeps.
  Terrain written by an older version is lowered to valid steps on the next edit, with a warning.
- **Profile sections match ids whatever their case**, so `Ycgd`'s model (section `[YCgd]`) is found and `model_ok`
  tells the truth.
- **`constants_get`** takes `query` (over keys and the editor's display names) and returns keys it does not know
  under `unknown` beside the ones it answered.
- **A library custom script** gets an `InitTrig` that only creates the trigger, instead of registering a function
  that takes parameters (which fails pjass).

## What's new in 1.2

- **Game tests no longer ask for a Battle.net login.** The game started on its own (`Warcraft III.exe -launch -loadfile ...`) has no session, and signing the Battle.net app in does not give it one - which is why 1.1's sign-in did not help. `game_test` (`login="auto"`) now has the **app itself start the game**, the way its Play button does (`-launch -uid w3`), and the app hands the game its own session: no login screen, and no password read, typed or stored anywhere. The map is copied to one fixed path inside the server's folder and that path is stored in the app's launch options for Warcraft III, so only the first run has to restart the app; the copy is removed when the run closes the game. Verified live: from `--exec=launch W3` to the map's loading screen in 13 s, `login.screen_seen: false`. The app has to be logged in once, with "Keep me logged in".
- **`constants_get` / `constants_edit`**: the World Editor's Gameplay Constants (`war3mapMisc.txt`) as a typed tool - the hero level cap, the experience formula, `HeroAbilityLevelSkip`, revive costs, illusion and aura rules. Every key the game defines with its default and where it comes from; a misspelt key is refused instead of silently ignored, and `map_validate` warns about one already in a map.
- **More ability ranks now carry values.** Raising `alev` above the base ability's own level count used to leave every per-level field at the base's ranks; `objdata_edit` repeats the last value into the new ranks, as the World Editor does, and reports what it filled in (`extended_levels`).
- `objdata_edit` accepts the numeric strings `data_get` hands back (`"0"`, `"600.5"`), and `null` clears a field or one of its levels - there was no way to unset `aubx` before.
- **`balance_report` reads a hero as a hero**: life, mana, armour and damage computed from `ustr`/`uagi`/`uint` and the gameplay constants at level 1 and at the level cap, and compared with the stock heroes instead of Peasants (every hero's unit fields say life 100, mana 0, damage 2).

## What's new in 1.1

- **No more logins by hand for game tests** (usually): when the game shows the Battle.net login screen, `game_test` (`login="auto"`) closes it, starts the game once through the Battle.net desktop app - which signs it in with the app's own remembered login, no credentials involved - and runs the map again. When that is not possible it flashes the game window, plays a warning sound and waits `login_wait` seconds for you, then carries on in the same call. `login="wait"`, `"battlenet"` and `"stop"` pick one behaviour. A game that lands on its main menu instead of the map after a login is started again (`relaunched`).
- **Deep water is unwalkable** in every walkability the tools compute (terrain pathing, `terrain_render pathing=true`, `map_flow`, `layout_check`, `map_validate reachable`): deeper than about 53, measured against the editor's own pathing on the shipped maps (flat water up to 51.95 deep is always walkable there, from 56.4 never). Water heights are now right on every tileset: Ashenvale, Underground, Dungeon and Outland draw their water at their own offset (Outland water is never walkable).
- **`map_flow origins/targets`**: can a unit walk from these points, regions or start locations to those, on the game's 32-unit pathing cells, with every placed object's footprint turned the way the editor turns it? `sealed: true` proves a tree wall, a moat or a cliff ring closed; a leak comes back with the gap and where it is.
- The `river` brush put its water 89.6 too low and ignored cliff levels; it now takes `water_level`, joins standing water at its level, keeps a promise with `walkable: false` (a channel units cannot wade) or `true` (a ford), and reports the depths it made. `coast` had the same bug and is fixed; every water op reports its stored level and depth range.
- `game_test screenshots=N` works while the map runs (the series used to start on a log line the game writes late, so it was empty in real runs); it starts at the probe's start marker and lists frames it could not take with the reason.
- `terrain_render area` draws only that part of the map (up to 16 px per tile) and says which rectangle it drew; a heightmap export now returns its `base` and `amount`.
- `elements_edit`, `info_edit` and `strings_edit` take `ops_file`; `terrain_edit quiet` silences the unbuildable-tile or stale-files warnings on a scenery map.
- `layout_check` says why objects stand on bad ground, per kind: deep or shallow water, cliff, boundary, unwalkable tile, outside the playable area.
- `sound_add kind=ambient` uses the settings the World Editor writes for region ambience (`DoodadsEAX`, volume 127, distances 0/10000/3000); one sound may serve many regions, as it does in the shipped maps.
- `map_snapshot restore` no longer marks every file dirty; `placed_edit` accepts a scale within 0.01 of a fixed-scale type; `data_get kind=ability` names the order string the game accepted for the three abilities checked in the game.

## What's new in 1.0

**Ground, shaped like ground.** `terrain_edit` gained the landscape brushes: `river` (a bed deepest in the middle, water in it, banks painted), `coast` (floods under a waterline, slopes the sea floor, lays a beach band), `ridge`, `erosion` (thermal, so hills stop looking like cones), `terrace`, `blend` (a speckled tile seam) and `stamp` (copy a patch, rotated or mirrored).

**Symmetry.** `mirror` on both `terrain_edit` and `placed_edit`: build one half or quadrant, then reflect or rotate it, facings turned and, with `owner_map`, the copies handed to another player.

**Heightmaps.** A picture over an area goes in (`{"op": "heightmap", ...}`, any Pillow format, any channel, set or add) and `terrain_render heightmap="height"|"cliff"|"water"` writes a 16-bit PNG back out over the same corner window.

**Does it play?** `map_flow` gives walking distances between starts, to mines and expansions, the narrowest choke on each route and the pockets nobody reaches on foot. `melee_check` measures the map the way the 272 melee maps shipped with the game are measured and reports every metric against their p10, median and p90 for the same player count. `balance_report` computes damage per second, effective life and cost efficiency from the object fields and flags a custom object far outside what the stock objects of the same price show.

**Systems and text.** `script_recipe` holds nine tested JASS systems as `triggers_edit` ops (damage detection, unit indexer, respawn, waves, scoreboard, hero tavern, quest, camera, cinematic), each compiled with pjass by the tests. `strings_get` / `strings_edit` read and write the string table, including a `replace` that renames one thing everywhere and an `import` for a translated table. `sound_add` imports audio, registers it in `war3map.w3s` and hands back the script that plays it.

**Cheaper calls.** `wc3_batch` runs up to 20 tools in one round trip. `wc3_help(topic)` holds the op catalogues the tool descriptions used to carry (32.6 KB of descriptions down to 27 KB, with sixteen reference pages a caller asks for when it needs them). `terrain_get format="runs"` packs rows into `[value, count]` pairs and `format="summary"` answers with ranges and counts: a whole map's three layers go from 48 KB to 36 KB or 1 KB.

**Tests in the game.** `ProbeStartAI` gives an empty slot a melee AI, so a run has an opponent, and `ProbeGold` pays for what the test builds.

There are deliberately **no map templates**: the tools are pieces to compose for the map someone actually asked for, and the skill's `references/building-a-map.md` is the order to compose them in.

## What's new in 0.9

- **Scenery that looks placed.** `placed_edit` gained generator ops that build a layout instead of a heap, with Poisson-disk spacing: `forest` (density from noise, thinning toward the edge and around clearings, kept to the right tiles), `line` (even spacing along a path, with offset, sides and facing), `town` (a row of buildings along every block side facing its street, props between them, streets returned for `terrain_edit` to pave), `cluster` (dense in the middle, objects shrinking to the rim) and `clear` (empty an area first).
- **`layout_check`** reports what a top-down picture cannot show: nearest-neighbour spacing with its spread (a grid stamp is near 0, hand-placed work 0.15-0.45), objects on water or on ground no unit can stand on, the tiles they ended up on, and how much of the walkable map the start locations still reach.
- **`game_test screenshots=N`** saves a series of pictures while the map runs, and the probe helper `ProbeCamera(x, y, distance, seconds)` walks the camera over the scenery, so the result can be looked at in the game.
- **`data_search` / `data_get kind=native`** answer from the installed build's `common.j`, `Blizzard.j` and `common.ai`: natives, functions, constants and handle types with their signatures.
- **`ui_get` / `ui_edit`** read and write custom UI: `.fdf` layouts (the game's own included), the `.toc` beside them and the loader script, with a check for unknown frame types, bad anchors, a `SetPoint` to a frame that does not exist and missing textures.
- **`objdata_diff`** shows what a batch changed against the map on disk or a snapshot, field by field.
- **`map_validate`** gained `ability_order` (two abilities of one unit sharing an order string) and `reachable` (start locations cut off from each other, or a preplaced unit its own player cannot walk to).
- **`script_validate lint=true`** gained a desync rule: game state changed, or a random number drawn, inside a `GetLocalPlayer()` block.
- **`ProbeExpect(name, condition)`** records pass/fail checks, so a test run answers with a verdict (`probe.checks`, `checks_failed`) instead of text.
- `terrain_render write_preview=true` writes `war3mapPreview.tga`, the picture the map list shows.

## What's new in 0.8

- Fewer, smaller calls: `data_get` and `objdata_get` take a **list of ids** and answer compactly (raw code -> value, empty fields left out, about a tenth of the size); `verbose=true` brings back the field metadata.
- `game_test wait=false` runs the test in the background and returns at once: `game_status` reports the run and its whole result when it ends, so the map can be edited while a long probe runs.
- `script_validate lint=true` reports the runtime traps pjass cannot see: leaked handles, event data read after a wait, a trigger with an action but no event, endless or operation-limit loops, a handle used after it was destroyed, and a local or parameter named after a JASS type (the cause of a pile of misleading pjass errors).
- Replacing a trigger keeps its position in its category, so the triggers after it still see its functions; `index` and `after` move one on purpose, and `map_validate` reports a call into a later trigger (`function_order`).
- `data_get kind=ability` returns an `orders` block with the ability data's order, the World Editor's presets and their targeting, and `disagree: true` for the ~15 abilities where only one of the two works; `map_validate` warns when a script issues one of those or an order string nothing knows (`order_string`).
- The variable-type error names the editor's own name for a handle type (`rect` for a region, `location` for a point) and what to use instead where the editor has no global (`itempool`, `code`, `boolexpr`).
- The skill is split into a short core plus `references/*.md` loaded on demand, so a session starts with about 6 KB instead of 34 KB of skill text.
- The tool log records the result size in bytes and the duration of failed calls too.

## What's new in 0.7

- Probes observe more: `ProbeCountEvent` / `ProbeEventCount` count player-unit events, `probe_functions` adds your own callback functions, and `probe.messages` includes text shown with `DisplayTextToPlayer`, `DisplayTimedTextToPlayer` and the force variants.
- `map_validate` warns about object data pitfalls: `command_card` (buttons sharing a position, including Rally and Cancel), `inherited_builds` (a copied worker that keeps its base's build list) and `locked_ability` (a required research nothing in the map offers).
- `terrain_get` snaps an area narrower than the corner spacing to the nearest corner line (`window.snapped`).
- `terrain_render` gives tree marks a light rim so they show on dark grass.

## What's new in 0.6

- `game_test` after `login_required`: once the user has logged in, the same call continues in the game left open instead of launching again. Each probe run gets its own copy, so an open game never blocks the next run.
- Terrain buildability: `data_search kind=tile` gives `buildable`, `walkable` and `flyable`; `terrain_edit` warns when it paints an unbuildable or unwalkable tile over an area; `terrain_get` pathing and `terrain_render pathing=true` show pathing derived from the current terrain before an editor save.
- `objdata_edit create` copies a custom object when `base` is one of the map's custom ids.
- `objdata_get` checks the model the map sets (`umdl`, `dfil`, `bfil`) instead of the base model.
- `data_get kind=tile` honours `fields`; file globs match without the storage layer prefix (`PathTextures/8x8*`).

## What's new in 0.5

- `game_test probe_script` can call the map's own trigger functions: the probe trigger now comes after all map triggers.
- `game_test` presses a key on a loading screen that waits for one (maps with loading-screen text), and ends a run stuck on the Battle.net login screen after about 30 seconds with `login_required`, leaving the game open for the user.
- `game_test` returns Preload strings unescaped, and a run without results hints that an open dialog pauses a single-player game.
- `objdata_get` sizes `levels` by the map's own `alev`/`glvl` and lists values beyond it as `unused_levels`.
- `data_search kind=icon|model|file` returns one result per file with `ref` (the object-data path, `.blp` icons and `.mdl` models) and its storage `layers`.

## What's new in 0.4

- Model checks cover classic graphics, which the World Editor uses: HD-only files such as `ZPsh` variation 3 no longer pass as present, and `data_search` lists the `variations_ok` of a partly usable type.
- `placed_edit` warns when a doodad or destructible scale is outside its type's minimum and maximum, which the World Editor clamps on save.
- `triggers_edit` `script_replace` changes one exact piece of a script trigger or the map header without resending the script.
- `map_save` compiles a regenerated or edited map script and refuses to save when it does not compile (`validation.script`).
- `game_test probe_script` runs caller test code in the throwaway probe copy, with `ProbeReport(text)` for reports of any length; result lines at the Preload length limit are listed under `truncated`.
- Stock unit `Solid texture substituted` log lines count as benign.
- `objdata_edit` refuses op keys it does not know (a misspelt `set` no longer drops the values silently).

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

## License

MIT, see [LICENSE](LICENSE). Free to use, change and share, for personal projects and others.
Warcraft III and its game data belong to Blizzard Entertainment; this project reads a local install and ships none of it.
