---
name: wc3-map-making
description: Use when the user wants to create, edit, inspect, validate or test a Warcraft III map, campaign, AI or model/texture asset, or drive the Warcraft III World Editor or game, through the wc3 MCP tools.
---

# Warcraft III map making with the wc3 tools

The `wc3` MCP server works on real map files (`.w3x`/`.w3m`, map folders, `.w3n` campaigns). Game data comes read-only from the local Warcraft III install.

If a parameter or op named here is missing from the tool definitions you see (for example `ops_file`, `script_replace` or `probe_script`), the session still holds an older version of the tools: ask the user to reconnect the `wc3` server (`/mcp`) or start a new session instead of working around it.

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
- `placed_edit` `scatter` places random objects in one op: `{"op": "scatter", "kind": "destructible", "types": {"LTlt": 3, "ATtr": 1}, "count": 200, "rect": [l, b, r, t], "exclude": [{"x": 0, "y": 0, "radius": 1500}], "min_distance": 96, "seed": 7}`. It stays on land by default (`"where": "water"` or `"any"`), picks only variations whose model is installed, and uses the type's fixed facing or a random one. Prefer it over computing coordinates yourself.
- `placed_edit` returns `created` as ranges in op order (`"doodad:422..909"`) plus `created_count`. Refs number on in op order, per file: doodads and destructibles share `war3map.doo`; units, items and start locations share `war3mapUnits.doo`. `verbose=true` lists every ref.
- Batches of several hundred ops in one call are fine.

## Terrain

- A map spans `tiles × 128` world units centred on the origin (96×96: −6144..6144). The playable area is 12 tiles narrower and shorter and is **not** centred (a 96×96 map: `[-5376, -5632, 5376, 5120]`). `placed_list` returns both under `bounds`.
- Every `terrain_edit` op is a flat object: `{"op": "paint", "tile": "Lgrs", "x": 0, "y": 0, "radius": 384}`. A nested form such as `{"paint": {...}}` fails with `bad_op`. Areas: `"x"/"y"/"radius"`, `"rect": [left, bottom, right, top]`, `"path": [[x, y], ...]` with `"width"` (roads), or **no area** for the whole map. Do not send 50 circles for what one rect or path does.
- Brushes known to work: `paint`, `noise` (`amount`, `seed`, `falloff`; over the whole map or a `rect` for gentle hills), `plateau` (a circle flattened to the height of its centre corner) and `cliff` (`{"op": "cliff", "rect": [...], "level": 3, "cliff": "CLgr"}` raises the rect one level). A new map's ground is cliff level 2 with height 0.
- **Buildability.** Every tile is buildable or not, walkable or not: `data_search kind=tile` results carry `buildable`, `walkable` and `flyable`. Unbuildable tiles that look like a good plaza or build zone: `Ybtl` Brick, `Yblm` Black Marble, `Ywmb` White Marble, `Ysqd` Square Tiles, `Lrok` Rock. Buildable: `Ldrt`, `Ldro`, `Ldrg` and the grass tiles. A player's build order (`IssueBuildOrderById`) on an unbuildable tile silently does nothing, while `CreateUnit` still places a structure there, which hides the problem from computer-built bases. Check the flags before painting build zones; `terrain_edit` warns when a batch paints an unbuildable or unwalkable tile over more than a few corners.
- `terrain_get layers=["pathing"]` and `terrain_render pathing=true` show pathing before an editor save: after `terrain_edit` they derive it from the current tiles, cliffs, water and blight (without doodad or building footprints; `pathing_source` says which source was used).
- A map holds at most 16 ground tiles. A new map already holds all of its tileset's tiles plus 2 cliff tiles: Ashenvale (`A`) 8 tiles (8 free), Lordaeron Summer (`L`) 6 tiles, `Ldrt, Ldro, Ldrg, Lrok, Lgrs, Lgrd` (10 free). `terrain_get` and every `terrain_edit` result report the palette (`tiles`, `free`) and what the edit added (`palette_added`).
- `map_new` takes sizes from 32 to 480 in steps of 32. It fills the map with the tileset's first tile, which is often dirt, not grass (`Ldrt` for Lordaeron Summer, `Adrt` for Ashenvale). Pass `fill_tile` and read `fill_tile` in the result: a road in the ground tile shows nothing.
- `data_search kind=tile` results carry `tileset` and `tileset_name`; `query="Ashenvale"` finds that tileset's tiles by name.
- Terrain edits leave pathing (`war3map.wpm`), shadows (`war3map.shd`) and minimap icons (`war3map.mmp`) stale; only a World Editor save recomputes them. While that save is owed, `map_validate` (and so `map_save`) warns with check `derived_files`. When the warning is gone, the cycle is done.
- `terrain_render` shows tiles, height, water, regions, start locations, units, items, doodads (magenta), trees (dark green) and other destructibles (orange). Look at it before launching the editor or the game.

