# Phase 6: Acceptance Scenario Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the whole tool surface on one small hero-arena project built only through MCP tool calls: three map variants (GUI, JASS, Lua logic), a two-map campaign, an AI script, an imported icon and model; it passes validation, World Editor open + save, and a game test.

**Architecture:** `tests/acceptance/arena.py` builds the project through the in-process MCP client (`create_connected_server_and_client_session(server.mcp._mcp_server)`, as in `tests/test_server.py`), one tool call per step, and returns the paths and the facts the tests check. Three test modules use it: the default suite (build + validate + reopen), `-m editor` (open and save everything in the World Editor), `-m game` (run each variant, compare the Preload reports).

**Tech Stack:** Python 3.13, mcp 1.27 in-process client, pytest markers `editor` / `game`.

**Spec:** `docs/superpowers/specs/2026-09-14-wc3-mcp-design.md` (section 7 item 6; build order step 6).

## Global Constraints

- Only MCP tool calls build the project (no direct `ops` / `formats` calls in the builder); tests may read results with codecs.
- The game install stays read-only; everything is written under the test's temporary directory.
- Take turns with the World Editor: editor tests skip when an editor is already running and quit only the instance they launched.
- Game tests need the user to be logged in to Battle.net once; never enter credentials.

## Found while building it

- The Microsoft Store Python redirects writes under `AppData\Local` into its package folder, invisible to pjass and JassHelper, so `script_validate` failed outside the test suite: `config.home()` now names the package's real `LocalCache\Local` folder (fixed in 5437239).

## The scenario

- Map: `map_new` 64x64 Lordaeron Summer, 2 players; `script_language` jass (GUI and JASS variants) or lua (Lua variant).
- Terrain: raise and paint the arena centre (`terrain_edit`); region `Arena` (-512, -512, 512, 512) (`elements_edit`).
- Assets: `asset_edit` BTNFootman into `war3mapImported\BTNArenaChampion.blp` (tint + BTN bevel) and Footman.mdx into `war3mapImported\ArenaChampion.mdx` (scale 1.3, team colour, extra attachment).
- Object data (`objdata_edit`): ability `A000` from `AHhb` ("Arena Light"), hero `H000` from `Hpal` ("Arena Champion", icon + model imports, hero ability list `A000`), item `I000` from `ratc` ("Arena Token").
- Placed (`placed_edit`): the hero for player 0 at (0, 0), a hostile ogre at (700, 700), an Arena Token at (128, -128).
- Logic on map initialization, written as GUI actions (report lines as Custom Script), as a JASS text trigger, or as a Lua text trigger: set the hero to level 3, learn `A000`, give it an `I000`, then Preload-report hero type id, hero level, `A000` level, whether it holds `I000`, and `arena` when the Arena region contains it, to `wc3mcp\arena_<variant>.txt`.
- AI: `ai_edit` a new `HeroArena.wai` (name, a Paladin hero, footmen build, attack wave), `ai_export` into each map for player 1.
- Checks before saving: `script_validate` ok, `map_validate` without errors; `map_save`.
- Campaign: `campaign_new` `HeroArena.w3n`, `campaign_edit` name/author, `add_map` for the GUI and JASS maps, one button each; `map_save`.

### Task 1: scenario builder and default-suite test

**Files:** Create `tests/acceptance/arena.py`, `tests/acceptance/test_arena.py`.

**Interfaces:** `build(folder: Path) -> dict` with `maps` ({variant: path}), `campaign` (path), `hero`, `ability`, `item` ids and `expected_report(variant) -> list[str]`.

- [x] The builder runs every step through tool calls and fails with the tool's error text on any `isError` result.
- [x] `test_arena.py` (needs the install): all three maps validate clean; reopened with `map_open`, each has the custom hero / ability / item (`objdata_list`), the Arena region (`elements_list`), the hero placed for player 0 (`placed_list`), both imports and the exported AI (`imports_edit` listing), the report trigger (`triggers_tree`: gui for GUI, text for JASS and Lua); `campaign_get` lists two maps and two buttons.

### Task 2: World Editor acceptance

**Files:** Create `tests/acceptance/test_arena_editor.py`.

- [x] `-m editor`: each map opens in the World Editor without dialogs and saves without script errors; the editor log names no failing import; the editor-saved maps still hold the custom objects, the region, the placed hero, the imports and the triggers; the campaign opens in the Campaign Editor and saves (`save_campaign`) without warnings.

### Task 3: game acceptance

**Files:** Create `tests/acceptance/test_arena_game.py`.

- [ ] `-m game`: each variant runs in Warcraft III and writes the expected report (identical apart from the file name); the run ends when the report exists and the game closes. (Test written 2026-09-15; blocked: the game exits before loading a map until the user logs in to Battle.net.)
