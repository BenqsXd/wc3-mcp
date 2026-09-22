# Terrain, placed objects and models

## Coordinates and size

- A map spans `tiles × 128` world units centred on the origin (96×96: −6144..6144). The playable area is 12 tiles narrower and shorter and is **not** centred (96×96: `[-5376, -5632, 5376, 5120]`; 96×64: `[-5376, -3584, 5376, 3072]`). `placed_list` returns both under `bounds`.
- `map_new` takes sizes from 32 to 480 in steps of 32. It fills the map with the tileset's first tile, which is often dirt, not grass (`Ldrt` for Lordaeron Summer, `Adrt` for Ashenvale). Pass `fill_tile` and read `fill_tile` in the result: a road painted in the ground tile shows nothing.
- The playable area is inset 6 tiles on the left and right, 4 at the bottom and 8 at the top (`camera_complements` 6, 6, 4, 8): 64×64 `[-3328, -3584, 3328, 3072]`, 128×128 `[-7424, -7680, 7424, 7168]`. Nothing walks outside it (the editor's pathing marks it unwalkable).
- `map_new` places the start locations well inside the playable area (64×64 and 96×64, 4 players: `(±1632, 1376)` and `(±1632, -1888)`; 96×96, 4 players: ±2656, +2400/−2912). The 8-player ring scales with the map: radius about 2336 around `(0, -256)` on 64×64; on 128×128 `(±3680, 3424)`, `(0, 4928)`, `(±5184, -256)`, `(±3680, -3936)`, `(0, -5440)`.

## terrain_edit

- Every op is a flat object: `{"op": "paint", "tile": "Lgrs", "x": 0, "y": 0, "radius": 384}`. A nested form such as `{"paint": {...}}` fails with `bad_op`. Areas: `"x"/"y"/"radius"`, `"rect": [left, bottom, right, top]`, `"path": [[x, y], ...]` with `"width"` (roads), or **no area** for the whole map. Do not send 50 circles for what one rect or path does.
- Brushes known to work: `paint`, `noise` (`amount`, `seed`, `falloff`; over the whole map or a `rect` for gentle hills), `plateau` (a circle flattened to the height of its centre corner) and `cliff` (`{"op": "cliff", "rect": [...], "level": 3, "cliff": "CLgr"}` raises the rect one level). A new map's ground is cliff level 2 with height 0.
- Enclosed basins: a `cliff` op with `level` 3 and no area raises the whole map; later `cliff` ops with `level` 2 and a `rect` lower those rects back. The corners next to a rect edge become cliff (unwalkable). A raised strip 3 corners wide keeps two basins apart; its middle corner is walkable but unreachable.
- Neighbouring corners (diagonals included) stay at most **2 cliff levels** apart: the World Editor enforces it when it loads a map, and `terrain_edit` does it first so both agree. An op's own corners keep the level asked for and the corners around them step, which the result reports per op under `cliffs` (`corners` set, `blended` moved). Carve the width you want - a rect carved to level 2 inside level-7 rock is walkable to its own edge, and a 2-tile doorway stays open. Terrain written before 1.3 keeps steeper steps until the next `terrain_edit`, which lowers them and warns.
- Cliff levels more than one step apart render as stacked cliff faces (level 2 inside 7: 640-unit walls). `CDdi` (Natural Walls) glows with lava cracks, `CDsq` (Manmade Walls) is carved stone. A lava or crack tile on the rock tops animates and is unreachable, a cheap way to break up a large rock mass.
- `ramp` works across a two-level step when its rect covers the whole blended slope band (a level-4 shelf in a level-2 basin; it worked on 3 of 4 level-6 shelves), and it moved `layout_check` `reach.share` from 0.565 to 0.768 on a map with stranded shelves. A later `cliff` carve through a ramp removes it silently: apply ramps after all cliff work.
- Dungeon (`D`): tiles `Ddkr`, `Ddrt`, `Dbrk`, `Drds`, `Dlvc`, `Dlav`, `Dgrs`, `Dsqd`, cliffs `CDdi`, `CDsq`; a new `D` map holds all 8 (8 slots free). Only `Ddrt` is buildable; the rest are walkable but unbuildable. Black Citadel `Ksmb` (Small Bricks) and `Kfst` (Flat Stones) are buildable and read as dark dungeon floor, so a build zone can be marked with the tileset alone. `Oaby` (Outland Abyss) is neither walkable nor buildable. `ridge` with `cliff: 5` and `cliff_tile: "CDdi"` makes rock spines that block movement without doodads.
- Icecrown (`I`): tiles `Idrt`, `Idtr`, `Idki`, `Ibkb`, `Irbk`, `Itbk`, `Iice`, `Ibsq`, `Isnw`, cliffs `CIsn`, `CIrb`. `Idki`, `Idtr` and `Ibkb` render very dark (a map on `Idki` reads almost black); `Iice` is the neutral base. No fog doodad: `IRrs` Snowy Rock and `LOsm` Smoke Smudge stand in. Bridges `YT00`-`YT11`, Icy Gates `ITg1`-`ITg4`.
- A map holds at most 16 ground tiles. A new map already holds all of its tileset's tiles plus 2 cliff tiles: Ashenvale (`A`) 8 tiles (8 free), Lordaeron Summer (`L`) 6 tiles, `Ldrt, Ldro, Ldrg, Lrok, Lgrs, Lgrd` (10 free), Sunken Ruins (`Z`) 9 tiles (7 free). `terrain_get` and every `terrain_edit` result report the palette (`tiles`, `free`) and what the edit added (`palette_added`). Tiles of other tilesets can be painted too (`Ybtl` on an `L` map); each takes a slot.
- Sunken Ruins (`Z`) is the jungle tileset: `Zdrt`, `Zdtr`, `Zdrg`, `Zbks` (unbuildable), `Zsan`, `Zbkl` (unbuildable), `Ztil` (unbuildable), `Zgrs`, `Zvin` Dark Grass; cliffs `CZdi` Dirt, `CZlb` Ruined Walls; trees `ZTtw` Ruins Tree Wall and `ZTtc` Ruins Canopy Tree (`ZPtw` is an indestructible doodad version).
- `heightmap` brush: `{"op": "heightmap", "source": "<16-bit grayscale PNG>", "rect": [-8192, -8192, 8192, 8192], "amount": 800, "base": -400, "mode": "set"}` sets each corner to `base + amount × pixel / 65535`, one pixel per corner (129×129 for a 128×128 map), first row = north edge. Values are heights relative to the cliff level, so after `cliff` ops in the same batch a mesa reads the designed relative heights. `terrain_render heightmap="height"` exports the same format and names its `base`/`amount` in the text after the picture.
- `quiet=["tile_pathing"]` drops the unbuildable-tile warnings on a scenery map where nothing is built.

## Water and heights

- `terrain_get` `height` is relative to the corner's cliff level: ground z = height + (cliff_level − 2) × 128, so an untouched level-3 corner reads 0. Water levels are absolute z (the drawn surface): on a level-3 mesa, `level: 100` floods the corners whose relative height is below −28.
- The `water` op sets the level on every corner of its area; corners whose ground is above it stay dry, so one band over land and river floods only the low ground. Levels are stored in quarter units (`-40` reads back as −40.1); every water op's result names the stored `level`, the `depth` range and `deep_corners`.
- **Depth decides walkability.** Water up to about 52 deep is wadeable (walkable, unbuildable); deeper than about 53 stops ground units. The editor's own pathing flips between 52 and 56 (measured over the shipped maps: flat water ≤ 51.95 deep always walkable, ≥ 56.4 never; a World Editor save read 47.9 walkable and 63.9 not). In the game, footmen crossed fords about 30 deep and stopped at the bank of a channel about 220 deep. Outland water stops them at any depth.
- `terrain_get` pathing, `terrain_render pathing=true`, `map_flow`, `layout_check` and `map_validate reachable` all count deep water as unwalkable.
- `river` brush: `water_level` fixes the surface; without it a river that starts in standing water (another river, a lake) takes that water's level (`joined` in the result), else the surface sits a quarter of `depth` below the lowest ground it crosses. `walkable: false` keeps a channel at least 69 deep along the middle (a barrier; prove it with `map_flow` origins/targets), `walkable: true` keeps it all at most 40 deep (a ford). Carving with `"water": false` and setting the level with a `water` op also works.
- `terrain_get area` narrower than the 128-unit corner spacing uses the nearest corner line and says so in `window.snapped`.
- A `terrain_edit` brush area narrower than the corner spacing does the same since 1.4 (the result lists the ops under `snapped`) instead of failing with `bad_value`.
- **Derived pathing was calibrated against the editor on 2026-09-22** and now agrees with an editor-saved `war3map.wpm` on about 99.95 % of the cells of a carved Dungeon map with a river, a dry crossing and a two-tile doorway. The rest is a handful of cells at a sloping shore that the editor blocks and the tools allow, so the derived reading errs on the permissive side at a waterline and nowhere else. The earlier "a crossing the tools read as 320 wide came back closed" report was that defect: the tools judged a cell by the water depth at its centre, the editor by the cell's shallowest point. Natural bridges (`YT04`) still add no walkable ground. A crossing the map depends on is still worth an editor save (`editor_map open` + `save`) and a `map_flow` check, and `map_flow` carries a `warning` while the pathing it used is derived.

## Buildability

Every tile is buildable or not, walkable or not, flyable or not: `data_search kind=tile` results carry the three flags and `data_get kind=tile fields=["buildable"]` reads one.

- Unbuildable tiles that look like a good plaza or build zone: `Ybtl` Brick, `Yblm` Black Marble, `Ywmb` White Marble, `Ysqd` Square Tiles, `Lrok` Rock. Buildable: `Ldrt`, `Ldro`, `Ldrg`, `Lgrs`, `Lgrd`.
- A player's build order (`IssueBuildOrderById`) on an unbuildable tile silently does nothing — no structure, no gold spent — while `CreateUnit` still places a structure there, which hides the problem from computer-built bases.
- `terrain_edit` warns when a batch paints an unbuildable or unwalkable tile over more than a few corners (`quiet=["tile_pathing"]` silences it).
- `terrain_get layers=["pathing"]` marks corners on unbuildable tiles with `b`; `terrain_render pathing=true` tints unbuildable ground red and unwalkable ground (deep water included) black.

## Derived files

Terrain edits leave pathing (`war3map.wpm`), shadows (`war3map.shd`) and minimap icons (`war3map.mmp`) stale; only a World Editor save recomputes them. While that save is owed, `map_validate` (and so `map_save`) warns with check `derived_files`. Until then `terrain_get layers=["pathing"]` and `terrain_render pathing=true` derive pathing from the current tiles, cliffs, water and blight, without doodad, destructible or building footprints; `pathing_source` says which source was used. On the shipped maps the derived 32-unit cells disagree with the editor's in 0.2 % of cells (mostly bridges, which make water walkable).

## terrain_render

Draws tiles, height shading, water, regions, start locations, units, items, doodads (magenta), trees (dark green with a light rim, visible on dark grass) and other destructibles (orange). Look at it before launching the editor or the game. `area: [left, bottom, right, top]` draws only that part (whole tiles, up to 16 px per tile) for a close look at a town; the text after the picture names the rectangle drawn.

## Placed objects

- Move a start location with `placed_edit` `{"op": "move", "ref": "start_location:N", ...}`: it also moves the player's start in `war3map.w3i` (the position the map script uses) and reports `synced`. `info_edit players[N].start` alone does not move the marker; `map_validate` warns when the two disagree.
- Useful `add` fields: `owner`, `angle`, `variation`, `scale`, `acquisition: "camp"` (creep camp behaviour, `SetUnitAcquireRange(u, 200)` in the generated script), `drops: {"sets": [[{"item": "phea", "chance": 100}]]}`.
- The World Editor clamps a doodad's or destructible's scale to its type's minimum and maximum (`dmis`/`dmas`, `bmis`/`bmas`) when it saves: `ZPsh` placed at 1.55 reads back as 1.2. `placed_edit` warns when a scale is more than 0.01 out of range (`JScs` has a fixed 1.095; 1.09 passes). For bigger objects, create a custom type with a higher maximum and place that.
- Placed-object refs stay stable across a World Editor save. `created` comes back as ranges in op order (`"doodad:422..909"`) plus `created_count`; doodads and destructibles share `war3map.doo`, units, items and start locations share `war3mapUnits.doo`. `verbose=true` lists every ref.
- Player 24 is neutral hostile (`Player(24)` in JASS) and 27 is neutral passive.
- Objects in `war3mapUnits.doo` exist before initialization triggers run: `main()` creates them before `InitCustomTriggers` / `RunInitializationTriggers`, so a `run_on_init` trigger can enumerate the preplaced creeps with `GroupEnumUnitsOfPlayer(g, Player(PLAYER_NEUTRAL_AGGRESSIVE), null)`.
- Large batches are fine: 6133 destructibles in one `add` op (`columns`/`rows` from `ops_file`), 1924 doodads plus 57 units in one call.
- When its area cannot hold `count` objects, `scatter` places fewer and only warns (`placed 142 of 160; ...`): read the warnings, not only `created_count`.
- Critters (`urac` critter, collision 16): `nfro`, `nskk`, `ncrb`, `nhmc`, `nrat`, `nrac`, `nder`, `npig`, `nech`, `nalb`, `nvul`, `ndog`, `nsea`, `nshe`; townsfolk `nvil`, `nvl2`, `nvlw`, `nvlk`, `nvk2`. Place them with `owner: 27`.

## Footprints and walls

- A placed object blocks the cells of its pathing texture (`data_get fields=["dptx"]` for doodads, `bptx` destructibles, `upat` units; one pixel = one 32-unit cell). The texture turns with a doodad or destructible in quarter turns (its top row faces north at 270°); buildings never turn theirs.
- No footprint: `ZPsh`, `ZPfw`, `ZPf0`, `APms`, `LOtz`, `LOrb`, `ZOsh`, `ZZgr`, `LOsm`, `YOms`, `YOm1`, `ASpr`, `ZCv1`/`ZCv2`, water doodads and ambient effects (`AObd`, `LOfl`, `NObt`). 2×2: `APbs`, `ZPvp`, `ZPms`, `APtv`, `ZOrp`, `ZObz`, `LObz`, `XOcl`, `AOnt`, `BOtt`, `BOct`, `LOss`, `LOsh`, `YOec`, `LOwp`, `LOam`. 4×4: `ZRrk`, `ARrk`, `ZRsp`, `ZOss`, `ZOst`, `ZOsb`, `ZOob`, `AOob`, `AOhs`, `NOfp`, `NOfg`, `LOsk`, `LOce`, `LOct`, `DOjp`, `ZOfp`, `LSwl`, `ZOrt`. Larger: `AOlg` 12×6, `ZSrb` 6×8, `ZOfo`/`ZOrc`/`NRwr` 8×8, `SA02`/`LZth` 12×12, `ASv0/1/3/4` 8×8Round (`ASv2` 4×4), `ZSas`/`ZSar` CityArch. `JOgr` and `XOmr` use `2x2Unbuildable` (blocks building only).
- Trees: `4x4Default` (a solid 128×128 square: `ZTtw`, 10 variations, scale 0.65–1.05) and `2x2Default` (`ZTtc`, `ATtc`). Two 4×4 trees 192 apart leave a 64-unit gap that small units walk through.
- A tree wall units could not pass: `ZTtw` at Poisson-disk spacing 100, then a fill pass adding a tree wherever a point is farther than 96 from every tree; footmen ordered 1000–1900 units into it all stopped at its edge.
- **Prove a wall closed** with `map_flow` `origins`/`targets` (points, region names, `"start:N"`): it works on the game's 32-unit cells, and `sealed: true` means no target is reachable. A leak comes back with `gap` (the narrowest width on the way) and `gap_at` (the hole). The start-to-start numbers of plain `map_flow` and `map_validate reachable` use the coarser 128-unit corner grid, where any footprint touching a corner blocks it: a start 130 units from a 4×4 doodad warns `reachable` there.

### Gates and fixed rotation

Types with a fixed rotation (`dfxr`/`bfxr` of 0 or more: trees at 270, `DTg1` 270, `DTg3` 0, ...) always stand at that angle; the World Editor rewrites any other angle, and since 1.4 `placed_edit` does too (it warns once per type when an angle was given). All 364,674 placed doodads and destructibles of that kind in the shipped maps stand at their fixed angle. A line of `DTg1` gates at 256 spacing sealed a gateway in `map_flow`. There is no "vertical gates need 128 spacing" rule: the old advice came from the footprint turning with an angle the game never uses. Prove each gate line with `map_flow` origins/targets before and after placing the gates ("opens when not gated", "seals when gated").

### Gaps, blocking and non-blocking copies

- A gap of 64 or 96 is a wall for a hero (collision above 16); treat anything under about 128 as closed. `layout_check` reports `narrowest`: the tightest free width on the shortest walk between two start locations.
- `data_search` shows `pathing` (the texture) and `blocks` (whether it stops walking) for every doodad and destructible, and `placed_edit` `scatter`/`cluster` warn when the types they placed block walking.
- A copy of a blocking doodad with `dptx` `"_"` keeps the look without the footprint (260 scattered copies changed no corridor width). `LOsm` has no footprint and `dmis`/`dmas` 0.8-1.2; a custom copy with a wider range places it bigger.
- More `4x4Default` footprints: `BRsp`, `ZRbs`, `BRrk`, `ORrr` (a scatter of 220 of them cut 512-wide corridors to 32-128). Dungeon props: 4x4 `DRrk`, `DRst`, `DOtp`, `DOim`, `DOtt`, `DOtb`, `YOth`; 2x2 `DOmc`, `DOme`, `DOkb`, `DObk`, `DOsv`; `DObw` 4x2; `DRfc` 6x6; `DOas` 8x8; `LOwf` 12x12WallFountain; nothing: `DOsw`, `ZZcd`, `ZZdt`, `DOch`, `DOlc`, `YOfb`. `DSar`/`DSah` archways (CityArch) leave a 96-unit slit: keep them out of walkways; two obelisks (`DOob`) beside an opening frame it without blocking.
- A `line` op along a polyline places props straight across every branch that leaves it, and two 4x4/2x2 props facing each other leave about 96: `exclude` the junctions.
- Placed units take `scale` directly (a boss at 2.6 needs no custom type).
- `map_validate reachable` names the players whose start a shop or building within about 150 units boxed in.
- `layout_check` `reach.share` around 0.84 is normal with deliberate rock walls (cliff tops are walkable but unreachable); read `narrowest` for the gaps.
- `terrain_render pathing=true` and `map_flow` are the floor test: probing 15 candidate points in one `map_flow` origins/targets call beats reading cliff levels. Rotations of a verified point on rot90-symmetric terrain are walkable too; mirror images are not.

## Mirroring

`{"op": "mirror", "axis": ...}` runs on `terrain_edit` and on `placed_edit`. `x` reflects the x coordinate (a left-right mirror), `y` the y coordinate; `point`/`rot180`, `rot90` and `rot270` rotate around the centre. `rot4` fills the other three quadrants from one source (three quarter turns of the same untouched quadrant), which is what a four-fold map needs - three separate rotations read ground the earlier ones had already written. A mirror whose image overlaps its own source is refused with `bad_value`: give a `from` that ends at the centre, or leave `from` out for the half or quadrant the axis implies.

## Missing models

Some doodad and destructible ids in the data files have no model in the installed game. They place without error and render nothing in the game; the World Editor prints `Could not load file: ...` and draws a green-and-black checkerboard cube. Known examples: `LPgp` (Grass Patch), `LSga` (Summer Grass), `YOsp` (Spider Web), `LPwh` (Wheat), `NWfp` (Floating Plank), `LOca` (Cauldron with heads). Shipped ladder maps carry some of them too.

The World Editor draws classic (SD) models, and some HD models have no classic copy: `ZPsh` (Shrub) variation 3 and `LCss` (Statue Sword) exist only in HD, so the editor cannot load them although the HD game can. The tools check both graphics modes.

- `data_search` marks these results `model_ok: false`, and `variations_ok` lists the variations that do load (`ZPsh`: `[0, 1, 2]`). `data_get` lists `model.files` and `model.missing`. Check `model_ok` before choosing decoration ids.
- `placed_edit` warns when it places one (per variation), and `scatter` uses only the variations that load.
- `map_validate` warns (check `model`) for every placed doodad, destructible or unit whose model loads from neither the game data nor the map's imports.
- More `model_ok: false` ids: `NWfl`, `YObo`, `YOtc`, `YOpb`, `YOsc`, `YOol`, `YOhz`, `UOvf`, `YOs1`/`YOs2`, `YCwa`, `YCda`..`YCdg`, `YCbd`, `YCbr`, `YCbf`, `ZOba`, `EMt0`, `ET00`, `EW00`, `LOmp`, `LCsd`, `LCsx`, `LCsb`, `LFgs`, the `LCb*` banners, most Standing Banners, `LOlp`/`YOlp` post lanterns (`LOlp` variations 0–1 load).
- Jungle dressing that loads: `ZPvp`, `ZPms`/`APms`, `APbs`, `APtv`, `OPop`, `ZPru`/`APct`, lily pads `ZPlp`/`AWlp`/`AWfl`, `ZWsw` seaweed (scale 1.5–2.0), fish `ZWfs`/`AWfs`/`ZWsf`, `ZWbg` bubbles, rocks `ZRrk`/`ARrk`, spires `ZRsp`/`ZRrs`, logs `AOlg`/`AOla`, `AOhs` stump; ruins `ZOst`, `ZOsb`, `ZOss`, `ZOob`, `ZOrp`, `ZSrb`, `ZSar`, `ZSas`, `ZObz`, `ZOfp`, `ZOfo`, `ZOrt`, `ZOrc`, `SA02`, `JScs`; `ZCv1`/`ZCv2` cliff vines, `LWw0` waterfall, `ASpr` pier, `NWrd` rowboat, `AObd` birds, `LOfl` flies, `NObt` bats. No doodad is named Tent, Fern or Troll.
- Camp and village props that load: `NOfp`, `NOfg`, `NOft`, `BOtt`, `BOct`, `LOss`, `LOsh`, `LOsk`, `LOtz`, `LOwp`, `LOam`, `LOce`, `LOct`, `DOjp`, `LOt1`, `NRwr`, `NObo`, `BObo`, `LOrb`, `LOsm`, `ASv0`–`ASv4` fishing village, `LZth` Thrall's Hut, `YOms`/`YOm1` stalls, `YOec` crates, `LOch` hay cart, `LSwl` well, `VOfl`/`NOfl` fences, `AOnt` totem lantern, `JOgr` Glowing Runes, `XOmr` Magical Runes.
- Walk-through plant doodads that load on Lordaeron Summer: `ZPsh` Shrub (variations 0–2), `APct` Cattail, `LPcr` Corn, `ZPfw` Flowers, `ZPf0` Tulips. `XOcl` Magical Lantern, `LTlt` Summer Tree Wall and `YTct` Cityscape Summer Tree Wall also load. `LTlt` is the only tree of Lordaeron Summer (`data_search kind=destructible query=Tree tileset=L` lists it and two tree bridges); there is no `LTlf`.

## Scenery that looks placed

`placed_edit` has generator ops that build a layout instead of a heap. All of them are seeded and deterministic, take the placement fields of their kind (owner, scale, ...) plus `exclude`, `where` and `seed`, and keep off water, cliffs and the map boundary. Use them instead of `scatter` whenever the result is meant to look like part of the world; `scatter` stays for "sprinkle N of these anywhere".

- **`forest`** — trees at Poisson-disk spacing, thinner toward the edge of the area and around clearings. `spacing` is the distance between trees at full density, `density` (0-1) scales it, `edge` is how far in from the border the wood thins, `clearings`/`clearing_radius` punch holes, `on_tiles` keeps it to the right ground. Run it twice for a canopy plus underbrush: the same area, doodads instead of destructibles, lower density and a wider `edge`.
- **`line`** — objects at an even spacing along a `path`: `offset` from the line, `sides` (`both`, `left`, `right`, `alternate`, `center`), `face` (`path`, `out`, `in` or an angle) and `jitter` for a hand-placed wobble. Fences, lamp rows, docks, market stalls.
- **`town`** — a street grid: a row of buildings along every block side, set back by `margin`, `spacing` apart, each facing its street, with `props` between them and the block middles left as yards. `fill` below 1 leaves gaps (and puts a prop in the gap), `plaza` keeps an area open. The result's `streets` are polylines for `terrain_edit` to pave.
- **`cluster`** — a clump that is dense in the middle and thins out, with `scale_range` shrinking the objects toward the rim. Rocks, rubble, flower beds.
- **`clear`** — delete what is in an area (`rect`, circle or `path` with `width`) before a road or a building site goes in.

A road is three ops: `terrain_edit` `{"op": "paint", "path": [...], "width": ...}` for the ground, `placed_edit` `clear` along the same path, then `line` for the lanterns. Paint the verge with a second, wider paint op in a different tile.

`layout_check` then reports what a top-down render cannot show: the nearest-neighbour spacing (`min`, `p10`, `median`, `mean` and `spread`, the coefficient of variation — near 0 is a grid stamp, 0.15-0.45 reads as hand-placed, above 0.6 as random clumps), how many objects stand on water or on ground no unit can stand on (with `reasons` per kind: `deep_water`, `shallow_water`, `cliff`, `boundary`, `unwalkable_tile`, `outside_playable`, so trees in shallow water on purpose are told apart from mistakes), which tiles they ended up on, and how much of the walkable map the start locations still reach. `map_validate` reports the same reachability as a warning when decoration walls something off.

For the look itself: `terrain_render` from above, and `game_test screenshots=N screenshot_every=S` with `ProbeCamera(x, y, distance, seconds)` in the probe code to walk the camera over the scenery and photograph it in the game.