## Placed objects and start locations

- `map_new` places the start locations well inside the playable area (64×64 and 96×64, 4 players: `(±1632, 1376)` and `(±1632, -1888)`; 8 players: a ring of radius about 2336 around `(0, -256)`). Move a start location with `placed_edit` `{"op": "move", "ref": "start_location:N", ...}`: it also moves the player's start in `war3map.w3i` (the position the map script uses) and reports `synced`. `info_edit players[N].start` alone does not move the marker; `map_validate` warns when the two disagree. A 96×64 map's playable area is `[-5376, -3584, 5376, 3072]`.
- Useful `add` fields: `owner`, `angle`, `variation`, `scale`, `acquisition: "camp"` (creep camp behaviour), `drops: {"sets": [[{"item": "phea", "chance": 100}]]}`.
- The World Editor clamps a doodad's or destructible's scale to its type's minimum and maximum (`dmis`/`dmas`, `bmis`/`bmas`) when it saves: `ZPsh` placed at 1.55 reads back as 1.2. `placed_edit` warns when a scale is out of range. For bigger objects, create a custom type with a higher maximum (`objdata_edit`) and place that.
- Placed-object refs stay stable across a World Editor save: the same ref still names the same object.
- Player 24 is neutral hostile (`Player(24)` in JASS) and 27 is neutral passive.
- Objects in `war3mapUnits.doo` exist before initialization triggers run: `main()` creates them before `InitCustomTriggers` / `RunInitializationTriggers`.

## Missing models

Some doodad and destructible ids in the data files have no model in the installed game. They place without error and render nothing in the game; the World Editor prints `Could not load file: ...` and draws a green-and-black checkerboard cube. Known examples: `LPgp` (Grass Patch), `LSga` (Summer Grass), `YOsp` (Spider Web), `LPwh` (Wheat), `NWfp` (Floating Plank), `LOca` (Cauldron with heads). Shipped ladder maps carry some of them too.

The World Editor draws classic (SD) models, and some HD models have no classic copy: `ZPsh` (Shrub) variation 3 and `LCss` (Statue Sword) exist only in HD, so the editor cannot load them although the HD game can. The tools check both graphics modes.

- `data_search` marks these results `model_ok: false`, and `variations_ok` lists the variations that do load (`ZPsh`: `[0, 1, 2]`). `data_get` lists `model.files` and `model.missing`. Check `model_ok` before choosing decoration ids.
- `placed_edit` warns when it places one (per variation), and `scatter` uses only the variations that load.
- `map_validate` warns (check `model`) for every placed doodad, destructible or unit whose model loads from neither the game data nor the map's imports.
- Walk-through plant doodads that load on Lordaeron Summer: `ZPsh` Shrub (variations 0–2), `APct` Cattail, `LPcr` Corn, `ZPfw` Flowers, `ZPf0` Tulips. `XOcl` Magical Lantern, `LTlt` Summer Tree Wall and `YTct` Cityscape Summer Tree Wall also load. `LTlt` is the only tree of Lordaeron Summer (`data_search kind=destructible query=Tree tileset=L` lists it and two tree bridges).

## Triggers

