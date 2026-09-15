# Phase 5c: Campaigns Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and edit `.w3n` campaigns through tools: campaign info, loading screen, campaign screen buttons, the maps inside, campaign object data and imports.

**Architecture:** A `.w3n` is a plain MPQ (no 512-byte header) opened by the existing `MapProject`. A new `formats/w3f.py` codec reads `war3campaign.w3f`; `ops/campaign.py` gives JSON views and batch edits; the object data, strings and imports ops pick `war3campaign*` file names when the project is a campaign. Tools: `campaign_new`, `campaign_get`, `campaign_edit`; `map_open`/`map_save`/`map_status`/`map_validate`/`objdata_*`/`imports_edit` accept campaigns.

**Tech Stack:** Python 3.13 stdlib.

**Spec:** `docs/superpowers/specs/2026-09-14-wc3-mcp-design.md` (Campaign tools, `.w3n` + `war3campaign.w3f` + campaign object data row of the verification table).

## Global Constraints

- Byte-exact round trip of every editor-written `war3campaign.w3f` sample (`tests/formats/data/campaign`).
- Batch edits are all-or-nothing; errors are `ToolError(code, message, hint, path/op_index)`.
- A campaign built by the tools opens in the World Editor's Campaign Editor and saves without warnings.

## Verified facts (Campaign Editor of editor 3.0.0.24268, samples made 2026-09-15)

- `.w3n`: MPQ at offset 0. Files: `war3campaign.w3f`, `war3campaign.wts` (once a text field is edited), `war3campaign.w3u` / `war3campaignSkin.w3u` (and the other object data extensions), `war3campaign.imp` (imp v1, default flag 0x15), the campaign's maps stored under their file names (`Chapter One.w3x`), imports under `war3campImported\`.
- `war3campaign.w3f` format version 3, little endian, strings NUL-terminated:
  `i32 version (3)`, `i32 campaign_version (+1 per editor save)`, `i32 editor_version (7000)`, `name`, `difficulty`, `author`, `description` (plain text on a new campaign, `TRIGSTR_n` into war3campaign.wts once edited), `i32 flags`, `i32 background` (index or -1), `background_path` (imported .webm, index -1), `minimap_path`, `i32 ambient_sound` (index or -1), `ambient_sound_path`, `i32 fog_style` (-1 = no custom fog; 0 Linear, 1 Exponential 1, 2 Exponential 2, 3 Height, 4 New Exponential 1, 5 New Exponential 2), `f32 fog_z_start`, `f32 fog_z_end`, `f32 fog_density`, `u8[4] fog_color` (B, G, R, A), `i32 cursor` (0 Human, 1 Orc, 2 Undead, 3 Night Elf, 4 Forsaken), `f32 fog_height_start`, `f32 fog_height_end`, `f32 fog_linear_start`, `f32 fog_linear_end`, `f32 fog_max_opacity`, `i32 fog_over_sky`, `i32 background_version` (0 Default, 1 Classic, 2 Reforged), `i32 button_count` then per button `i32 flags` (1 visible the first time the campaign is loaded, 2 cinematic), `chapter`, `title`, `map`; `i32 map_count` then per map `unknown` (always ""), `path`.
- Flags: 1 variable difficulty levels, 2 the ambient sound is an imported file, 4 the minimap image is a campaign map's minimap (`minimap_path` = the map name).
- Minimap presets are `UI/WorldEditData.txt [CampaignImages]` paths (stored without extension); an imported minimap stores its import path. Background presets index the `[CampaignScreens]` entries followed by the `[LoadingScreens]` entries; ambient sounds index `[AmbientSounds]`.
- A new campaign's float fields hold the editor's uninitialised defaults (`00 04 08 ff` for Z start/end, `00 00 00 ff` for the others, color `00 00 00 00`); keep the floats bit-exact.
- The editor warns "This campaign contains map files which are not used" when a map has no button.
- Driving the Campaign Editor: menu commands posted to it only work while it is the active window (use keyboard shortcuts: ctrl+s, ctrl+o, alt+e); list context menus hold "Add Button..." and "Import File..."; clicking a disabled radio button crashes the editor (dialog_act now refuses disabled controls).

