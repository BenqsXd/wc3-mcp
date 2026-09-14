# wc3-mcp — Warcraft III World Editor MCP Server: Design

Date: 2026-09-14
Status: Draft for user review

## 1. Goal

A Python MCP server that lets Claude fully operate Warcraft III map making:

- **Outcome:** build and modify any map/campaign content precisely — terrain, doodads, units, object data, GUI and code triggers, script, regions, cameras, sounds, map info, imports, campaigns, AI files, models/textures.
- **Editor:** drive the World Editor desktop app where it adds value — open/reload/save, compile-via-save, Test Map, menus, dialogs, screenshots, viewport input.
- **Proof:** every result can be verified — byte-exact codecs, validation, editor open/save, and in-game tests.

### Decisions made during brainstorming

| Topic | Decision |
|---|---|
| Meaning of "fully operate" | Outcome + editor (hybrid) |
| Primary map type | Custom games (RPG / TD / arena / hero defense): triggers, object data, regions, cameras, sounds first; terrain second |
| Logic form | Decide per map: Lua code triggers, JASS/vJASS code triggers, and GUI triggers are all first-class |
| Desktop sharing | Take turns: Claude owns the editor while working, backs up before every write, never discards the user's unsaved work |
| Approach | A — Python-native: own codecs + game-data catalog + script validation + pywin32 editor driver; editor used as compile/verify step |
| Scope | Includes campaigns (.w3n), AI Editor (.wai/.ai), model/texture tools |

### Out of scope

- Authoring `.w3xd` (Blizzard-internal, encrypted-looking container used only by built-in Forsaken Kingdom campaign maps; not an MPQ).
- Live co-editing (both editing the same open map simultaneously).
- Battle.net hosting/publishing.
- Creating 3D models from scratch or audio authoring (models/textures: inspect, convert, edit, preview only).

## 2. Verified environment facts (local, 2026-09-14)

- Warcraft III Reforged **3.0.0.24268** (`v3.0.x`) at `D:\Warcraft III`. Newer than most public format docs.
- `_retail_\x86_64\World Editor.exe` and `Warcraft III.exe` are x64. `JassHelper\jasshelper.exe`, `pjass.exe`, `sfmpq.dll` are 32-bit (exes runnable; DLL not loadable from 64-bit Python).
- Python 3.13 with `mcp 1.27`, `pywin32`, `numpy`, `pillow`, `pydantic`, `pytest` installed; Node 24; uv 0.11.
- **Game data (CASC):** a throwaway pure-Python reader resolves 175,018 paths instantly. Namespace root `War3.w3mod:` with overlays `_hd.w3mod`, `_de.w3mod`, `_teen.w3mod`, `_locales/<loc>.w3mod`, `_tilesets/<letter>.w3mod`, `_balance/{custom,melee}_v{0,1}.w3mod`, `_deprecated.w3mod`. Key files present: `UI/TriggerData.txt`, `Scripts/common.j`, `Units/UnitMetaData.slk`, `_Locales/enUS.w3mod:UI/WorldEditStrings.txt`, `UI/CampaignInfo*.txt`.
- **Corpus available locally:** ~100 ladder `.w3x` (Documents), 374 `.w3x` + 91 `.w3m` built-in maps in CASC, 7 `.wai`, 282 `.ai`, 14,984 `.mdx`, 55,705 `.dds`, 700 `.blp`. No `.w3n` sample exists locally.
- **Newest map format versions observed** (CASC campaign maps, game version field `7000.2.0.4`): `w3i` v39, `w3e` v12, `war3map.doo` v13/sub 11, `war3mapUnits.doo` v13/sub 11, object mods v3. Ladder maps: `w3i` v31/33, `w3e` v11, doo v8/sub 11, `wtg`/`wct` marker `0x80000004`, `w3r` v5, `imp` v1.
- Maps contain `conversation.json` and localized string tables `_Locales\<loc>.w3mod\war3map.wts`; scripts are `war3map.j` or `war3map.lua`.
- MPQ facts from ladder maps: header at offset 0, format v0, sector size 4096; `(listfile)` and `(attributes)` present, both encrypted with FIX_KEY; `(attributes)` version 100, flags 1 (CRC32).
- **Editor:** no menu/dialog/accelerator PE resources; code section is packed. Menus are built at runtime → command ids must be enumerated at runtime (`GetMenu` / `GetMenuItemInfoW`) and matched to `WESTRING_MENU_*` labels. 396 `WECOMMAND_*` names exist. Save types include "Warcraft III Scenario Folder" (folder maps). Features of note: Export Script, Calculate Shadows and Save Map, batch resave.
- CLI flags present in both exes: `-launch`, `-loadfile "<path>"`, `-windowmode windowed|fullscreen|windowedfullscreen`, `-nowfpause`, `-hd 0|1|2`, `-teen 0|1`; game also `-graphicsapi`. Test Map preference `Copy Location=WorldEditTestMap`.
- Logs: `Documents\Warcraft III\Logs\War3EditorLog.txt`, `War3Log.txt` (logs "Opening mod - <path>" per map).

