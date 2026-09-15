# Phase 4: World Content Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline; the user asked for no subagents after spend-limit failures). Steps use checkbox (`- [ ]`) syntax. Byte layouts below were verified on 556 local maps (CASC campaigns + ladder/melee maps) on 2026-09-15; tasks give interfaces, behaviour and tests, and the code is written test-first during execution.

**Goal:** Read and edit regions, cameras, sounds, placed units/items/doodads/destructibles and terrain of a map through MCP tools, byte-exact for untouched data, with the editor-generated script sections kept in sync for JASS maps.

**Architecture:** New codecs in `wc3mcp.formats` (`w3r`, `w3c`, `w3s`, `doo`, `unitsdoo`, `w3e`, `wpm`, `mmp`), JSON views and batch edits in `wc3mcp.ops` (`elements.py`, `placed.py`, `terrain.py`), script sections in `wc3mcp.script.world` spliced by `script.build`, tools in `server.py`. Derived files the editor recomputes on save (`war3map.wpm` pathing, `war3map.shd` shadows, `war3map.mmp` minimap icons, Lua scripts) are left alone and reported as stale; `editor_map` open + save refreshes them.

**Tech Stack:** Python 3.13 Store interpreter, stdlib struct/dataclasses, Pillow for `terrain_render`, FastMCP `Image`.

**Spec:** `docs/superpowers/specs/2026-09-14-wc3-mcp-design.md` (section 4 "Terrain (3)", "Placed objects (2)", "Regions/cameras/sounds (2)"; section 5 script rebuild rule; build phase 4).

## Global Constraints

