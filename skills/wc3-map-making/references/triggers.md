# Triggers, variables and script pitfalls

## Trigger ops

- A `"script"` trigger runs only through the editor's `InitTrig_<script name>` function, which assigns `gg_trg_<name> = CreateTrigger()`. Send the actions alone and the tools add that wrapper (the result says what was added), or write the whole thing yourself. The script name is the trigger name with every character outside `A-Z a-z 0-9 _` turned into `_`, so identifier-safe names keep the script readable.
- `run_on_init` makes a script trigger run at map start. A GUI trigger runs at map start through the event `{"fn": "MapInitializationEvent"}`.
- A `trigger` op naming an existing trigger replaces its script and **keeps its position, category and `run_on_init`** (the World Editor does the same). Position matters, so change it only on purpose: `{"op": "trigger", "name": "Helpers", "index": 0}` puts a trigger first in its category, `{"after": "Core"}` puts it right after another trigger of the same category, `{"after": null}` first.
- To change a few lines of a long script, use `{"op": "script_replace", "name": "SWTest", "old": "2900.0, -500.0", "new": "2900.0, -250.0"}` (or `"header": true` for the map header) instead of resending the whole script; `old` must occur exactly once.
- `{"op": "delete", "what": "variable" | "trigger" | "category", "name": ...}` removes a global (refused while triggers use it), a trigger, or an empty category.
- Deleting the default `Melee Initialization` trigger removes all melee behaviour (starting units, victory and defeat), which a non-melee map needs.
- Long scripts and generated batches: `script_file` loads one trigger's script from a local file, `ops_file` loads the whole ops array.

## Function order

Trigger code is emitted in **trigger-tree order**, so a function can only be called from the same trigger below its definition, or from a later trigger. Put shared helpers in the first trigger of the first category.

- `map_validate` reports a call into a later trigger as an error (check `function_order`) and names the trigger to move.
- The map header is emitted before all triggers, so functions defined there are available everywhere.

## GUI variables

`variable` ops create GUI globals, emitted as `udg_<Name>`; `array_size` makes an array, and `InitGlobals` initializes indices `0..array_size` inclusive (a `dialog` array gets `DialogCreate()` for each).

- Handle types that work as globals include `unit`, `group`, `rect`, `location`, `item`, `force`, `player`, `trigger`, `timer`, `hashtable`, `fogmodifier`, `weathereffect`, `effect`, `lightning`, `texttag`, `quest`, `sound`, `destructable`, `image`, `camerasetup`, `gamecache` and `handle`, plus `integer`, `real`, `boolean`, `string`, `dialog`, `leaderboard`, `multiboard`, `timerdialog`. `data_search kind=trigger_type` lists them all.
- The editor's names differ from the JASS ones in places: a region variable is `rect`, a point is `location`, a unit group is `group`.
- `itempool`, `unitpool`, `boolexpr`, `code` and `widget` have no global in the editor: keep those in locals. `ChooseRandomItemEx(ITEM_TYPE_PERMANENT, 6)` replaces an item pool (it returns a real item id, created with `CreateItem`), and `SetPlayerAlliance(p, other, ALLIANCE_SHARED_VISION, true/false)` gives and takes full vision without a stored fog modifier.
- A `hashtable` variable starts as `null`: call `InitHashtable()` once before using it.

## JASS pitfalls

- **A JASS type name cannot be a variable or parameter name.** `function F takes integer code returns nothing` fails, because `code` is a type: pjass then reports a syntax error on the function line plus one undeclared-variable error per following declaration — 17 errors for one word, none naming the cause. `script_validate` adds a `lint` entry that names it (also without `lint=true`, whenever pjass fails).
- `exitwhen` must stand directly in the loop body. Inside an `if` block it fails with `Missing endloop` / `Missing endfunction`.
- There is no `B2S`: `I2S(IntegerTertiaryOp(flag, 1, 0))` prints a boolean. Look natives up (`data_get kind=native`) instead of guessing.
- `script_validate lint=true` reports the runtime traps a compiler cannot see, each with its line, function and trigger: leaked locations, groups, forces, rects and boolexprs, event data read after a `TriggerSleepAction`, a trigger with an action but no event, a loop without `exitwhen` or over the operation limit (about 300000 operations per thread), and a handle used after it was destroyed. They are heuristics; each firing rule is usually a game run saved.
- `validate=true` on `triggers_edit` returns pjass / Lua errors straight away, each with `script_line`, its line inside the script you sent. Without it, `triggers_edit` warns that the map script is not regenerated yet; `map_save` or `script_build` regenerates it.
- `map_save` compiles a regenerated or edited script and refuses to save when it does not compile; `validation.script` shows the result.
- Reforged natives that pass pjass and work in the game: `BlzSetUnitMaxHP`, `BlzGetUnitMaxHP`, `GetEventDamageSource`, `BlzSetEventDamage`, `BlzGetUnitAbilityCooldownRemaining`, `BlzSetAbilityResearchTooltip`, `BlzGetAbilityResearchTooltip`, `BlzGetUnitAbility`, `BlzGetAbilityStringField` / `BlzSetAbilityStringField`, and the event `EVENT_PLAYER_UNIT_DAMAGED` (with `TriggerRegisterAnyUnitEventBJ`). `BlzSetAbilityResearchExtendedTooltip` passes pjass; its effect in the game is unchecked.