## 3. Architecture

Python package `wc3mcp`, stdio MCP server (FastMCP from `mcp`), project at `D:\Warcraft III\wc3-mcp`.

| Module | Responsibility | Depends on |
|---|---|---|
| `wc3mcp.mpq` | MPQ read/write (.w3x/.w3m/.w3n): encryption, compression (zlib/bzip2 + read-only legacy), (listfile)/(attributes) regeneration, protected-map tolerance, unnamed-entry preservation | stdlib |
| `wc3mcp.casc` | Read-only CASC access, overlay/namespace resolution | stdlib |
| `wc3mcp.formats.*` | One codec per file type, `parse(bytes) -> model`, `serialize(model) -> bytes`: w3i, w3e, shd, wpm, mmp, doo, unitsdoo, w3r, w3c, w3s, wts, imp, objmods (w3u/w3t/w3b/w3d/w3a/w3h/w3q + skin + campaign), wtg, wct, w3f, wai, slk, txt/ini, mdx, mdl, blp, dds, tga | stdlib, numpy (textures) |
| `wc3mcp.gamedata` | Catalog: base objects, field metadata (name ↔ rawcode, types, ranges), TriggerData signatures, tilesets/cliffs/water, doodads, sounds, models, icons, natives. Cached per game build | casc, formats |
| `wc3mcp.project` | `MapProject` / `CampaignProject`: working copy, lazy components, dirty tracking, fingerprints, backups, snapshots, pack/unpack (MPQ or folder) | mpq, formats |
| `wc3mcp.ops` | High-level edits: terrain brushes, placements, object editor ops, GUI trigger builder, code triggers, variables, imports, strings, campaign ops, AI ops, asset ops | project, gamedata |
| `wc3mcp.script` | Script generation (JASS/Lua), `pjass`/`jasshelper` runners (copied out of the install), Lua syntax check, error → trigger mapping | gamedata, formats |
| `wc3mcp.editor` | Win32 driver: launch/attach, window discovery, runtime menu enumeration + `WM_COMMAND`, dialog/control reading and driving (incl. cross-process list/tree/Scintilla), screenshots, input, log tailing, load/save completion detection | pywin32, ctypes |
| `wc3mcp.game` | Game launch for tests, log watching, Preload-file result reading, screenshots, closing launched processes | pywin32 |
| `wc3mcp.server` | Thin MCP tool layer: argument validation, calls into ops/editor/game, compact JSON / image results, tool-call logging | all |

### Principles

