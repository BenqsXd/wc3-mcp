# Game behaviour verified in the game

Everything here was observed in a real run (mostly through `game_test probe_script`), not read from the data files.

## Heroes and abilities

- `SetHeroLevel(h, 10, false)` on a new hero gives 10 unspent skill points. `SelectHeroSkill` fires `EVENT_PLAYER_HERO_SKILL`; in the handler `GetLearnedSkill()` names the ability and `GetUnitAbilityLevel` already returns the new level.
- Total experience per level, measured with `AddHeroXP`: 200, 500, 900, 1400, 2000, 2700, 3500, 4400, 5400 for levels 2 to 10. A learn table therefore needs one entry per level from 1 to 10.
- `AddHeroXP` ignores the creep experience reduction table, which otherwise gives a hero no creep experience from level 5 on. Awarding experience from a creep death handler is the way to let heroes pass level 5 in a map without melee gold and tech.
- After `SetPlayerAbilityAvailable(p, heroAbility, false)`, `SelectHeroSkill` for it does nothing (no level, no point spent) until it is made available again.
- `UnitAddAbility` of stock hero abilities (`AHtb`, `AUfn`, `AOcr`, `AHav`) onto a hero works and `SetUnitAbilityLevel` sets their level; they do not appear in the learn menu. A hero ability at its maximum level is not shown in the learn menu either.
- `BlzSetAbilityResearchTooltip(abilCode, text, level)` changes the learn-menu tooltip. The learn-menu icon cannot change at runtime: `BlzSetAbilityIcon` and `ABILITY_SF_ICON_RESEARCH` have no visible effect there, `BlzGetUnitAbility` returns `null` for a hero ability not learned yet, and an empty `arar` shows a placeholder portrait.
- `ForceUIKey("O")` opens the hero learn menu only after `SelectUnit(h, true)` and a 0.5 s `TriggerSleepAction`, not right after the selection.
- A Channel spell's cooldown starts even when its `EVENT_PLAYER_UNIT_SPELL_EFFECT` handler moves the caster (`SetUnitPosition`) and issues an attack order.

## Vision, groups and invisibility

- A unit given a permanent-invisibility ability with `UnitAddAbility` is invisible to enemies: `IsUnitVisible(u, enemy)` is false and `IsUnitInvisible(u, enemy)` true. With an enemy true-sight unit in range, both flip. `UnitRemoveAbility` makes it visible again.
- `SetPlayerAlliance(other, p, ALLIANCE_SHARED_VISION, true)` for every other player gives p full vision of the map, and `false` takes it back — no fog modifier handle to keep.
- `GroupEnumUnitsInRange` returns Locust units, and units of `PLAYER_NEUTRAL_PASSIVE` count as enemies for `IsUnitEnemy`, so decorative marker units are counted unless the filter skips them (`GetUnitAbilityLevel(u, 'Aloc') == 0`).
- A single-player run can create units for an empty player slot (`Player(1)`), and visibility queries against that player work as for a playing one.

## Combat

- `SetUnitAcquireRange(u, 0)` does not stop a unit from attacking an enemy already inside its attack range.
- `EVENT_PLAYER_UNIT_ATTACKED` fired once while a unit hit the same target for several swings. `EVENT_PLAYER_UNIT_DAMAGED` fires on every hit, and `GetEventDamageSource()` returns the attacker.
- `UnitDamageTarget(src, t, 189, true, false, ATTACK_TYPE_NORMAL, DAMAGE_TYPE_MAGIC, WEAPON_TYPE_WHOKNOWS)` removed 188 life from an Ogre Lord (`nogl`); 100 of it on a hero arrived as 75 (`GetEventDamage`).
- In `EVENT_PLAYER_UNIT_DAMAGED`, `BlzSetEventDamage(0.0)` prevents the life loss and `BlzSetEventDamage(d - x)` reduces it by x.
- A unit given `Abun` (Cargo Hold) with `UnitAddAbility` did not attack enemies 350 units away.

## Items

