# Phase 5e: Assets (Textures and Models) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Inspect, convert, edit and preview Warcraft III textures (BLP, DDS, TGA) and models (MDX, MDL) through tools, for game files, map imports and local files.

**Architecture:** `formats/blp.py` (BLP1 JPEG / paletted read and write), `formats/texture.py` (one decode/encode entry over BLP, DDS, TGA, PNG and JPEG on Pillow, with a BC1-sRGB fallback), `formats/mdx.py` (typed chunk model, byte-exact), `formats/mdl.py` (text form of the same model), `ops/assets.py` (sources: local file, open map file, game data path; destinations: local file or map import) and tools `asset_info`, `asset_convert`, `asset_edit`, `asset_preview`.

**Tech Stack:** Python 3.13, Pillow 12, numpy.

**Spec:** `docs/superpowers/specs/2026-09-14-wc3-mcp-design.md` (Assets tools; "MDX 800/900-1200, MDL, BLP1/2, DDS" verification row: CASC corpus round trip, MDX -> MDL -> MDX).

## Global Constraints

- Game data stays read-only; results go to local files or map imports (imports_edit rules).
- Round trips are byte-exact on the game corpus: 700 BLP (all BLP1: 613 paletted, 87 JPEG), 14,984 MDX (14,982 v1800, one v1700, one v1600); 55,705 DDS (DXT5, DXT1, ATI2/BC5, rare DX10) decode to RGBA.
- Corpus tests sample the game data at runtime and are skipped without the install; nothing from the game is committed.

## Verified facts

- Pillow 12 reads BLP1 (both kinds), DDS DXT1/DXT5/ATI2 and TGA; it writes DDS (uncompressed, DXT1, DXT5), TGA and PNG, but BLP only from palette images. DXGI format 72 (BC1 sRGB) is not implemented in Pillow.
- Game icons are 64x64 DXT5 DDS (BTN*, and DISBTN* under CommandButtonsDisabled); older ones are BLP1 JPEG 64x64.
- MDX files are `MDLX` followed by chunks (tag, u32 size, payload) with no trailing bytes; tags seen: VERS MODL SEQS PIVT TEXS MTLS BONE GEOS GEOA BPOS CLID CAMS ATCH EVTS CORN LITE FAFX PRE2 HELP GLBS RIBB TXAN PREM DILG.

### Task 1: textures

**Files:** Create `src/wc3mcp/formats/blp.py`, `src/wc3mcp/formats/texture.py`; Test `tests/formats/test_textures.py`.

**Interfaces:** `blp.parse(bytes) -> Blp` (header fields, mip data), `blp.serialize(Blp) -> bytes`, `blp.encode(image, kind="jpeg"|"palette", quality=90, mipmaps=True) -> bytes`; `texture.info(bytes) -> dict` (format, width, height, mipmaps, compression, alpha), `texture.decode(bytes) -> PIL.Image (RGBA)`, `texture.encode(image, format, **options) -> bytes` for blp / dds (dxt1, dxt5, uncompressed) / tga / png / jpg.

- [x] Every game BLP round-trips byte-exact through parse/serialize and decodes like Pillow; a sample of game DDS decodes (including BC1 sRGB); encoded BLP JPEG, BLP palette, DDS and TGA decode back within tolerance.

### Task 2: texture tools

**Files:** Create `src/wc3mcp/ops/assets.py`; Modify `src/wc3mcp/server.py`; Test `tests/ops/test_assets.py`.

**Interfaces:** sources are `{"file": path}`, `{"map": open map path, "name": file in the map}` or `{"game": path}` (CASC path, layers like data_file). `asset_info(source)`; `asset_convert(source, dest, format?, options)` where dest is `{"file": path}` or `{"map": path, "name": import path}`; `asset_edit(source, dest, ops)` with texture ops `resize`, `crop`, `tint`, `grayscale`, `brightness`, `overlay` (another texture), `icon` (`{"op": "icon", "kind": "BTN"|"DISBTN"|"PASBTN"|"DISPASBTN"}` building the 64x64 command button variants: BTN bevel measured on 120 game icons, DISBTN = luminance x 0.48 with a black 4-pixel frame and a dark ramp, mean error 4.6/255 against 200 game DISBTN icons); `asset_preview(source, size?)` returns a PNG image.

- [x] Tests: info on game BLP/DDS; convert a game icon to PNG and to a BLP JPEG import in a ladder map (imports list and map_validate clean); DISBTN built from BTNFootman is close to the game's DISBTNFootman; errors for missing sources and unknown formats.

### Task 3: MDX codec

**Files:** Create `src/wc3mcp/formats/mdx.py`; Test `tests/formats/test_mdx.py`.

**Interfaces:** `mdx.parse(bytes) -> Model` (version, info, sequences, global sequences, textures, materials/layers, texture animations, geosets, geoset animations, bones, lights, helpers, attachments, pivots, particle emitters, ribbons, cameras, event objects, collision shapes, corn emitters, face effects, bind poses; unknown chunks kept raw), `mdx.serialize(Model) -> bytes`.

- [x] Byte-exact on a runtime sample of game models across every chunk kind (all models with the rare tags) and the v1600 / v1700 files. (Whole corpus checked once: 14,984 / 14,984. Found on the way: bone indices and weights are 16-bit from v1600; v1600+ lights carry 4 + 24 undocumented bytes; material shader names exist only for 900-1000; camera sizes keep 3 in their top byte; cameras use the unprefixed one-float tracks IDUF, ELAF and PTSF; v1100+ layers name their real textures in a per-layer list with semantics 0 diffuse, 1 normal, 2 ORM, 3 emissive, 4 team colour, 5 environment; the DILG chunk stays raw.)

### Task 4: MDL text and conversion

**Files:** Create `src/wc3mcp/formats/mdl.py`; Test `tests/formats/test_mdl.py`.

- [x] MDX -> MDL -> MDX byte-exact on the same sample (and 300 random models); MDL output readable by Retera-style tools (blocks, keys, interpolation names). Syntax follows mdx-m3-viewer's MDL; each written block is read back and anything the dialect cannot hold goes on `//@ key json` comment lines.

### Task 5: model tools

**Files:** Modify `src/wc3mcp/ops/assets.py`, `src/wc3mcp/server.py`; Test `tests/ops/test_assets.py`.

- [ ] `asset_info` for models (version, sequences with intervals, textures, geoset / bone / attachment counts, extents); `asset_convert` MDX <-> MDL; `asset_edit` model ops `retexture`, `scale`, `rename_sequence`, `remove_sequence`, `team_color`, `add_attachment`; `asset_preview` renders geosets (software, orthographic, textured when possible).

### Task 6: live check

- [ ] A converted icon and an edited model imported into a map show in the World Editor (object editor icon and model preview) without errors (`pytest -m editor`).