- `$PY = "%LOCALAPPDATA%\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\python.exe"`; branch `phase4-world-content` stacked on `phase3-editor-driver`; no push/merge until all phases are done.
- Codecs: `parse(bytes) -> model`, `serialize(model) -> bytes`, `FormatError` on bad data or unsupported versions; every corpus sample map round-trips byte-exact; writes keep the file's own version.
- Edits are all-or-nothing batches raising `ToolError(code, message, hint, **details)`; unchanged files are not rewritten.
- The install is read-only; the scratch corpora under the session scratchpad are never committed.
- Commits end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`; stage explicit paths.

## Verified layouts (little-endian; cstr = NUL-terminated UTF-8; id = 4 bytes)

- **war3map.w3r** v5/v7: `i32 version, i32 count`, per region `f32 left, bottom, right, top; cstr name; i32 index; id weather (0 = none); cstr ambient sound; u8 b, g, r, 0xFF`; v7 adds 8 bytes (always zero). Script: `set gg_rct_<script name> = Rect( left, bottom, right, top )`.
- **war3map.w3c** v0/v3: `i32 version, i32 count`, per camera v0 `13 f32: x, y, z_offset, rotation, angle_of_attack, distance, roll, field_of_view, far_z, near_z, local_pitch, local_yaw, local_roll; cstr name`; v3 `16 f32` (adds depth_of_field_distance, depth_of_field_scale, z_absolute) `, cstr name, i32 camera_type`.
- **war3map.w3s** v3 (only version seen): `i32 version, i32 count`, per sound `cstr name, path, eax; u32 flags; i32 fade_in, fade_out, volume; f32 pitch, pitch_variance; i32 priority, channel; f32 min_distance, max_distance, distance_cutoff, cone_inside, cone_outside; i32 cone_outside_volume; f32 cone_x, cone_y, cone_z; cstr name2 (= name), label, path2 (= path); i32 dialogue_text_key (-1 none); cstr unknown_s1; i32 dialogue_speaker_key; cstr unknown_s2; i32 unknown_i1; cstr speaker_unit, facial_animation_label, facial_animation_group_label, facial_animation_set_path; i32 unknown_i2`.
- **war3map.doo** (8, 11), (12, 11), (13, 11): `"W3do", i32 version, i32 subversion, i32 count`; per doodad `id; i32 variation; f32 x, y, z, angle, scale_x, scale_y, scale_z; id skin; [v12+ i32 always -1]; u8 flags; u8 life; i32 item_table; i32 set_count, sets of (i32 count, (id item, i32 chance)*); [v13+ i32 always -1]; i32 editor_id; [v12+ i32 0, i32 0, i32 n, n × 36-byte entries (colour-bearing, meaning unknown)]`; then `i32 special_version (0), i32 count, (id, i32 z, i32 x, i32 y)*` for cliff/terrain doodads.
- **war3mapUnits.doo** (8, 9), (8, 11), (12, 9), (12, 11), (13, 9), (13, 11): header as doo; per unit `id; i32 variation; 7 f32; id skin; [v12+ i32 -1]; u8 flags; i32 owner; u8 unknown_a; u8 unknown_b; i32 hp (-1 default); i32 mp; [sub 11: i32 item_table]; item sets as doo; i32 gold; f32 target_acquisition (-1 normal, -2 camp); i32 hero_level; [sub 11: i32 strength, agility, intelligence]; i32 count, (i32 slot, id item)*; i32 count, (id ability, i32 autocast, i32 level)*; i32 random_flag: 0 → 4 bytes (3-byte level, u8 item class), 1 → i32 group, i32 position, 2 → i32 count, (id, i32 chance)*, other values carry no data; i32 color (-1); i32 waygate (-1 none, else region index); i32 editor_id; [v12+ i32 0, i32 0, i32 0]`.
- **war3map.w3e** v11/v12: `"W3E!", i32 version, u8 tileset, i32 custom_tileset, i32 n + n tile ids, i32 n + n cliff ids, i32 width, i32 height, f32 offset_x, offset_y`, then width × height corners: v11 `i16 height; u16 water (low 14 bits level, bit 14 boundary); u8 texture (low 4) | flags (0x10 ramp, 0x20 blight, 0x40 water, 0x80 boundary); u8 variation (low 5 ground, high 3 cliff); u8 cliff texture (high 4) | layer (low 4)`; v12 widens texture to `u16` (low 6 texture, flags at bits 6-9).
- **war3map.wpm** v0: `"MP3W", i32 0, i32 w, i32 h, w × h bytes` with `w = 4 × (terrain width - 1)`. **war3map.shd**: raw bytes of the same size, 0/255. **war3map.mmp** v0: `i32 0, i32 count, (i32 kind, i32 x, i32 y, u8 b, g, r, a)*`.
- Sample coverage (`tests/corpus.py`): ladder maps give w3e 11, doo (8,11), units (8,11), w3r 5, w3c 0, w3s 3; CASC samples add w3e 12, doo (12,11)/(13,11), units (8,9)/(12,9)/(12,11)/(13,9)/(13,11), w3r 7, w3c 3.
- Editor script sections (JASS): `InitSounds`, `CreateRegions` (with weather effects), `CreateCameras`, `CreateAllDestructables` (only `gg_dest_` referenced ones), `CreateAllItems`, `Unit<editor id>_DropItems` / `ItemTable<id>_DropItems` / `Doodad<id>_DropItems`, `CreateBuildingsForPlayerN`, `CreateUnitsForPlayerN`, `CreateNeutralHostile`, `CreateNeutralPassiveBuildings`, `CreateNeutralPassive`, `CreatePlayerBuildings`, `CreatePlayerUnits`, `CreateAllUnits`; globals `gg_rct_`, `gg_cam_`, `gg_snd_` precede `gg_trg_`, then `gg_unit_`, `gg_item_`, `gg_dest_`.

---

### Task 1: Region, camera and sound codecs

**Files:** Create `src/wc3mcp/formats/w3r.py`, `w3c.py`, `w3s.py`; Test `tests/formats/test_elements_codecs.py`.

**Interfaces:** `w3r.Region(left, bottom, right, top, name, index, weather=b"\0\0\0\0", ambient_sound="", color=b"\xff\xff\xff\xff", extra=bytes(8))`, `w3r.RegionFile(version=5, regions=[])`, `VERSIONS = (5, 7)`; `w3c.FIELDS_V0`, `w3c.FIELDS_V3`, `w3c.Camera(name, values: dict[str, float], camera_type=0)`, `w3c.CameraFile(version=0, cameras=[])`, `VERSIONS = (0, 3)`; `w3s.Sound(...)` with the field names above, `w3s.SoundFile(version=3, sounds=[])`, `VERSIONS = (3,)`.

- [ ] Tests: constructed files round-trip for every version; unknown versions and truncated data raise `FormatError`; every sample map's file round-trips byte-exact (skip maps without the file).
- [ ] Implement; `& $PY -m pytest tests/formats/test_elements_codecs.py -q` → pass; commit `feat(formats): regions, cameras and sounds codecs`.

### Task 2: Doodad and unit placement codecs

**Files:** Create `src/wc3mcp/formats/doo.py`, `unitsdoo.py`; Test `tests/formats/test_placement_codecs.py`.

**Interfaces:** `doo.ItemSet = list[tuple[bytes, int]]`; `doo.read_item_sets(r)`, `doo.write_item_sets(w, sets)`; `doo.Doodad(id, variation, x, y, z, angle, scale, skin, flags, life, item_table=-1, item_sets=[], editor_id=0, v12_value=-1, v13_value=-1, entries=[])` (`scale` a 3-list, `entries` the 36-byte blobs); `doo.SpecialDoodad(id, z, x, y)`; `doo.DoodadFile(version=8, subversion=11, doodads=[], special_version=0, specials=[])`, `VERSIONS = {(8, 11), (12, 11), (13, 11)}`. `unitsdoo.Unit(id, variation, x, y, z, angle, scale, skin, flags, owner, unknown_a=0, unknown_b=0, hp=-1, mp=-1, item_table=-1, item_sets=[], gold=12500, target_acquisition=-1.0, hero_level=1, strength=0, agility=0, intelligence=0, inventory=[], abilities=[], random_flag=-1, random_data=b"", random_units=[], color=-1, waygate=-1, editor_id=0, v12_value=-1)`; `unitsdoo.UnitFile(version=8, subversion=11, units=[])`, `VERSIONS` the six pairs above. A unit tail with a non-zero third integer raises `FormatError` (layout unverified).

- [ ] Tests: constructed doodad and unit files (with item sets, inventory, abilities, all random flags, v12/v13 fields, special doodads) round-trip for each version; wrong magic/version raises; sample maps round-trip byte-exact.
- [ ] Implement; run; commit `feat(formats): doodad and unit placement codecs`.

### Task 3: Terrain codecs

**Files:** Create `src/wc3mcp/formats/w3e.py`, `wpm.py`, `mmp.py`; Test `tests/formats/test_terrain_codecs.py`.

**Interfaces:** `w3e.Terrain(version, tileset, custom_tileset, tiles, cliffs, width, height, offset_x, offset_y, heights, water, textures, variations, cliff_bytes)` (per-corner lists, row-major from the bottom-left), helpers `w3e.corner(t, x, y) -> dict` (`height`, `water_level`, `boundary_water_bit`, `texture`, `ramp`, `blight`, `water`, `boundary`, `ground_variation`, `cliff_variation`, `cliff_texture`, `layer`) and `w3e.set_corner(t, x, y, **fields)`; `VERSIONS = (11, 12)`. `wpm.PathingMap(version, width, height, cells: bytearray)`; `mmp.Icon(kind, x, y, color)`, `mmp.Minimap(version=0, icons=[])`.

- [ ] Tests: constructed v11/v12 terrains round-trip; `corner`/`set_corner` pack and unpack every field for both versions (texture 0-15 vs 0-63); wpm/mmp round-trip; sample maps round-trip byte-exact; wpm size equals `4(w-1) × 4(h-1)` of the map's terrain.
- [ ] Implement; run; commit `feat(formats): terrain, pathing and minimap codecs`.

### Task 4: `elements_list` / `elements_edit`

**Files:** Create `src/wc3mcp/ops/elements.py`; Modify `src/wc3mcp/server.py`; Test `tests/ops/test_elements.py`, `tests/test_server.py`.

**Interfaces:** `elements_list(project, kind: "region"|"camera"|"sound", catalog) -> {"version", "items": [...]}` — region `{name, script_name, left, bottom, right, top, weather, ambient_sound, color: {r,g,b}}`, camera `{name, script_name, x, y, ...fields, camera_type?}`, sound `{name, path, eax, looping, 3d, stop_out_of_range, music, fade_in, fade_out, volume, pitch, channel, min_distance, max_distance, distance_cutoff, cone..., label, dialogue: {text, speaker, ...}|None}` (flag bits and TRIGSTR keys resolved). `elements_edit(project, kind, ops, catalog)` with ops `{"op": "upsert", "name", ...fields}` (create with editor defaults or change named fields; `new_name` renames), `{"op": "delete", "name"}`; names unique by script name; weather/sound labels checked against the catalog; new regions get the next free index. Returns `{"changed", "warnings"}` (script stale warning for Lua or when rebuild is off; triggers referencing a deleted `gg_rct_`/`gg_cam_`/`gg_snd_` name).

- [ ] Tests on a scratch ladder map (and a CASC v7/v3 sample): list shapes; upsert create/modify/rename/delete round-trip through the codecs; duplicate names, bad weather ids, bad kinds and missing names raise `bad_value`/`not_found`; unchanged edits leave files untouched.
- [ ] Server tools `elements_list(path, kind)`, `elements_edit(path, kind, ops)`; EXPECTED tool list updated; commit `feat(ops): regions, cameras and sounds tools`.

### Task 5: Script sections for regions, cameras and sounds

**Files:** Create `src/wc3mcp/script/world.py`; Modify `src/wc3mcp/script/build.py`, `src/wc3mcp/ops/script.py`, `src/wc3mcp/server.py` (`map_save` auto rebuild also when `war3map.w3r/w3c/w3s` are dirty); Test `tests/script/test_world.py`.

**Interfaces:** `world.region_globals(rf)`, `world.create_regions(rf) -> str`, `world.camera_globals(cf)`, `world.create_cameras(cf) -> str`, `world.sound_globals(sf)`, `world.init_sounds(sf, durations) -> str` where `durations(path) -> int|None` reads the sound length in ms (FLAC STREAMINFO / WAV header / MP3 frames from the map or CASC; falls back to the duration already in the script); `build.splice(original, tf, ct, td, world=None)` replaces those sections and globals when `world` (parsed files) is given, adding/removing `call InitSounds(  )`-style calls in `main` as the editor does.

- [ ] Tests: generated sections equal the corpus scripts' sections on the sample maps with the files (exact text); splice with unchanged inputs returns the original script byte-exact; a new region appears in globals, `CreateRegions` and `main`.
- [ ] Scratch check (not committed): exact on all JASS maps of the local corpus; list and investigate mismatches.
- [ ] Implement; run; commit `feat(script): regions, cameras and sounds script sections`.

### Task 6: `placed_list` / `placed_edit`

**Files:** Create `src/wc3mcp/ops/placed.py`; Modify `src/wc3mcp/server.py`; Test `tests/ops/test_placed.py`, `tests/test_server.py`.

**Interfaces:** `placed_list(project, catalog, kind: "unit"|"item"|"start_location"|"doodad"|"destructible"|None, area=None, owner=None, type_id=None, limit=200, offset=0) -> {"total", "items": [...]}` — each `{ref: "unit:<editor id>", kind, type, name, x, y, z, angle (degrees), scale, skin, variation, owner, life, mana, gold, level, hero: {str, agi, int}, inventory, abilities, drops: {table, sets}, random: {...}, waygate: region name|None, color}` (fields by kind); classification via catalog (items, doodads, destructibles; `sloc` start locations). `placed_edit(project, catalog, ops)` with `{"op": "add", "kind", "type", "x", "y", ...}` (editor defaults: z from terrain, scale 1, variation 0, life 100 / hp -1, owner 0 for units, neutral passive 15 for items; next editor id), `{"op": "set", "ref", ...fields}`, `{"op": "delete", "ref"}`, `{"op": "move", "ref", "x", "y"}`; validates type ids, owners 0-27, inventory slots 0-5, ability ids, positions inside the playable area.

- [ ] Tests on scratch maps (ladder v8/11 and CASC v13): filters and paging; add/set/move/delete round-trip; bad refs, types, owners and positions raise; untouched files byte-exact.
- [ ] Server tools `placed_list`, `placed_edit`; commit `feat(ops): placed units, items, doodads and destructibles tools`.

### Task 7: Script sections for placed objects

**Files:** Modify `src/wc3mcp/script/world.py`, `script/build.py`, `ops/script.py`, `server.py` (auto rebuild on `war3map.doo` / `war3mapUnits.doo` dirty); Test `tests/script/test_world.py` (append).

**Interfaces:** `world.create_all_destructables(df, referenced)`, `world.create_all_items(uf, referenced)`, `world.create_units(uf, catalog, referenced) -> str` (per-player building/unit functions, neutral functions, drop-item functions, `CreateAllUnits`), `world.placed_globals(...)`; `referenced` = `gg_unit_/gg_item_/gg_dest_` names used by triggers.

- [ ] Tests: sections equal corpus scripts' sections on sample maps; splice identity on unchanged inputs; an added unit appears in its player function.
- [ ] Scratch check on all local JASS corpus maps; commit `feat(script): placed object script sections`.

### Task 8: Terrain tools

**Files:** Create `src/wc3mcp/ops/terrain.py`; Modify `src/wc3mcp/server.py`; Test `tests/ops/test_terrain.py`, `tests/test_server.py`.

**Interfaces:** `terrain_get(project, x0, y0, x1, y1, layers) -> {"width", "height", "offset", "tiles", "cliffs", "layers": {height: [[...]], texture, cliff_level, water, flags, pathing}}` (corner grid window, world ↔ corner coordinates reported); `terrain_edit(project, catalog, ops)` with brushes `{"op": "raise"|"lower"|"plateau"|"smooth"|"noise", "x", "y", "radius", "amount"}`, `{"op": "paint", "tile", "x", "y", "radius"}` (adds the tile to the tileset list, max 16 in v11 / 64 in v12), `{"op": "cliff", "x", "y", "radius", "level"}`, `{"op": "ramp", ...}`, `{"op": "water", "x", "y", "radius", "level"|null}`, `{"op": "blight", ...}`, `{"op": "boundary", ...}`; returns `{"changed", "warnings": ["war3map.wpm/shd/mmp are recomputed by the World Editor on save ..."]}`; `terrain_render(project, scale, layers) -> PNG bytes` (texture colours from tile palette, height shading, water, cliffs, optional placed objects/regions overlay).

- [ ] Tests: brush math on a constructed terrain (radius falloff, clamping to height limits, plateau, smoothing), paint adds tiles and respects limits, window extraction; render returns a PNG of the expected size.
- [ ] Server tools `terrain_get`, `terrain_edit`, `terrain_render` (Image); commit `feat(ops): terrain get, edit and render tools`.

### Task 9: Live verification and wrap-up

- [ ] Editor-marked test: a scratch ladder map edited through `elements_edit` (region + camera), `placed_edit` (unit + item) and `terrain_edit` (raise + paint) and saved with `map_save` opens in the World Editor without load errors, saves cleanly, and the objects are still present after re-reading.
- [ ] Game-marked test: the same map with a map-init trigger writing `RectContainsCoords(gg_rct_...)` and the placed unit's type via `PreloadGenEnd` returns the expected values.
- [ ] Full suite `& $PY -m pytest -q`; update project memory; commit.