1. **Lossless:** unknown fields and trailing data are preserved; untouched files are copied byte-for-byte; only dirty components are re-serialized.
2. **Version-gated writes:** a codec writes a version only after corpus round-trip proves byte-exactness; otherwise it is read-only and says so.
3. **Headless-first:** all map-content tools work without the editor; the editor is a compile/verify step and the path for GUI/visual work.
4. **Game install is read-only:** every write passes a path guard refusing `D:\Warcraft III\**`. Work dirs, backups, cache, logs, tool copies live under `%LOCALAPPDATA%\wc3mcp\`.
5. **No new dependencies** beyond what is installed unless a plan task justifies one explicitly.

## 4. MCP tool surface (51 tools)

All `*_edit` tools take a batch of `ops` applied atomically (all-or-nothing). Fields accept human names or rawcodes. Large results are paged. Maps/campaigns are referenced by path; several may be open.

| Group | Tools |
|---|---|
| Map lifecycle (8) | `map_new` (size, tileset, script language), `map_open` (summary: info, counts, versions, protection), `map_close`, `map_save` (validate → backup → pack; MPQ or folder), `map_status` (dirty components, files, warnings), `map_file_read`, `map_file_write` (raw escape hatch), `map_snapshot` (create/restore/diff) |
| Game data (3) | `data_search` (unit/item/ability/buff/upgrade/doodad/destructible/tile/cliff/water/sound/model/icon/trigger function/trigger type/native), `data_get` (base values + field metadata), `data_file` (raw CASC read) |
| Map info (2) | `info_get`, `info_edit` (name, author, description, loading screen/prologue, fog/weather/light/sound env, flags, players, forces, script language, tech/upgrade availability, random unit/item tables, game data set) |
| Terrain (3) | `terrain_get` (grid window: height, texture, cliff, water, flags, pathing), `terrain_edit` (raise/lower/plateau/smooth/noise brushes, paint, cliff level, ramp, water, blight, boundary), `terrain_render` (top-down image from data) |
| Placed objects (2) | `placed_list`, `placed_edit` — units, items, start locations, doodads, destructibles (owner, hero data, inventory, drops, abilities, skins, random entries, waygates) |
| Regions/cameras/sounds (2) | `elements_list`, `elements_edit` (kind = region / camera / sound) |
| Object data (3) | `objdata_list`, `objdata_get` (merged base + mods with field names), `objdata_edit` (create/set/reset/delete, per-level values, gameplay constants; `scope: map / campaign`) |
| Triggers (3) | `triggers_tree`, `trigger_get` (GUI ECA as JSON + readable text, or custom text), `triggers_edit` (upsert GUI or code trigger, delete, move, enable, categories, variables, map header script; GUI validated against TriggerData) |
| Imports (1) | `imports_edit` (add/replace/remove, paths; `scope: map / campaign`) |
| Script & validation (3) | `script_build` (generate war3map.j / war3map.lua), `script_validate` (pjass / jasshelper / Lua syntax; errors mapped to triggers), `map_validate` (cross-file references, strings, limits) |
| Editor driver (9) | `editor_launch`, `editor_status` (open map, dirty state, windows, modal dialogs), `editor_map` (open/save/close/reload/compile), `editor_menu` (list/invoke), `editor_screenshot` (main/module/dialog/region), `editor_dialogs` (read controls), `editor_dialog_act` (set/click), `editor_input` (clicks/keys/drags), `editor_log` |
| Game testing (3) | `game_test` (launch windowed, watch log, read Preload results, timeout), `game_status` (log + screenshot), `game_close` |
| Campaign (2) | `campaign_get` (info, map buttons, cinematics, loading screens, campaign data summary), `campaign_edit` (info, buttons, cinematics, add/remove/extract maps). Lifecycle tools accept `.w3n` |
| AI editor (3) | `ai_get` (.wai general options, priorities, heroes/skills, attack groups/waves, conditions), `ai_edit`, `ai_export` (.ai script → import into map → wire start-AI call) |
| Assets (4) | `asset_info` (MDX/MDL/BLP/DDS/TGA metadata), `asset_convert` (MDX↔MDL, BLP/DDS/TGA↔PNG), `asset_edit` (retexture, scale, sequences, materials/team color, attachments; texture resize/recolor; BTN/DISBTN/PAS icon builder), `asset_preview` (texture image; model via editor Model Previewer screenshot or software render) |

## 5. Data flow and editor sync

### Working copy

1. `map_open` unpacks the source into `%LOCALAPPDATA%\wc3mcp\work\<id>\` and records a source fingerprint (size, mtime, sha256).
2. Ops mutate typed components in memory and mark them dirty.
3. `map_save`: serialize dirty components → rebuild script if needed (below) → `map_validate` → back up source to `%LOCALAPPDATA%\wc3mcp\backups\<map>\<timestamp>` (keep last 20) → pack to temp → atomic replace.
   - Script rebuild rule, `rebuild_script` = `auto` (default) / `always` / `never`: `auto` runs `script_build` only when components that feed the script (triggers, variables, placements, regions, cameras, sounds, players/forces) are dirty **and** the map has `war3map.wtg`/`war3map.wct`. Maps without trigger data (protected or hand-scripted) never get their script regenerated automatically; their script is edited via `map_file_write`.
4. If the source fingerprint changed since open (e.g. user saved in the editor), save is refused; the tool reports it and Claude reopens and re-applies.

### Take-turns protocol with the editor

1. `editor_status`: is the target map open, and does it have unsaved changes? Unsaved user changes → stop and ask the user.
2. Close the map in the editor (if open).
3. Apply edits and `map_save`.
4. Reopen in the editor and wait for load completion (window title / editor log / dialog state).
5. Optional compile: save in the editor — regenerates `war3map.j`/`.lua` from triggers, runs JassHelper, rebuilds shadows/pathing/minimap. Capture error dialogs. Reload the working copy from the saved file.

Reverse direction: when the user saves in the editor, `map_status`/`map_open` detect the fingerprint change and reload (discarding in-memory state only if clean).

### Script authority

Editor compile-via-save is the final authority for maps meant to stay editor-compatible. `script_build` gives headless generation for fast validation and editor-less work.

### Game testing

`game_test`: save → launch `Warcraft III.exe -launch -loadfile "<map>" -windowmode windowed -nowfpause` → watch `War3Log.txt` for load/errors/crash → optional screenshots → read Preload output files → close on timeout or request. The editor's Test Map command is also reachable via `editor_menu`.

### Concurrency and desktop

Operations are serialized per map; editor and game automation are serialized globally. Tools needing focus or real input say so in their result and restore the previous foreground window afterwards.

### Game data cache

Built from CASC on first use, cached under `%LOCALAPPDATA%\wc3mcp\cache\<build>\`, rebuilt automatically when `.build.info` reports a different build.

## 6. Error handling and safety

- **Untrusted input:** all codecs bounds-check and cap sizes (no decompression bombs, no oversized allocations). MPQ entry names are sanitized before touching disk (no `..`, no absolute paths).
- **Protected maps:** missing `(listfile)` → name recovery from known WC3 names, script references, import lists; `protected: true` flag; unnamed entries are preserved and re-packed so saving never drops content.
- **Version gating:** unknown/newer versions load best-effort with raw bytes kept; writes are refused with a clear message pointing to `map_file_write` or the editor.
- **Atomic ops:** each `*_edit` batch is validated first, applied to a copy, and committed only if every op succeeds. Errors return `{code, message, op_index, hint}` with nearest-match suggestions.
- **Validation tiers:** per-op (types, metadata min/max, id existence) → per-save (cross-file references, TRIGSTRs, script syntax) → editor compile (error dialogs) → game test (log + Preload results).
- **User work:** backups before every save; snapshots for rollback; never touch an editor with unsaved changes; a hung editor is reported, never killed without asking; only processes the server launched are closed.
- **Install read-only:** path guard on every write; JassHelper folder copied to `%LOCALAPPDATA%\wc3mcp\tools\jasshelper\` and run from there with timeouts.
- **Observability:** every tool call logged (args summary, duration, result/error) to `%LOCALAPPDATA%\wc3mcp\logs\`.

## 7. Testing

1. **Corpus round-trip (core):** pytest parametrized over every local instance — ladder maps, CASC built-in maps, CASC `.wai`, CASC models/textures. Pass = parse → serialize byte-identical (MDX also MDX → MDL → MDX). Corpus discovered at runtime, never committed; tests skip when the install is absent.
2. **Unit tests:** terrain brush/cliff/ramp math, field-name resolution, TriggerData signature validation, trigger builder, script generation, MPQ write → read-back, protected-map name recovery, path guard.
3. **Tool-level tests:** in-process MCP client drives tools on temp copies: new map → edit → save → reopen → assert.
4. **Editor integration (`pytest -m editor`, on demand):** tool-made maps open in the editor without errors; editor save → re-parse → changes preserved; menu/dialog/screenshot driver smoke tests.
5. **Game integration (`pytest -m game`):** launch test maps windowed; map script writes results via Preload natives (`PreloadGenClear`/`PreloadGenStart`/`Preload`/`PreloadGenEnd`) to `Documents\Warcraft III\CustomMapData`; test reads and asserts; `War3Log.txt` checked for clean load.
6. **Acceptance scenario:** a small hero-arena map built entirely through tools — terrain, regions, custom hero/ability/item, the same logic as GUI, Lua, and JASS variants, a 2-map campaign, an AI script, an imported model and icon — passes editor open+save and a game test.

## 8. Format and behavior facts resolved during implementation

These are not open design questions; each is resolved inside the named plan task by the stated method, and the corresponding write path stays disabled until it passes.

| Item | Method | Module |
|---|---|---|
| Byte layouts of newest versions: w3i v39, w3e v12, doo v13/11, unitsdoo v13/11, objmods v3 (+skin), wtg/wct `0x80000004`, w3r, w3c, w3s, imp, mmp, wpm, shd, wts, `conversation.json` | Layouts from War3Net / HiveWE / WC3MapTranslator sources, confirmed by 100% corpus round-trip | `formats` |
| `.w3n` + `war3campaign.w3f` + campaign object data | Source references; no local sample → create one with the editor's Campaign Editor during a take-turns session, then round-trip | `formats`, `project` |
| `.wai` layout | Sources + round-trip of the 7 CASC `.wai` files | `formats` |
| MDX 800/900–1200, MDL, BLP1/2, DDS | Sources (mdx-m3-viewer, HiveWE, Retera Model Studio) + CASC corpus round-trip | `formats` |
| Editor-generated script structure (JASS and Lua) | Compare `script_build` output against editor-saved corpus maps | `script` |
| Editor menu command ids, load/save completion signals, unsaved-changes (dirty) detection, Open/Save dialog structure, Scintilla access | Runtime enumeration and observation in a take-turns session; until dirty detection is proven, `editor_status` reports dirty state as unknown and the protocol treats unknown as dirty (stop and ask) | `editor` |
| Preload file output in 3.0 | Game integration test | `game` |
| Folder-map layout accepted by the editor | Save a map as "Scenario Folder" in the editor and inspect | `project` |

## 9. Delivery

- Project: `D:\Warcraft III\wc3-mcp` (git repo), uv-managed, Python 3.13.
- Registration: `D:\Warcraft III\.mcp.json` entry `wc3` with command `uv`, args `["run", "--project", "D:\\Warcraft III\\wc3-mcp", "wc3-mcp"]` (console script `wc3-mcp` → `wc3mcp.server:main`, stdio transport).
- Implementation plans are written per build-order phase below (one plan document per phase), each ending with its tests passing.
- Runtime data: `%LOCALAPPDATA%\wc3mcp\{work,backups,cache,logs,tools}`.

### Build order

1. **Foundation:** `mpq`, `casc`, path guard, `project` working copy/backups, `gamedata` catalog core, server skeleton + `map_*` + `data_*` tools.
2. **Custom-game core:** `wts`, `w3i`, `imp`, objmods, `wtg`/`wct`, script build/validate, `info_*`, `objdata_*`, `triggers_*`, `imports_edit`, `script_*`, `map_validate`.
3. **Editor + game loop:** `editor_*`, `game_*`, take-turns protocol, compile-via-save.
4. **World content:** `w3r`/`w3c`/`w3s`, `doo`/`unitsdoo`, `w3e`/`shd`/`wpm`/`mmp`, `elements_*`, `placed_*`, `terrain_*`.
5. **Extended scope:** campaign (`w3f`, `.w3n`), AI (`wai`, `.ai` export), assets (MDX/MDL/BLP/DDS/TGA).
6. **Acceptance scenario.**