- `EVENT_PLAYER_UNIT_PICKUP_ITEM` fires for `UnitAddItemById`, `UnitAddItem` and shop purchases.
- Recipes: in the pickup handler, `RemoveItem` the components and `UnitAddItemById` the result. `RemoveItem` fires `EVENT_PLAYER_UNIT_DROP_ITEM` and `UnitAddItemById` fires `..._PICKUP_ITEM`, so the handler re-enters itself: an unguarded combine built six copies. Guard it with a global flag or `DisableTrigger(GetTriggeringTrigger())` around the change. (The older `TriggerSleepAction(0.0)` version worked in one test; the guard is what makes it safe, and `script_validate lint=true` reports `item_reentry` without one.)
- `UnitAddItemToSlotById(h, id, 4)` puts an item in slot 4. `UnitDropItemSlot` right after `UnitAddItem` did not move the item.
- Hero swap keeping items: `UnitRemoveItem` + `SetItemVisible(item, false)`, `RemoveUnit` the old hero, then `SetItemVisible(item, true)` + `UnitAddItem` on the new one; `SetHeroXP(new, GetHeroXP(old), false)` keeps the level.
- `ChooseRandomItemEx(ITEM_TYPE_PERMANENT, 2)`, `(ITEM_TYPE_PERMANENT, 6)` and `(ITEM_TYPE_ARTIFACT, 7)` returned real item ids (Claws of Attack +5, Khadgar's Gem of Health, Orb of Frost), so random drops by class and level need no item pool.

## Timers, stats and measurement

- A countdown that subtracts a fixed step per tick drifts: a 0.1 s timer decrementing 2.0 by 0.10 read 0.8 left after 3 s. Run one free timer as the clock (`TimerStart(t, 1000000, false, null)`, `TimerGetElapsed`) and store absolute deadlines.
- `BlzSetUnitMaxHP` changes max life; `SetUnitState(u, UNIT_STATE_MAX_LIFE, x)` does not.
- `BlzSetUnitArmor` in a 0.5 s loop drives strength to armour exactly, and `SetUnitMoveSpeed(u, GetUnitDefaultMoveSpeed(u) * (1 + k * agi))` is exact too. A stat loop that writes move speed wipes an item's move-speed bonus: give each of move speed, armour and resist exactly one writer.
- `SetUnitAcquireRange(h, 1.0)` stops acquiring, not retaliating; `PauseUnit(h, true)` holds a hero silent while scripted damage still goes out from it. Two heroes 400 apart auto-attack each other and spoil a damage measurement: pause both and place them thousands of units apart.
- Pool dummy units. `CreateUnit` per missile plus `RemoveUnit` on impact grew the handle counter by 118 over 120 missiles; keeping the dummy and calling `ShowUnit(u, false)` gave 2 over 60. Every probe run reports `handles` (start, end, growth, per_minute), and `ProbeHandleCount()` samples the counter around a loop.
- Bot gold is no measurement (a farming bot earns meanwhile): verify the reward function and the credit instead.

## Deaths

- `ReviveHero(h, x, y, true)` after a `TriggerSleepAction` in the death handler revives the hero at (x, y) with full life. A death handler with `TriggerSleepAction(45.0)` and `CreateUnit` respawns a creep.
- `KillUnit(u)` and a killing `UnitDamageTarget(src, u, ...)` run the `EVENT_PLAYER_UNIT_DEATH` handler before the next statement of the calling code; `GetKillingUnit()` returns `src`.
- `GroupEnumUnitsInRange` keeps corpses: they still answer `GetUnitTypeId`, `BlzGetUnitMaxHP` and their owner, so an area spell hits them unless the loop or the filter tests `GetUnitState(u, UNIT_STATE_LIFE) > 0.405`.
- `SetPlayerHandicapXP(p, 0)` plus `AddHeroXP` is the way to award authored kill experience. Last-hit attribution: store `(lastHitBy, lastHitAt)` per player in the damage handler and credit it on death inside 15 s.
- A region leave event fires only when a unit inside the rect leaves it alive; a unit moved from outside to further outside, or a dead one, fires nothing useful.
- Waygates: the generated script sets the destination and activates a placed gate at map start, so nothing has to be activated by hand. A unit uses it when ordered onto the gate itself (`IssueTargetOrder(h, "smart", gate)`, what a right-click does); `IssuePointOrder(h, "move", gateX, gateY)` stops about 110 units short and nothing happens. `map_validate` reports `waygate_self` for a gate whose destination region contains the gate.
- An empty player slot is not a Computer and does not need to be: `CreateUnit`, orders and alliances work for it. "A human is here" is `GetPlayerController(p) == MAP_CONTROL_USER and GetPlayerSlotState(p) == PLAYER_SLOT_STATE_PLAYING`. Runtime teams on 12 FFA slots work with `SetPlayerAllianceStateBJ` (`bj_ALLIANCE_ALLIED_VISION` / `bj_ALLIANCE_UNALLIED`); allied players still get the gold-transfer slider.
- Camps can be rebuilt from the placed units at init: enumerate `Player(PLAYER_NEUTRAL_AGGRESSIVE)` and cluster by distance (700 rebuilt 15 camps and 43 members), so moving a camp in the editor moves it in the script.

## Players, dialogs and UI

- In a single-player game an open dialog (`DialogDisplay`) pauses game time: timers and `TriggerSleepAction` wait until it is clicked. `GetClickedDialog()` / `GetClickedButton()` identify the click; map buttons to options with `SaveInteger(ht, GetHandleId(DialogAddButton(...)), 0, option)`.
- The unused player slots 8, 10 and 11 work as computer army owners without any `war3map.w3i` entry. After `SetPlayerAllianceStateBJ` (`bj_ALLIANCE_ALLIED_VISION` with their team, `bj_ALLIANCE_UNALLIED` with the other), `IsPlayerAlly` and `IsPlayerEnemy` answer accordingly, and units created with `CreateUnit` and ordered `IssuePointOrder(u, "attack", x, y)` march and fight.
- In a single-player run `GetPlayerName` returns `"Local Player"` for the human and `"Player N"` for empty slots, not the names in `war3map.w3i`. `SetPlayerName` works on empty slots.
- `SetUnitState(b, UNIT_STATE_MANA, 1.5)` on a building with `umpm` 20 and `umpr` 0 keeps 1.5 / 20, so a building's mana bar can show script-driven progress.
- A multiboard created from a 0.1-second timer callback (`CreateMultiboard`, `MultiboardSetItemStyle(item, true, false)`, `MultiboardSetItemWidth`, `MultiboardDisplay`) shows in the top-right corner; `MultiboardSetTitleText` every 0.5 s updates its title. `SelectUnitForPlayerSingle(u, Player(0))` from such a timer selects the unit.
- `CustomVictoryBJ(p, true, true)` in a single-player custom game shows a "Victory!" dialog with "Continue" and "Quit Campaign".

## Workers, training and building

- A worker copied from `ewsp` with `uabi` `"Awha"` harvests trees: in the `EVENT_PLAYER_UNIT_TRAIN_FINISH` handler, `TriggerSleepAction(0.0)` then `IssueTargetOrder(worker, "harvest", tree)` on an `LTlt`. Lumber arrives without any drop-off building (`Wha1` 8 gave 8 lumber in 20 s).
- `IssueImmediateOrderById(hall, 'n011')` on a building that lists `n011` in `utra` trains it and charges its cost. In `EVENT_PLAYER_UNIT_TRAIN_FINISH`, `GetTrainedUnit()` is the unit; `ShowUnit(u, false)` plus `RemoveUnit(u)` leaves nothing behind. Units with `ufoo` 0 train without any food building.
- `IssueBuildOrderById(builder, 'h000', x, y)` returns true, and `GetUnitCurrentOrder(builder)` equals `'h000'` while the builder is on its way. On an unbuildable tile the order starts nothing at all.
- Refund pattern: an `EVENT_PLAYER_UNIT_CONSTRUCT_START` handler adds the cost back and calls `RemoveUnit(GetConstructingStructure())`; no structure is left and the gold is unchanged.
- A structure copied from `hhou` with a unit model, `ubld` 1 and an Acolyte-copy builder finishes within seconds; `EVENT_PLAYER_UNIT_CONSTRUCT_FINISH` fires for each.
- Swapping a player's structure for a unit of another player (`RemoveUnit` + `CreateUnit(Player(10), ...)` + `SetUnitColor`) and back each round works at scale (about 50 slots over seven rounds).

## Common practice (not verified by the tools)

- Create leaderboards, multiboards and timer dialogs from a short timer (for example 0.1 seconds) after map start, not directly at initialization, where they may not display.
- Adding ability `Abun` (Cargo Hold) to a unit is a common way to remove its attack, for example so that creeps walk a path without fighting.
- Client-side UI changes (`BlzSetAbilityPosX/Y`, `BlzSetAbilityResearchTooltip`) go inside `GetLocalPlayer()` blocks, on the assumption that they do not desync a multiplayer game. Not tested with several players.
