# Game behaviour verified in the game

Everything here was observed in a real run (mostly through `game_test probe_script`), not read from the data files.

## Heroes and abilities

- `SetHeroLevel(h, 10, false)` on a new hero gives 10 unspent skill points. `SelectHeroSkill` fires `EVENT_PLAYER_HERO_SKILL`; in the handler `GetLearnedSkill()` names the ability and `GetUnitAbilityLevel` already returns the new level.
- Total experience per level, measured with `AddHeroXP`: 200, 500, 900, 1400, 2000, 2700, 3500, 4400, 5400 for levels 2 to 10. A learn table therefore needs one entry per level from 1 to 10.
- `AddHeroXP` ignores the creep experience reduction table, which otherwise gives a hero no creep experience from level 5 on. Awarding experience from a creep death handler is the way to let heroes pass level 5 in a map without melee gold and tech.
- After `SetPlayerAbilityAvailable(p, heroAbility, false)`, `SelectHeroSkill` for it does nothing (no level, no point spent) until it is made available again.
- `UnitAddAbility` of stock hero abilities (`AHtb`, `AUfn`, `AOcr`, `AHav`) onto a hero works and `SetUnitAbilityLevel` sets their level; they do not appear in the learn menu. A hero ability at its maximum level is not shown in the learn menu either.
- `BlzSetAbilityResearchTooltip(abilCode, text, level)` changes the learn-menu tooltip. The learn-menu icon cannot change at runtime: `BlzSetAbilityIcon` and `ABILITY_SF_ICON_RESEARCH` have no visible effect there, `BlzGetUnitAbility` returns `null` for a hero ability not learned yet, and an empty `arar` shows a placeholder portrait.
- `SelectHeroSkill` cannot learn through an Engineering Upgrade (`ANeg`) swap on game 3.0.0 (build 24268): adding the clone removes the learned slot ability and gives nothing, and a placeholder that gets a swap after being learned loses its rank. Learning through the learn menu (`SelectUnitForPlayerSingle` + `ForceUIKeyBJ(p, "O")`, then the slot's hotkey) does learn the real ability, spends a point and fires `EVENT_PLAYER_HERO_SKILL` with it. For computer players, which cannot use the menu, learn a hidden placeholder ability with `SelectHeroSkill` and add the real ability from the skill handler at the placeholder's rank; removing the swaps sends each learned rank back to its placeholder.
- `ForceUIKey("O")` opens the hero learn menu only after `SelectUnit(h, true)` and a 0.5 s `TriggerSleepAction`, not right after the selection.
- A Channel spell's cooldown starts even when its `EVENT_PLAYER_UNIT_SPELL_EFFECT` handler moves the caster (`SetUnitPosition`) and issues an attack order.

## Vision, groups and invisibility

- A unit given a permanent-invisibility ability with `UnitAddAbility` is invisible to enemies: `IsUnitVisible(u, enemy)` is false and `IsUnitInvisible(u, enemy)` true. With an enemy true-sight unit in range, both flip. `UnitRemoveAbility` makes it visible again.
- `SetPlayerAlliance(other, p, ALLIANCE_SHARED_VISION, true)` for every other player gives p full vision of the map, and `false` takes it back — no fog modifier handle to keep.
- `GroupEnumUnitsInRange` returns Locust units, and units of `PLAYER_NEUTRAL_PASSIVE` count as enemies for `IsUnitEnemy`, so decorative marker units are counted unless the filter skips them (`GetUnitAbilityLevel(u, 'Aloc') == 0`).
- Units moved with `SetUnitPosition` are visible to nobody until vision updates: wait about 0.5 s before reading `IsUnitVisible`.
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

- **A Channel cast resolves inside about a second.** With 0.5 s between the order and `UnitRemoveAbility` only 6 of 40 abilities reached `EVENT_PLAYER_UNIT_SPELL_EFFECT`, with 1.0 s all 40: removing the ability cancels a cast in flight. A test that adds an ability, orders it and takes it away needs a second in between.
- A global cast counter cannot attribute a cast in a map with bots (they cast throughout): record the last ability id instead, and freeze the bots while measuring.
- **Strongest-wins for every stacking status, buffs included**: a weaker buff overwriting a stronger one lowered armour. One 0.5 s loop can own move speed, armour, resist, slows, damage over time and timed buffs together (a 40 % slow took 270 to 162 and back; 100/s burn for 2 s dealt 199.7).
- `SetUnitPosition` puts a unit on the nearest walkable spot, which can be past a clamp (a 600 blink landed 676 away once); still better than `SetUnitX/Y` inside a cliff.
- An effect created and destroyed in a pair is cheap: art on a pooled missile dummy cost 12 handles over 60 missiles. Destroy the slot's handle on relaunch as well as on impact. `effect` is a `triggers_edit` variable type.
- `SetCameraFieldForPlayer(p, CAMERA_FIELD_TARGET_DISTANCE, d, 0)` on a 0.5 s timer holds a camera distance (and disables that player's mouse wheel, so make it opt-in); `GetCameraField` reads it back for the local player. A camera lock that lets the minimap work: re-centre from a 50 Hz timer and stand down while `BlzIsMouseButtonPressed(MOUSE_BUTTON_TYPE_LEFT)` and the target jumped (a minimap click moved it); `SetCameraTargetController` swallows minimap clicks.
- `PingMinimapEx(x, y, duration, r, g, b, true)` gives a coloured alert ping. `ushu` "" removes a unit's shadow.
- `GetObjectName(abilityCode)` returns the authored name in game. `BlzSetAbilityResearchTooltip` is per ability code (the same for every player); inside a `GetLocalPlayer` block each player sees their own text without a desync.

## Shops and camps

- A shop sells only within a few hundred units of the buyer's unit (Tavern 300-350, Goblin Merchant 250) and not in the first seconds of a map; `isto` 0 is never in stock (references/objects.md).
- `IssueNeutralImmediateOrderById(player, shop, id)` returned false for every hero a Tavern listed - distance, gold, food and stock ruled out - while `IssueImmediateOrderById(shop, id)` on the same shop sold one and fired `EVENT_PLAYER_UNIT_SELL`. `ForceUIKey` does nothing on a neutral shop's card. Neither stands in for a click.
- Neither `EVENT_PLAYER_UNIT_SELL_ITEM` nor `..._PICKUP_ITEM` sees the new item in the inventory, so a "three spells at most" rule enforced there lets the fourth through: sweep the inventory on a tick instead.
- **A passive camp**: `SetUnitAcquireRange(u, 0)` is ignored, 1 reads back as 200 (a camp still bit a hero 220 away), and `UNIT_WEAPON_BF_ATTACKS_ENABLED` false did not stop it. **`PauseUnit(u, true)` does**: the creep holds its ground, takes damage and can be attacked until the damage handler unpauses it. A paused unit keeps its order id, so test the pause and the victim's life. A hero left idle beside a creep attacks it by itself: blind the test hero (`SetUnitAcquireRange(h, 1)`) and stand it 600 away.
- `SetUnitInvulnerable(u, true)` takes a unit out of target acquisition entirely - a pick pen of mutual enemies stays still, and a bot will not even path to someone invulnerable - while its owner can still walk it and buy with it. It also stops a Fountain of Health healing it, so a safe base heals by script (5 % of max life and mana per 0.5 s tick measured 400 -> 655 of 1000 in two seconds). Give invulnerability one writer, and let a scripted freeze tell that writer to stand down.
- A gate destructible opens when killed and closes when its life is restored (`ModifyGateBJ`). Place gates closed so `map_flow` can prove the bowl seals, and open them a second into the game.

## Deaths

- `ReviveHero(h, x, y, true)` after a `TriggerSleepAction` in the death handler revives the hero at (x, y) with full life. A death handler with `TriggerSleepAction(45.0)` and `CreateUnit` respawns a creep.
- `KillUnit(u)` and a killing `UnitDamageTarget(src, u, ...)` run the `EVENT_PLAYER_UNIT_DEATH` handler before the next statement of the calling code; `GetKillingUnit()` returns `src`.
- `GroupEnumUnitsInRange` keeps corpses: they still answer `GetUnitTypeId`, `BlzGetUnitMaxHP` and their owner, so an area spell hits them unless the loop or the filter tests `GetUnitState(u, UNIT_STATE_LIFE) > 0.405`. For heroes, whose corpses can regain life, test `IsUnitType(u, UNIT_TYPE_DEAD)` instead.
- **A hero drops its whole inventory on the ground when it dies, before any death trigger runs**, and `udro` 0 does not stop it. Mirror the inventory on every change while the hero lives, sweep the corpse's surroundings with `EnumItemsInRect` + `RemoveItem` for the mirrored items, and hand them back **one tick after** `ReviveHero` (items given in the same instant do not arrive), reading the whole list into locals first - the pickup events re-take the mirror halfway. Removing items one by one fires a DROP per item while it still counts as carried: guard the handler for the duration.
- `SetPlayerHandicapXP(p, 0)` plus `AddHeroXP` is the way to award authored kill experience. Last-hit attribution: store `(lastHitBy, lastHitAt)` per player in the damage handler and credit it on death inside 15 s.
- A region leave event fires only when a unit inside the rect leaves it alive; a unit moved from outside to further outside, or a dead one, fires nothing useful.
- Waygates: the generated script sets the destination and activates a placed gate at map start, so nothing has to be activated by hand. A unit uses it when ordered onto the gate itself (`IssueTargetOrder(h, "smart", gate)`, what a right-click does); `IssuePointOrder(h, "move", gateX, gateY)` stops about 110 units short and nothing happens. `map_validate` reports `waygate_self` for a gate whose destination region contains the gate.
- An empty player slot is not a Computer and does not need to be: `CreateUnit`, orders and alliances work for it. "A human is here" is `GetPlayerController(p) == MAP_CONTROL_USER and GetPlayerSlotState(p) == PLAYER_SLOT_STATE_PLAYING`. Runtime teams on 12 FFA slots work with `SetPlayerAllianceStateBJ` (`bj_ALLIANCE_ALLIED_VISION` / `bj_ALLIANCE_UNALLIED`); allied players still get the gold-transfer slider.
- Camps can be rebuilt from the placed units at init: enumerate `Player(PLAYER_NEUTRAL_AGGRESSIVE)` and cluster by distance (700 rebuilt 15 camps and 43 members), so moving a camp in the editor moves it in the script.

## Players, dialogs and UI

- **A player with no units has no vision at all** - with `masked_areas_partially_visible` they see a room's terrain and none of its buildings. `CreateFogModifierRect(p, FOG_OF_WAR_VISIBLE, rect, true, false)` + `FogModifierStart` per player makes vendors visible from the first frame (`IsVisibleToPlayer` checks it).
- **A `DialogDisplay` pauses a single-player game until it is clicked** - no timers, no waits, no probe. Open it on a short timer, not at map init; a probe gets past it with `game_test probe_init` and `ProbeSkipDialogs()`. A match that ends in a victory/defeat dialog pauses the same way. A timed default therefore never fires in single player. A dialog drawn as frames (a panel child of the game UI with `GLUETEXTBUTTON` buttons made from `ScriptDialogButton`; text and visibility set inside `GetLocalPlayer`) does not pause the game: keep the `dialog` and `button` handles as the choice keys (`DialogClear` / `DialogAddButton` as data), map a frame click (`FRAMEEVENT_CONTROL_CLICK`) back to its button handle, and a timer default then fires (measured: six chained dialogs timed out and took their defaults).
- A multiboard created and displayed during map initialization never appears (displayed at init and restored later it comes up collapsed): build it on the first timer tick. There is no way to add a line to the hero panel; a tooltip is the nearest place a player looks.
- `GetUnitName(hero)` is the unit type's name; `GetHeroProperName` is the hero's. `BlzGetUnitBaseDamage` on a hero already includes its primary attribute.
- The STR/AGI/INT tooltips come from `UI\FrameDef\InfoPanelStrings.fdf` (`BONUS_HITPOINTS`, `BONUS_DEFENSE`, ...); a map's own `.fdf` with a `StringList` of the same keys, loaded with `BlzLoadTOCFile`, replaces them (keep the `%d`s). A frame anchored to `BlzGetFrameByName("InfoPanelIconHeroStrengthLabel", 6)` sits on the Strength label; `BlzCreateFrameByType("GLUETEXTBUTTON", name, gameUI, "ScriptDialogButton", 0)` works without a stock fdf; `BlzFrameClick` fires `FRAMEEVENT_CONTROL_CLICK`. `BlzFrameClick` on `ORIGIN_FRAME_COMMAND_BUTTON` frames does nothing. `BlzSendSyncData` + `BlzTriggerRegisterPlayerSyncEvent` deliver in single player.
- A summon's stats can come from its master: `BlzSetUnitMaxHP`, `SetUnitState` life, `BlzSetUnitDiceNumber/Sides` 1 and `BlzSetUnitBaseDamage(u, dmg - 1, 0)`.
- A threshold filled in lazily by a tick that returns early is 0 the whole time, and every `>=` against it is true: a first death ended a match during the pick phase that way. Initialise it where its phase is decided, or guard with `> 0`.

- In a single-player game an open dialog (`DialogDisplay`) pauses game time: timers and `TriggerSleepAction` wait until it is clicked. `GetClickedDialog()` / `GetClickedButton()` identify the click; map buttons to options with `SaveInteger(ht, GetHandleId(DialogAddButton(...)), 0, option)`.
- The unused player slots 8, 10 and 11 work as computer army owners without any `war3map.w3i` entry. After `SetPlayerAllianceStateBJ` (`bj_ALLIANCE_ALLIED_VISION` with their team, `bj_ALLIANCE_UNALLIED` with the other), `IsPlayerAlly` and `IsPlayerEnemy` answer accordingly, and units created with `CreateUnit` and ordered `IssuePointOrder(u, "attack", x, y)` march and fight.
- In a single-player run `GetPlayerName` returns `"Local Player"` for the human and `"Player N"` for empty slots, not the names in `war3map.w3i`. `SetPlayerName` works on empty slots.
- `SetUnitState(b, UNIT_STATE_MANA, 1.5)` on a building with `umpm` 20 and `umpr` 0 keeps 1.5 / 20, so a building's mana bar can show script-driven progress.
- A multiboard created from a 0.1-second timer callback (`CreateMultiboard`, `MultiboardSetItemStyle(item, true, false)`, `MultiboardSetItemWidth`, `MultiboardDisplay`) shows in the top-right corner; `MultiboardSetTitleText` every 0.5 s updates its title. `SelectUnitForPlayerSingle(u, Player(0))` from such a timer selects the unit.
- A `timerdialog` sits under the multiboard at the top right, where it is not seen; show a countdown as a line of a dialog or frame text updated by a short local timer.
- Observers: nothing in `war3map.w3i` controls them; on builds with 24 player slots the host enables observers in the lobby's game options, and an observer gets a player id of 12 or more. A loop over `0..11`, or UI code that assumes ids below 12, skips or breaks on them (return early). Not tested in a real lobby (`game_test` cannot open one).
- A fog modifier can be created stopped and switched with `FogModifierStart` / `FogModifierStop`: an area measured fogged before the start, visible while started, fogged again after the stop.
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
- **Desync rule: a `GetLocalPlayer`-dependent branch may choose a value (a model path, a text, a frame's visibility), never whether a handle is created or game state changes.** A helper that returned early on clients that could not see a point, while the others went on to `CreateGroup()`, put handle ids out of step and ended an online game in a desync. Do the handle-creating work on every client first, then branch on the local player for the value only. Before release scan every `GetLocalPlayer` branch for calls that create handles (`CreateGroup`, `CreateUnit`, `AddSpecialEffect`, timers, triggers) or change state, and make sure every frame looked up with `BlzGetFrameByName` was created for all players. A desync writes `Documents\Warcraft III\Errors\<date> <hash>\` with `Desync.txt`, `<game>_Desync.log` (only that client's checksum dump; finding the differing category needs every player's log) and the replay.

- The buff bar's order cannot be set from script: the same auras came out in a different order from run to run. Name buffs in their tooltips instead.
- `BlzGetFrameByName("ConsoleUIBackdrop", 0)` lets a frame sit beyond the 4:3 area; the client's right edge in frame units is `0.4 + 0.3 * width / height`. The command card draws over it: text below about y 0.15 at the right edge is hidden.
- StringList `%%`: in the stock strings a literal percent is `%%` only inside strings that also carry format arguments (`"(%d%% income)"`); strings without arguments write a bare `%`. An override must follow the same rule per key. An empty `StringList` value does not hide a stock line (`BONUS_ATTACK_SPEED ""` still printed the game's own line); override it with real text.

- `UnitDamageTarget(..., attack=true, ...)` does not make `BlzGetEventIsAttack()` true in a damage event; only a real swing does. Test on-hit effects keyed on the attack flag with a real attack (a paused attacker does not count either: use a live one).
- A frame dialog parented to the bare `BlzGetOriginFrame(ORIGIN_FRAME_GAME_UI, 0)` did not draw; parented to `BlzGetFrameByName("ConsoleUIBackdrop", 0)` it did.
- `DestroyEffect(AddSpecialEffect(...))` shows only a model's death animation: buff and looping models (Inner Fire, Frost Armor, Bloodlust, auras, shields) show nothing. Keep the effect about 2 s before destroying it.
- Texttags keep their screen size when the camera zooms out, so long labels run into each other: use short lines.
- A rect enter event that grants True Sight beats the engine's own detection, which lags: enemies already inside stay concealed for about 0.6 s after the entrant gains it.
- Silence and disarm both sit on `ANsi` and share the `silence` order: one dummy casting both casts the wrong one. Use a dummy caster per cast (timed life about 1 s).
- Per-spell tables keyed `index` for one group and `100 + index` for another collide once a group passes 100 entries (basics 101-108 shared keys with ultimates, so cooldowns overwrote each other; `player * 100 + item` clashed the same way). Size the stride from the largest possible index.
- `IsUnitType(u, UNIT_TYPE_STUNNED)` stays false under a dummy-cast stun; read the stun buff (`GetUnitAbilityLevel(u, 'BPSE') > 0`) instead.
- Moving the caster (`SetUnitPosition`) inside `EVENT_PLAYER_UNIT_SPELL_EFFECT` skips the ability's cooldown (the mana is still spent). Restart it from a 0 s timer with `BlzStartUnitAbilityCooldown(u, a, BlzGetUnitAbilityCooldown(u, a, level - 1))` when the remaining cooldown is 0; do not take the mana again.
- Heroes keep all their items through death and revive when every item has `idrp` 0 (`idro` 0 also stops players dropping them; selling still works).
- One very large fog modifier circle (1760) left points near its rim fogged; tile an area with smaller circles.
- Minimap creep-camp colours come from the summed creep levels of a camp: below 10 green, 10-19 orange, 20+ red (`MinimapMiddleCampThreshold` / `MinimapToughCampThreshold` in `UI/MiscData.txt`).
- A fixed race for a slot: `info_edit` `players[i].race` plus `use_custom_forces` and `fixed_player_settings_for_custom_forces`; the lobby then shows the race and does not let it change.
- `SetUnitPathing(u, false)` units stay where they were created; Ghost (`Aeth`) added by script is "no unit collision, terrain still blocks".
- `GetUnitAcquireRange` reads back the type's value after `SetUnitAcquireRange(u, 1)`, but the set works; `SetUnitAcquireRange(u, 0)` does not stop acquiring (use 1).
- Re-sending an order every tick freezes a unit (a channel restarts before it fires): compare `GetUnitCurrentOrder` first and give a spell order a deadline.
- Permanent Invisibility needs its fade time: a paused unit given it stayed visible; unpaused, it was gone after about 3.5 s.
- Hiding and showing a Locust unit (`ShowUnit`) gives it a life bar; park pooled dummies out of sight with `SetUnitX/Y` instead.
- `ReviveHero` fails (returns false) on a hero still in its death animation: check the return value and retry a second later.
- `BlzGetUnitBaseDamage` is the weapon only; the primary attribute is added on top by the game.
- A neutral shop sells a normal item to a hero with a full inventory by dropping it on the ground; a power-up (tome) is bought with a full inventory and fires the same sell event.
- A shop's Select User button keeps one of its 12 command-card cells, so a shop sells at most 11 items. Removing `Aneu` makes the shop list nothing; moving or hiding its button, or `Aall` instead, does not help (`map_validate` warns `shop_select` / `shop_slots`).
- Special effects: `BlzSetSpecialEffectPosition` left a model invisible where `BlzSetSpecialEffectX/Y/Z` did not; `BlzSetSpecialEffectScale` scales the z offset too; `BlzSetSpecialEffectTimeScale` 0 plus `BlzSetSpecialEffectTime` freezes an animation at a frame.
- Effects only some players may see: create the effect on every client with an empty model string on the screens that should not see it (same handles, no desync); per-screen `BlzSetSpecialEffectAlpha` does the same for a lasting effect.
- The engine's life bar draws over world models at its height, and no native reports that height; a UI frame cannot follow a unit reliably (the 3D viewport centre is not the screen centre), a world model attached to it can. `SetTextTagPos` keeps a number next to such a model at any zoom.
- Two blended NoDepthTest materials have no fixed draw order; `PriorityPlane` fixes it.
- **A dead hero's life can climb while it stays dead.** Adding an ability or changing an attribute of a dead hero starts its life regenerating (about 5-7 per second) while `IsUnitType(h, UNIT_TYPE_DEAD)` stays true; a revive system reading `life > 0.405` as "standing" then never revives it. Some corpses regenerated with no known cause, from the instant of death. Test death with `IsUnitType(u, UNIT_TYPE_DEAD)` wherever a corpse may have been touched, and change a dead hero's abilities and stats only after its revive. `SetUnitState(h, UNIT_STATE_LIFE, 0)` on a dead hero fires no second death and does not stop `ReviveHero` (measured), so a periodic reset is a safe net.
- Maps cannot tell a player's own order from a script order in the order events (every system that orders heroes fires them), and a click on a command-card button alone reaches no map event. To detect "the player acted", use input events: `EVENT_PLAYER_MOUSE_DOWN` (any world click, Alt+click pings too), `BlzTriggerRegisterPlayerKeyEvent` for the order hotkeys, and chat.
- A player who quits or drops has slot state `PLAYER_SLOT_STATE_LEFT`: a "played by a human" test built on the slot state hands a leaver's seat to the map's own AI with no extra code; `EVENT_PLAYER_LEAVE` is only needed to announce it.
- Move speed is capped by gameplay constants: `MaxUnitSpeed` defaults to 400 and the engine's own hard limit is 522 (measured: 522 reached with +300 bonus once the constant was raised); `MinUnitSpeed` defaults to 150, so heavy slows stop there unless it is lowered. Faster than 522 needs scripted movement. Set both with `constants_edit`.
- Locust (`Aloc`) in a unit type's abilities removes its life bar and selection, and its collision with it: put a ground pathing blocker (`YTpb`) under a Locust building that must still block. In one probe a unit enum did not return such units; keep Locust units in variables instead of looking them up (the range enum has returned Locust markers on other maps, so filter for `Aloc` too).
- A charged item with a stack size (`ista`) did not merge with a stack the hero already carried when it was picked up or given with `UnitAddItem`: merge the charges in a pickup handler.
