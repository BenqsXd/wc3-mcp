# Building a map to order

There are no map templates in these tools, on purpose: a map the user asked for should be that map, not a skeleton with their words pasted on. What the tools give instead are pieces that compose — terrain brushes, scenery generators, the mirror op, object data, script recipes — plus checks that say whether the result works. This file is the order to use them in, and what to check between the steps.

## 1. Read the request as a map

Before any call, decide and say back in one or two lines:

- **Genre and rules.** Melee, tower defence, arena, survival, campaign scene, cinematic. What ends the game.
- **Players.** How many, how they are grouped, which slots are computers.
- **Size and tileset.** A lane map wants length (96×64 or 128×96), an arena wants a square, a melee map wants the ladder proportions. `map_new` sizes go 32 to 480 in steps of 32; the tileset letter fixes the palette (`data_search kind=tile tileset=L`).
- **The shape of the play space.** Where players start, where they fight, what separates them.

Anything the user did not say and the map cannot do without, choose and state the choice. Do not ask about details their answer would not change.

## 2. Terrain first, in layers

The ground decides everything after it, so build it in passes and look after each one.

1. `map_new` with the size, tileset, player count and an explicit `fill_tile` (the tileset's first tile is usually dirt, which makes a dirt road invisible).
2. Shape: `noise` over the whole map for texture, then `ridge`, `plateau` and `cliff` for the bones of the place, then `erosion` so nothing looks like a cone, then `terrace` where the map wants fields or quarries.
3. Water: `coast` from a waterline for a shore, `river` along a path for a river with banks. Both paint their own tiles when you name them.
4. Ground: `paint` the large areas, `paint` a `path` for roads, then `blend` the seams between two tiles so they read as transitions.
5. Symmetry: build **one** half or quadrant well, then `mirror` it. For a four-quadrant map use `axis: "rot4"` over the finished quadrant, which fills the other three from that one source; for a two-fold map mirror the finished half (`x` or `y`). Mirroring the still-empty half copies emptiness, and a mirror whose image overlaps its own source is refused.

Check as you go: `terrain_render` for the look, `terrain_get format="summary"` for the numbers (height range, tile counts), `terrain_render heightmap="height"` when a height field needs studying or reusing.

## Carving a path network

For a map that is corridors and rooms rather than open ground, carve instead of building up:

1. Raise the whole play area to one solid rock level (`cliff` with no area, `level` 6 or 7).
2. Carve the path graph down with `cliff` `path` ops plus `width` at the floor level. Path strokes already have round joins and round caps, so a bend needs no circle at its vertex.
3. Carve rooms as circles hanging off that graph.
4. One World Editor round trip (`editor_map open` + `save`), then verify with `map_flow` against the saved `war3map.wpm` before any camp or scenery goes in.

Carve first, decorate after: the opposite order took a dozen editor round trips on the dungeon map. Sizing: the default camera shows about 1800-2000 units of ground, so a path wider than about 1000 fills the screen and stops reading as a path, while 600-800 reads as a corridor with both walls visible. A ring-and-spoke graph has no dead ends by construction, and alcoves hung off it read as clearings. Decoration inside an alcove or on a 640-wide path has to be non-blocking (`data_search` `blocks`).

## 3. Scenery that reads as placed

Never `scatter` what should look designed. Use the generators, and give each one the ground it belongs on (`on_tiles`), the places it must avoid (`exclude`) and a `seed`.

- Woods: `forest` for the canopy, then a second `forest` of doodads with a lower `density` and a wider `edge` for the underbrush.
- Roads: `terrain_edit paint` along the path, `placed_edit clear` along the same path, then `line` for the lanterns or fences.
- Towns: `town` for blocks whose houses face their streets, then pave the `streets` it returns.
- Detail: `cluster` for rocks, rubble and flower beds, `line` for docks, walls and market rows.

Then `layout_check`: spacing spread near 0 means a grid stamp, 0.15–0.45 reads as hand-placed; it also reports objects on water or unwalkable ground, and how much of the map the starts still reach.

## 4. Objects, then the systems

- `data_search` / `data_get` for the ids and their real fields — never guess one. `data_get kind=native` for a JASS signature.
- `objdata_edit` for the units, items and abilities the map needs; `balance_report` afterwards, which puts each custom object beside the stock objects of the same price and flags a ratio far outside theirs.
- `script_recipe` for the systems that are the same in every map — damage detection, a unit indexer, respawns, waves, a scoreboard, a hero tavern, quests, camera setup, a cinematic. They arrive compiling, as `triggers_edit` ops, and can be edited before they go in. Everything that is specific to *this* map is written by hand as a script trigger, in the order the tree emits it (helpers first).
- `strings_edit` for text, so names and tooltips live in the string table and can be renamed or translated in one call.
- `sound_add` for audio, `ui_edit` for a custom panel.

## 5. Check before launching the game

In this order, because each catches what the next would waste a launch on:

1. `script_validate lint=true` — leaks, event data after a wait, dead triggers, endless loops, use-after-destroy, reserved names, `GetLocalPlayer` desyncs.
2. `map_validate` — cross-file errors, command cards, locked abilities, order strings, ability order clashes, ground a player cannot reach.
3. `map_flow` — walking distances between starts, to mines and expansions, the chokes on the way, pockets nobody reaches.
4. `melee_check` — for a melee map only, the shipped melee maps' own ranges.
5. `layout_check` — the scenery numbers again, after everything is in.
6. `map_save`, then `editor_map open` + `save` once, so pathing, shadows and the minimap match the terrain.

## 6. Then the game

One `game_test` run holds many checks. Write the probe code so it answers with verdicts: `ProbeExpect(name, condition)` for each rule the map must obey, `ProbeCountEvent` for events, `ProbeStartAI` for an opponent, `ProbeGold` to pay for what the test builds, `ProbeCamera` plus `screenshots=N` to look at the scenery in the game. Use `wait=false` and keep editing while it runs.

## What to do when the user asks for "a map like X"

Build the thing, not a copy of a skeleton: choose the size and tileset from what the genre needs, lay the terrain for the specific layout they described, place the scenery with the generators, and reach for a recipe only where the system is genuinely generic. Two maps of the same genre should not come out looking alike — the seeds, the terrain passes and the layout are where the map's character lives.