- A `"script"` trigger runs only through the editor's `InitTrig_<script name>` function, which assigns `gg_trg_<name> = CreateTrigger()`. Send the actions alone and the tools add that wrapper (the result says what was added), or write the whole thing yourself. The script name is the trigger name with every character outside `A-Z a-z 0-9 _` turned into `_` (`gg_trg_<script name>`), so identifier-safe names keep the script readable and unambiguous.
- `run_on_init` makes a script trigger run at map start. A GUI trigger runs at map start through the event `{"fn": "MapInitializationEvent"}`.
- A `trigger` op naming an existing trigger replaces it (`created` stays empty). To change a few lines of a long script, use `{"op": "script_replace", "name": "SWTest", "old": "2900.0, -500.0", "new": "2900.0, -250.0"}` (or `"header": true` for the map header) instead of resending the whole script; `old` must occur exactly once.
- Trigger code is emitted in trigger-tree order: a function defined in an earlier trigger (or category) can be called from a later one, not the other way round. Put shared helper functions in the first triggers.
- `validate=true` returns pjass / Lua errors straight away, each with `script_line`, its line inside the script you sent. Without it, `triggers_edit` warns that the map script is not regenerated yet; `map_save` or `script_build` regenerates it.
- `map_save` compiles a regenerated or edited script and refuses to save when it does not compile; `validation.script` shows the result.
- `{"op": "delete", "what": "variable" | "trigger" | "category", "name": ...}` removes a global (refused while triggers use it), a trigger, or an empty category.
- `variable` ops create GUI globals, emitted as `udg_<Name>`; `array_size` makes an array. Types known to work: `integer`, `real`, `boolean`, `string`, `unit`, `hashtable`, `dialog`, `leaderboard`, `multiboard`, `timer`, `timerdialog`. The generated `InitGlobals` initializes arrays for indices `0..array_size` inclusive, and a `dialog` array gets `DialogCreate()` for each of them. A `hashtable` variable starts as `null`: call `InitHashtable()` first.
- A `run_on_init` trigger already sees the preplaced units: `GroupEnumUnitsOfPlayer(g, Player(PLAYER_NEUTRAL_AGGRESSIVE), null)` enumerates the creeps.
- Deleting the default `Melee Initialization` trigger removes all melee behaviour (starting units, victory and defeat), which a non-melee map needs.
- Reforged natives that pass pjass and work in the game: `BlzSetUnitMaxHP`, `BlzGetUnitMaxHP`, `GetEventDamageSource`, `BlzSetEventDamage`, `BlzGetUnitAbilityCooldownRemaining`, `BlzSetAbilityResearchTooltip`, `BlzSetAbilityResearchExtendedTooltip`, `BlzGetAbilityResearchTooltip`, `BlzGetUnitAbility`, `BlzGetAbilityStringField` / `BlzSetAbilityStringField`, and the event `EVENT_PLAYER_UNIT_DAMAGED` (with `TriggerRegisterAnyUnitEventBJ`).

## Map info and object data