## The script API of the installed build

`data_search kind=native` and `data_get kind=native` answer from this install's `common.j`, `Blizzard.j` and `common.ai`: natives, Blizzard.j functions, constants and handle types, each with its signature. Look a function up instead of remembering it — the answer matches the patch the map will run on.

- `data_get kind=native id=CreateUnit` gives `native CreateUnit takes player id, integer unitid, real x, real y, real face returns unit` plus its parameters as a list.
- `data_search kind=native query=EVENT_PLAYER_UNIT_SPELL` lists the event constants; globs work too (`Blz*Frame*`).
- A list of ids in one call works here as everywhere: `data_get kind=native id=["CreateUnit", "SetUnitX"]`.

## Custom user interface

`ui_get` reads the `.fdf` layout files a map holds (and the game's own, so the stock UI can be studied), parsed into frames with their type, name, parent and template. `ui_edit` writes one — from `statements` (the same shape) or from ready FDF text — imports it under `war3mapImported`, lists it in a `.toc` beside it and returns the script that loads it (`BlzLoadTOCFile`, then `BlzGetFrameByName` or `BlzCreateFrame`).

Both check the layout and report: a frame type the game does not know, an anchor that is not one of the nine corners, a `SetPoint` to a frame the file never defines, and a texture that is in neither the map's imports nor the game data. Each of those shows up in the game as a missing or misplaced panel, so the check is worth more than a launch.

## Systems that are the same in every map

`script_recipe` holds them, as `triggers_edit` ops that arrive compiling: `damage_detection` (one function every damage
event passes through), `unit_indexer` (a number on every unit plus a hashtable for per-unit data), `respawn` (units of
one owner come back where they died), `waves` (timed waves walking from a spawn to a target, growing each round),
`scoreboard` (a multiboard per player, refreshed on a timer), `hero_tavern` (a tavern that sells heroes and places the
bought one at its owner's start), `quest`, `camera` and `cinematic` (camera shots with spoken lines and the waits
worked out). Call it without a name to list them with their parameters; `install=true` puts the ops into the open map
and checks the script.

A recipe is a starting point for a generic system, not the map: everything specific to this map is still written by
hand as a script trigger, and a recipe's script can be edited before it goes in (it comes back in the result).
Each one declares its state as GUI variables, because a trigger script cannot declare globals of its own.

## Audio

`sound_add` does the three steps at once: import a local .wav/.mp3/.ogg/.flac (or point at one of the game's own with
`game_path`), register it in war3map.w3s under a name with the settings that kind needs (`sound`, `sound3d`, `ambient`
or `music`), and hand back the script that plays it. The handle is `gg_snd_<name>` once `map_save` or `script_build`
has regenerated the script; a 3D sound is heard where it is played, so attach it to a unit or a point.

- `kind=ambient` uses what the World Editor writes for most region ambient sounds of the shipped maps: looping 3D, `DoodadsEAX`, volume 127, channel 0, distances 0 / 10000, cutoff 3000 (quieter local loops use channel 10, volume 30-60, 600 / 2600 / 2100: pass those in `settings`). `script_build` emits `CreateSound` with `SetSoundDuration` read from the file.
- Tie it to regions with `elements_edit kind=region` `upsert` `ambient_sound` (a `gg_snd_` name); `weather` takes a weather id (`data_search kind=weather`: `LRaa` Rays Of Light, `LRma` Moonlight, `RAlr`/`RAhr` Ashenvale rain, `RLlr`/`RLhr` Lordaeron rain, `FDgl`/`FDwl` fog, `VWgr` falling leaves, `WOlw` wind, `SNls` snow). An upsert of an existing region changes only the fields it sends; `ops_file` takes dozens of regions from a local file. `CreateRegions` then emits `AddWeatherEffect` + `EnableWeatherEffect` and `SetSoundPosition` + `RegisterStackedSound` per region.
- One sound may serve many regions: 148 of the 176 region ambient sounds in the shipped maps do, and `RegisterStackedSound` plays it at each.
- Loops that fit regions: `Sound\Ambient\DoodadEffects\WaterStreamLoop1.ogg`, `WaterLakeLoop1.ogg`, `WaterWaterFallLoop1.ogg`, `LordaeronSummerFliesLoop1.ogg`, `CityscapeFountainLoop1.ogg`, `CityScapeMagicRunesLoop1.ogg`; each tileset has day and night ambience too (`Sound\Ambient\SunkenRuins\WetlandsDay.ogg`).

- A custom-script trigger runs through `InitTrig_<name>`, which the tools add. It registers `Trig_<name>_Actions` when the script defines it, else the first function that **takes nothing**; a script of helpers that all take parameters is treated as a library and gets an `InitTrig` that only creates the trigger (registering a function with parameters fails pjass).