### Task 1: `war3campaign.w3f` codec

**Files:** Create `src/wc3mcp/formats/w3f.py`; Test `tests/formats/test_w3f.py`; add `tests/formats/data/** binary` to `.gitattributes`.

**Interfaces:** `Button(flags, chapter, title, map)`, `CampaignMap(unknown, path)`, `CampaignInfo` (fields above, defaults = the editor's new campaign), `parse(bytes) -> CampaignInfo` (FormatError for other versions), `serialize(CampaignInfo) -> bytes`; `FLAG_VARIABLE_DIFFICULTY, FLAG_IMPORTED_AMBIENT, FLAG_MINIMAP_FROM_MAP`.

- [ ] Tests: every sample round-trips byte-exact; `serialize(CampaignInfo()) == default.w3f`; decoded values of the loading screen, buttons and imported samples match what was set in the editor.

### Task 2: campaign file names for strings, object data and imports

**Files:** Modify `src/wc3mcp/ops/strings.py` (`file_prefix(project) -> "war3map" | "war3campaign"`, `load_strings` and a `strings_file(project)` use it), `src/wc3mcp/ops/objdata.py`, `src/wc3mcp/ops/imports.py`; Test `tests/ops/test_campaign.py`.

- [ ] `objdata_edit` on `Full.w3n` changes `war3campaign.w3u` / `war3campaignSkin.w3u` and writes new strings to `war3campaign.wts`; `imports_edit` keeps `war3campaign.imp`; maps are unchanged.

### Task 3: `ops/campaign.py` and tools

**Files:** Create `src/wc3mcp/ops/campaign.py`; Modify `src/wc3mcp/server.py`, `src/wc3mcp/ops/validate.py` (campaign checks), `tests/test_server.py`; Test `tests/ops/test_campaign.py`.

**Interfaces:**
- `new_campaign(path, name=None, author=None, format="mpq") -> MapProject` (the editor's default w3f; text fields other than the defaults go to war3campaign.wts).
- `campaign_get(project, catalog) -> dict`: `name`, `difficulty`, `author`, `description` (+ `_ref` when TRIGSTR), `variable_difficulty`, `minimap` (`null` | `{"preset": name}` | `{"map": name}` | `{"file": path}`), `loading_screen`: `background` (`null` | `{"preset": index, "name": label}` | `{"file": path}`), `background_version`, `ambient_sound` (same shape), `cursor`, `fog` (`null` | `{style, z_start, z_end, density, color: {r,g,b,a}, height_start, height_end, linear_start, linear_end, max_opacity, over_sky}`), `buttons` [`{index, chapter, title, map, visible, cinematic}`], `maps` [`{name, size, used}`], `campaign_version`, `editor_version`, `imports`, `object_data` (kinds with changes).
- `campaign_edit(project, catalog, ops) -> {"changed", "warnings"}` with ops `{"op": "set", "path", "value"}` on the JSON fields above (text, flags, minimap, loading screen, fog), `{"op": "add_button", chapter, title, map, visible?, cinematic?, index?}`, `{"op": "set_button", index, ...}`, `{"op": "delete_button", index}`, `{"op": "move_button", index, to}`, `{"op": "add_map", source, name?}`, `{"op": "replace_map", name, source}`, `{"op": "remove_map", name}` (refused while a button uses it), `{"op": "extract_map", name, dest}` (written after all ops succeed).
- `map_validate` on a campaign: buttons naming missing maps (error), maps without a button (warning), missing TRIGSTR strings (error).

- [ ] Tests: build a campaign from `new_campaign` with two tool-made maps, buttons, info, loading screen and a campaign unit change; `campaign_get` reflects it; errors are atomic; `map_save` of a campaign skips script rebuild and validates; the result round-trips through `w3f`.

### Task 4: live Campaign Editor check

**Files:** Modify `src/wc3mcp/desktop/editor.py` if the editor needs a way to open campaigns; Test `tests/desktop/test_campaign_live.py` (`pytest -m editor`).

- [ ] The tool-built campaign opens in the Campaign Editor and saves with no warning dialog; `campaign_get` on the editor-saved file equals the tool's view except `campaign_version`.