- `info_edit` `set` of a whole list (`forces`, `players`) replaces it, and every element must be complete, including `unknown_flag_bits`. Read the shape from `info_get` first.
- `objdata_edit` `create` takes an explicit `id` (`"h000"`) or allocates one like the editor. `set` also works on stock ids (`hgtw`), which makes modified standard objects. `base` may be one of the map's custom objects (`{"op": "create", "id": "u001", "base": "u000", "set": {...}}`): the copy gets its stock base and all its modifications, then `set`.
- `objdata_get` checks the model the object really uses: when the map changes `umdl` (or `dfil`/`bfil` and the variation count), `model.files` and `model.missing` follow the map's value (`source: "map"`), and imported models count as present.
- Unit fields for custom buildings: `upat` pathing texture, `usca` model scale, `umpm`/`umpi`/`umpr` mana maximum/initial/regeneration, `ufma` food produced, `ubpx`/`ubpy` button position, `uupt` upgrades to, `upgr` upgrades used, `ures` researches, `utra` units trained. `umvt` `"fly"` with `umvh` makes a flying unit.
- Pathing textures come in many sizes under `PathTextures\` (`4x4SimpleSolid`, `8x8Simple`, `12x12Simple`, `16x16Simple`, ...; one cell is 32 world units). Stock sizes: Barracks and Beastiary `12x12Simple`, Castle `16x16Simple`, Guard and Cannon Tower `4x4SimpleSolid`.
- A builder needs no build ability: a copy of `uaco` (Acolyte) with `uabi` `"Avul"` and a `ubui` list of custom buildings shows a Build command.
- Fields take raw codes, for example `ubui` (structures built), `ureq` (requirements), `ugol` / `ulum` (gold / lumber cost), `ubld` (build time), `umvs` (movement speed), or `Name`. Setting `ureq` to `""` removes a building's tech requirements.
- Per-level ability fields take level keys: `{"aran": {"1": 620}}`, `{"acdn": {"1": 20}}`. Other fields take plain values (`"aher": 0`, `"alev": 1`); Channel's animation names `aani` has no levels. A unit's `uabi`, `uhab`, `usei` and an item's `iabi` are comma-separated id strings (`"A003,A004"`).
- `objdata_get` sizes `levels` and per-level lists by the map's own `alev` (abilities) or `glvl` (upgrades); values stored for levels beyond it are listed under `unused_levels` and do not exist in the game.
- A hero's `uhab` takes at most 5 abilities (`maxVal` 5): with 11, `SelectHeroSkill` learned the 1st and 4th but not the 9th.
- Item fields: `iabi` abilities, `igol` gold cost, `iico` icon, `ifil` model, `icla` class, `ilev` level, `isel` sold by merchants, `ipaw` sellable, `iprn` random choice, `isto` stock maximum, `istr` replenish interval, `isst` start delay, `isit` initial stock, `uhot` hotkey, `utip` / `utub` tooltips, `ides` description. A custom item inherits its base's hotkey (`rst1`: `S`).
- Stock item abilities and their bonus fields (all per level): `AIx5` all stats (`Iagi`, `Iint`, `Istr`, `Ihid`), `AItc` damage (`Iatt`), `AIsx` attack speed (`Isx1`, a fraction), `AIlf` max life (`Ilif`), `Arel` life regeneration (`Ihpr`), `AImb` max mana (`Iman`), `AIrm` mana regeneration (`Imrp`), `AId3` armor (`Idef`), `AIcs` critical strike (`Ocr1` chance, `Ocr2` multiplier). Basic items: `rst1`, `rag1`, `rin1` (+3 stat), `ratc` Claws +12, `gcel` Gloves of Haste, `rde2` Ring of Protection +3, `prvt` Periapt, `rlif` Ring of Regeneration, `penr` Pendant of Energy, `rwiz` Sobi Mask.
- A shop sells the items in its `usei`: a custom copy of `nmgv` (Magic Vault) with `uabi` `"Aneu,Avul,Apit"` sold items to a hero, and `IssueNeutralImmediateOrderById` bought one and charged the gold.
- Channel (`ANcl`): `Ncl1` follow-through time, `Ncl2` target type (0 none, 1 unit, 2 point, 3 unit or point), `Ncl3` option bits (1 visible, 2 targeting image, 4 physical, 8 universal, 16 unique cast), `Ncl4` art duration, `Ncl5` disable other abilities, `Ncl6` base order id. Several Channel copies on one unit need distinct `Ncl6` orders (`acidbomb`, `howlofterror`, `avengerform`, `doom`); with `Ncl1` 0 and `Ncl5` 0 each cast by its own order string.
- A hidden, learnable, effect-free hero ability: copy `Aamk` (Attribute Bonus) with `Iagi`/`Iint`/`Istr` 0 and `Ihid` 1 on every level. It shows in the learn menu with its `arar` icon and `aret`/`arut` tooltips and has no command-card button.
- `data_search kind=icon` / `model` / `file` take globs (`*BTN*Staff*`, `PathTextures/8x8*`) or plain substrings. Use a result's `ref` in object data and scripts (`ReplaceableTextures\CommandButtons\BTNSkillz.blp`); `layers` says which storage layers hold it.
- Art fields (for example an ability's research icon `arar`) live in the skin files (`war3mapSkin.w3a`), so `merge_external` keeps them with the working copy's changes.
- True Sight abilities (`Adtg`, `Atru`, `ANtr`, `Agyv`, `Adts`, `Adt1`) detect within `aran` (Cast Range), not `aare`.
- `Apiv` (Permanent Invisibility) fades in over `adur`/`ahdu`, 2 seconds by default. With both set to 0, a unit given the ability turns invisible at once.

## Game behaviour (verified in the game)

- A unit given a permanent-invisibility ability with `UnitAddAbility` is invisible to enemies: `IsUnitVisible(u, enemy)` is false and `IsUnitInvisible(u, enemy)` true. With an enemy true-sight unit in range, both flip. `UnitRemoveAbility` makes it visible again, and adding the ability again works.
- A single-player run can create units for an empty player slot (`Player(1)`), and visibility queries against that player work as for a playing one.
- `SetUnitAcquireRange(u, 0)` does not stop a unit from attacking an enemy already inside its attack range.
- `EVENT_PLAYER_UNIT_ATTACKED` fired once while a unit hit the same target for several swings. `EVENT_PLAYER_UNIT_DAMAGED` fires on every hit, and `GetEventDamageSource()` returns the attacker.
- In a single-player game an open dialog (`DialogDisplay`) pauses game time: timers and `TriggerSleepAction` wait until it is clicked. `GetClickedDialog()` / `GetClickedButton()` identify the click; map buttons to options with `SaveInteger(ht, GetHandleId(DialogAddButton(...)), 0, option)`.

Heroes and abilities:
- `SetHeroLevel(h, 10, false)` on a new hero gives 10 unspent skill points. `SelectHeroSkill` fires `EVENT_PLAYER_HERO_SKILL`; in the handler `GetLearnedSkill()` names the ability and `GetUnitAbilityLevel` already returns the new level.
- After `SetPlayerAbilityAvailable(p, heroAbility, false)`, `SelectHeroSkill` for it does nothing (no level, no point spent) until it is made available again.
- `UnitAddAbility` of stock hero abilities (`AHtb`, `AUfn`, `AOcr`, `AHav`) onto a hero works and `SetUnitAbilityLevel` sets their level; they do not appear in the learn menu. A hero ability at its maximum level is not shown in the learn menu either.
- `BlzSetAbilityResearchTooltip(abilCode, text, level)` changes the learn-menu tooltip. The learn-menu icon cannot change at runtime: `BlzSetAbilityIcon` and `ABILITY_SF_ICON_RESEARCH` have no visible effect there, `BlzGetUnitAbility` returns `null` for a hero ability not learned yet, and an empty `arar` shows a placeholder portrait.
- `ForceUIKey("O")` opens the hero learn menu only after `SelectUnit(h, true)` and a 0.5 s `TriggerSleepAction`, not right after the selection.
- A Channel spell's cooldown starts even when its `EVENT_PLAYER_UNIT_SPELL_EFFECT` handler moves the caster (`SetUnitPosition`) and issues an attack order.

Damage:
- `UnitDamageTarget(src, t, 189, true, false, ATTACK_TYPE_NORMAL, DAMAGE_TYPE_MAGIC, WEAPON_TYPE_WHOKNOWS)` removed 188 life from an Ogre Lord (`nogl`); 100 of it on a hero arrived as 75 (`GetEventDamage`).
- In `EVENT_PLAYER_UNIT_DAMAGED`, `BlzSetEventDamage(0.0)` prevents the life loss and `BlzSetEventDamage(d - x)` reduces it by x.
- A unit given `Abun` (Cargo Hold) with `UnitAddAbility` did not attack enemies 350 units away.

Items:
- `EVENT_PLAYER_UNIT_PICKUP_ITEM` fires for `UnitAddItemById`, `UnitAddItem` and shop purchases.
- Recipes: in the pickup handler, `TriggerSleepAction(0.0)`, then `RemoveItem` the components and `UnitAddItemById` the result. The result's own pickup event runs the handler again without combining twice.
- `UnitAddItemToSlotById(h, id, 4)` puts an item in slot 4. `UnitDropItemSlot` right after `UnitAddItem` did not move the item.
- Hero swap keeping items: `UnitRemoveItem` + `SetItemVisible(item, false)`, `RemoveUnit` the old hero, then `SetItemVisible(item, true)` + `UnitAddItem` on the new one; `SetHeroXP(new, GetHeroXP(old), false)` keeps the level.

Deaths:
- `ReviveHero(h, x, y, true)` after a `TriggerSleepAction` in the death handler revives the hero at (x, y) with full life. A death handler with `TriggerSleepAction(45.0)` and `CreateUnit` respawns a creep.
- `KillUnit(u)` and a killing `UnitDamageTarget(src, u, ...)` run the `EVENT_PLAYER_UNIT_DEATH` handler before the next statement of the calling code; `GetKillingUnit()` returns `src`.

Players and UI:
- The unused player slots 10 and 11 work as computer army owners without any `war3map.w3i` entry. After `SetPlayerAllianceStateBJ` (`bj_ALLIANCE_ALLIED_VISION` with their team's players, `bj_ALLIANCE_UNALLIED` with the other team), `IsPlayerAlly` and `IsPlayerEnemy` answer accordingly, and units created with `CreateUnit` and ordered `IssuePointOrder(u, "attack", x, y)` march and fight.
- In a single-player run `GetPlayerName` returns `"Local Player"` for the human and `"Player N"` for empty slots, not the names in `war3map.w3i`.
- `SetUnitState(b, UNIT_STATE_MANA, 1.5)` on a building with `umpm` 20 and `umpr` 0 keeps 1.5 / 20, so a building's mana bar can show script-driven progress.
- A multiboard created from a 0.1-second timer callback (`CreateMultiboard`, `MultiboardSetItemStyle(item, true, false)`, `MultiboardSetItemWidth`, `MultiboardDisplay`) shows in the top-right corner.

## World Editor

`editor_launch`, `editor_status`, `editor_map` (open/save/reload/close/quit), `editor_menu`, `editor_dialogs`, `editor_dialog_act`, `editor_input`, `editor_screenshot`, `editor_log`.

- Take turns with the user: never discard unsaved work in the editor. `map_save` refuses while the editor has the same map with unsaved changes; ask the user first.
- The editor holds a lock on the map file whenever it shows the map, even with no unsaved changes, so `map_save` cannot replace it (`editor_holds_map`). The safe round trip is: **MCP edits → `editor_map action=close` → `map_save` → `editor_map action=open` → `editor_map action=save`**. That save recomputes pathing, shadows and minimap icons and compiles the script.
- `editor_map action=save` returns per-trigger script errors and the triggers the editor disabled. Empty `errors` and `disabled_triggers` mean the script compiled.
- `editor_map action=open` starts the editor with the map: an editor that shows another map, or none after `close`, is quit and relaunched (`previous_instance: "relaunched"`). Only an editor already showing that map is reused.
- `map_open` of a map whose working copy has no unsaved edits reloads it after an editor save (`source_changed` becomes `false`).
- An editor save rewrites the map file, so the next `map_save` of a working copy with its own edits fails with `source_changed`. Use `map_save merge_external=true`: it keeps the working copy's changed files and takes everything else from the map file (the recomputed pathing, shadows and minimap), then saves. `force=true` would overwrite what the editor recomputed, and `map_close discard=true` would drop your edits. `map_open merge_external=true` does the same merge when reopening. Saving the working copy **before** handing the map to the editor avoids the question.
- The editor writes its log only when it quits. `editor_log` parses the last session: `missing_files` (files it could not load), `messages`, and a count of benign ones; `note` says when a running editor makes the log stale. For missing models, use `map_validate` instead of waiting for the editor.
- `Failed to load Environment Map for tileset A` and `Referencing unknown database field: 'netsafe' / 'occlusion' / 'teamColor' ...` appear for every map. They are not map defects.

## Game tests

- `game_test` launches the map and ends as soon as every file listed in `results` exists under `Documents\Warcraft III\CustomMapData`. The map script writes such a file with `PreloadGenClear()` / `PreloadGenStart()` / `Preload("text")` / `PreloadGenEnd("mymap\\results.txt")`. A run whose files never appear lasts the full `timeout` and lists them under `missing`.
- `game_test probe=true` needs no reporting trigger of your own. It runs a throwaway copy that reports, `probe_seconds` into the game, the units, heroes, gold and lumber of every playing slot, plus the `BJDebugMsg` text (`probe.messages`). Use it to check that a map loads and runs.
- For a specific check, pass `probe_script` (or `probe_script_file`): statements in the map's language, JASS locals first, that run in the throwaway copy at `probe_seconds`. They can call the map's own functions (the probe trigger comes after all map triggers), read its `udg_` globals and wait with `TriggerSleepAction` (about 160 s of waits in one probe worked; each `ProbeReport` comes back in order). `ProbeReport(text)` writes text of any length, returned in `probe.reports`. The real map never gets test triggers, so there is nothing to remove before shipping.
  ```
  local unit u = CreateUnit(Player(0), 'hfoo', 0, 0, 270)
  if IsUnitVisible(u, Player(1)) then
      call ProbeReport("visible=1")
  else
      call ProbeReport("visible=0")
  endif
  ```
- The game keeps about 259 characters of one `Preload` string and silently drops the rest. `game_test` lists result lines that reach that length under `truncated`. Split long reports into several `Preload` calls, or use `ProbeReport`. Result strings come back unescaped (single backslashes).
- A run that writes its result file ends as soon as the file exists: 34–124 seconds in practice, most of it launch and map load (a probe with 160 s of waits took 189 s).
- **Every launch can hit the Battle.net login screen**, and the user may not be able to log in again and again. Put all checks of a session into as few runs as possible: one `probe_script` can run many checks with waits between them.
- A map with `loading_screen` `title`, `subtitle` or `text` waits on "PRESS ANY KEY TO CONTINUE" after loading. `game_test` presses space when it sees that screen and reports `loading_screen_keys`.
- An open dialog pauses a single-player game, so a map that shows a dialog early (a hero draft) never reaches a later `probe_seconds` or test timer on its own. Run the test code before the dialog opens (`probe_seconds` 0.3 worked). A timed-out run's hint mentions this; `screenshot=true` shows the dialog.
- To capture the hero learn menu: in the test code, `SelectUnit(h, true)`, `TriggerSleepAction(0.5)`, `ForceUIKey("O")`, then report; `screenshot=true` captures it. A user click in the game window meanwhile changes what is captured.
- `screenshot=true` saves a PNG of the game window. When the window will not come to the front, the tools draw it from the window itself; `screenshot_of` says what was captured, or why nothing was. `focus` says how often the window was raised.
- `log` holds the useful `War3Log.txt` lines, `missing_files` the files the game could not load, and `benign_log` counts shipped-data lines such as `model creation failed - C:/Users/<builder>/Perforce/.../GuardTowerBirth.mdl` or `Solid texture substituted - Units\_skeletons\Gore_Diffuse.tif`. Do not chase benign lines as map defects.
- `game_status` returns recent `War3Log.txt` lines even with no game running, including runs started from the World Editor's own test command.

## Rules

- The game loads a map only while its window is in front, and Warcraft III can show a Battle.net login first, also again later in a session. **Never type credentials**: ask the user to log in (with "Keep me logged in") and approve any authenticator request.
- `game_test` recognises the login screen and returns `login_required: true` after about 30 seconds, leaving the game open. Ask the user to log in there, then call `game_test` again with **the same arguments**: it continues in that game (`continued_game: true`) instead of launching a new one. A different test closes that game and launches again.
- If `game_test` returns no results and `exited_early`, the map failed to load: take a screenshot (`screenshot=true`) and tell the user.
- Keep a backup (`map_save` makes one) before replacing a user's map, and say which file changed.

## Common practice (not verified by the tools)

- Create leaderboards, multiboards and timer dialogs from a short timer (for example 0.1 seconds) after map start, not directly at initialization, where they may not display.
- Adding ability `Abun` (Cargo Hold) to a unit is a common way to remove its attack, for example so that creeps walk a path without fighting.
- Client-side UI changes (`BlzSetAbilityPosX/Y`, `BlzSetAbilityResearchTooltip`) go inside `GetLocalPlayer()` blocks, on the assumption that they do not desync a multiplayer game. Not tested with several players.
