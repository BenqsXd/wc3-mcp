# Terrain, placed objects and models

## Coordinates and size

- A map spans `tiles × 128` world units centred on the origin (96×96: −6144..6144). The playable area is 12 tiles narrower and shorter and is **not** centred (96×96: `[-5376, -5632, 5376, 5120]`; 96×64: `[-5376, -3584, 5376, 3072]`). `placed_list` returns both under `bounds`.
- `map_new` takes sizes from 32 to 480 in steps of 32. It fills the map with the tileset's first tile, which is often dirt, not grass (`Ldrt` for Lordaeron Summer, `Adrt` for Ashenvale). Pass `fill_tile` and read `fill_tile` in the result: a road painted in the ground tile shows nothing.
- `map_new` places the start locations well inside the playable area (64×64 and 96×64, 4 players: `(±1632, 1376)` and `(±1632, -1888)`; 8 players: a ring of radius about 2336 around `(0, -256)`; 96×96, 4 players: ±2656, +2400/−2912).

## terrain_edit

- Every op is a flat object: `{"op": "paint", "tile": "Lgrs", "x": 0, "y": 0, "radius": 384}`. A nested form such as `{"paint": {...}}` fails with `bad_op`. Areas: `"x"/"y"/"radius"`, `"rect": [left, bottom, right, top]`, `"path": [[x, y], ...]` with `"width"` (roads), or **no area** for the whole map. Do not send 50 circles for what one rect or path does.
- Brushes known to work: `paint`, `noise` (`amount`, `seed`, `falloff`; over the whole map or a `rect` for gentle hills), `plateau` (a circle flattened to the height of its centre corner) and `cliff` (`{"op": "cliff", "rect": [...], "level": 3, "cliff": "CLgr"}` raises the rect one level). A new map's ground is cliff level 2 with height 0.
- Enclosed basins: a `cliff` op with `level` 3 and no area raises the whole map; later `cliff` ops with `level` 2 and a `rect` lower those rects back. The corners next to a rect edge become cliff (unwalkable). A raised strip 3 corners wide keeps two basins apart; its middle corner is walkable but unreachable.
- A map holds at most 16 ground tiles. A new map already holds all of its tileset's tiles plus 2 cliff tiles: Ashenvale (`A`) 8 tiles (8 free), Lordaeron Summer (`L`) 6 tiles, `Ldrt, Ldro, Ldrg, Lrok, Lgrs, Lgrd` (10 free). `terrain_get` and every `terrain_edit` result report the palette (`tiles`, `free`) and what the edit added (`palette_added`).
- `terrain_get area` narrower than the 128-unit corner spacing uses the nearest corner line and says so in `window.snapped`.

## Buildability

Every tile is buildable or not, walkable or not, flyable or not: `data_search kind=tile` results carry the three flags and `data_get kind=tile fields=["buildable"]` reads one.

- Unbuildable tiles that look like a good plaza or build zone: `Ybtl` Brick, `Yblm` Black Marble, `Ywmb` White Marble, `Ysqd` Square Tiles, `Lrok` Rock. Buildable: `Ldrt`, `Ldro`, `Ldrg`, `Lgrs`, `Lgrd`.
- A player's build order (`IssueBuildOrderById`) on an unbuildable tile silently does nothing — no structure, no gold spent — while `CreateUnit` still places a structure there, which hides the problem from computer-built bases.
- `terrain_edit` warns when a batch paints an unbuildable or unwalkable tile over more than a few corners.
- `terrain_get layers=["pathing"]` marks corners on unbuildable tiles with `b`; `terrain_render pathing=true` tints unbuildable ground red and unwalkable ground black.

## Derived files

Terrain edits leave pathing (`war3map.wpm`), shadows (`war3map.shd`) and minimap icons (`war3map.mmp`) stale; only a World Editor save recomputes them. While that save is owed, `map_validate` (and so `map_save`) warns with check `derived_files`. Until then `terrain_get layers=["pathing"]` and `terrain_render pathing=true` derive pathing from the current tiles, cliffs, water and blight, without doodad, destructible or building footprints; `pathing_source` says which source was used. The derived and the saved pathing agreed on every lane, grove and cliff corner compared so far.

## terrain_render

Draws tiles, height shading, water, regions, start locations, units, items, doodads (magenta), trees (dark green with a light rim, visible on dark grass) and other destructibles (orange). Look at it before launching the editor or the game.

## Placed objects

- Move a start location with `placed_edit` `{"op": "move", "ref": "start_location:N", ...}`: it also moves the player's start in `war3map.w3i` (the position the map script uses) and reports `synced`. `info_edit players[N].start` alone does not move the marker; `map_validate` warns when the two disagree.
- Useful `add` fields: `owner`, `angle`, `variation`, `scale`, `acquisition: "camp"` (creep camp behaviour, `SetUnitAcquireRange(u, 200)` in the generated script), `drops: {"sets": [[{"item": "phea", "chance": 100}]]}`.
- The World Editor clamps a doodad's or destructible's scale to its type's minimum and maximum (`dmis`/`dmas`, `bmis`/`bmas`) when it saves: `ZPsh` placed at 1.55 reads back as 1.2. `placed_edit` warns when a scale is out of range. For bigger objects, create a custom type with a higher maximum and place that.
- Placed-object refs stay stable across a World Editor save. `created` comes back as ranges in op order (`"doodad:422..909"`) plus `created_count`; doodads and destructibles share `war3map.doo`, units, items and start locations share `war3mapUnits.doo`. `verbose=true` lists every ref.
- Player 24 is neutral hostile (`Player(24)` in JASS) and 27 is neutral passive.
- Objects in `war3mapUnits.doo` exist before initialization triggers run: `main()` creates them before `InitCustomTriggers` / `RunInitializationTriggers`, so a `run_on_init` trigger can enumerate the preplaced creeps with `GroupEnumUnitsOfPlayer(g, Player(PLAYER_NEUTRAL_AGGRESSIVE), null)`.
- Batches of several hundred ops (1278 in one call) are fine.

## Missing models

Some doodad and destructible ids in the data files have no model in the installed game. They place without error and render nothing in the game; the World Editor prints `Could not load file: ...` and draws a green-and-black checkerboard cube. Known examples: `LPgp` (Grass Patch), `LSga` (Summer Grass), `YOsp` (Spider Web), `LPwh` (Wheat), `NWfp` (Floating Plank), `LOca` (Cauldron with heads). Shipped ladder maps carry some of them too.

The World Editor draws classic (SD) models, and some HD models have no classic copy: `ZPsh` (Shrub) variation 3 and `LCss` (Statue Sword) exist only in HD, so the editor cannot load them although the HD game can. The tools check both graphics modes.

- `data_search` marks these results `model_ok: false`, and `variations_ok` lists the variations that do load (`ZPsh`: `[0, 1, 2]`). `data_get` lists `model.files` and `model.missing`. Check `model_ok` before choosing decoration ids.
- `placed_edit` warns when it places one (per variation), and `scatter` uses only the variations that load.
- `map_validate` warns (check `model`) for every placed doodad, destructible or unit whose model loads from neither the game data nor the map's imports.
- Walk-through plant doodads that load on Lordaeron Summer: `ZPsh` Shrub (variations 0–2), `APct` Cattail, `LPcr` Corn, `ZPfw` Flowers, `ZPf0` Tulips. `XOcl` Magical Lantern, `LTlt` Summer Tree Wall and `YTct` Cityscape Summer Tree Wall also load. `LTlt` is the only tree of Lordaeron Summer (`data_search kind=destructible query=Tree tileset=L` lists it and two tree bridges); there is no `LTlf`.
