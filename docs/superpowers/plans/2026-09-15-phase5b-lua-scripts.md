# Phase 5b: Lua Script Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `script_build`, `map_save` and `map_new` produce `war3map.lua` for Lua maps exactly as the World Editor writes it.

**Architecture:** The editor writes Lua maps by building its JASS script and transpiling it line by line. `script.build.new_script(..., raw=lua.RAW)` builds that JASS with the map's own Lua lines marked, and `script.lua.transpile` turns it into Lua in the reference script's style. `ops.script.script_build` rebuilds the whole file (Lua is never spliced).

**Tech Stack:** Python 3.13 stdlib; common.j / Blizzard.j from the catalog for types.

**Spec:** `docs/superpowers/specs/2026-09-14-wc3-mcp-design.md` (script & validation tools, "Editor-generated script structure (JASS and Lua)").

## Global Constraints

- Byte-identical to editor output on every local Lua corpus map (94) and on Lua maps saved by the current editor.
- JASS output unchanged (whole scripts identical on 455 of 462 corpus maps, as before).
- Never replace a hand-written war3map.lua: only scripts with editor `main()` and `config()` functions, or none.

## Verified facts

- Style, from the reference script: flat (83 corpus maps and every current-editor save) or 4-space indented (11 older maps); a blank line after a function's locals or not (2 older indented maps have none). The current editor (w3i editor version 7000) writes flat, blank line, CRLF. All corpus Lua scripts are CRLF.
- Detect indentation from the first line of `function main()`, and the blank-after-locals rule from editor functions (not `Trig_`/`InitTrig_`) that start with locals: Custom Script lines can start with `    local` and fool simpler checks.
- Expressions: `'abcd'` becomes `FourCC("abcd")`, `$10` becomes `0x10`, string `+` becomes `..`, `!=` becomes `~=`, integer `/` integer becomes `//`; `null` is `""` where a string is expected (function arguments, `==`/`<`/`>` against a string, string initialisers) but stays `nil` for `!=`; integer literals assigned to reals get `.0`; arrays are `__jarray(default)` (or `{}` for handles); string globals without a value are `""`, other types `nil`.
- Statements: `if`/`elseif` conditions lose all outer parentheses and get one pair; `loop` is `while (true) do`, `exitwhen x` is `if (x) then break end`, bare `return` is `return ` (trailing space); comments and blank lines are dropped, `endfunction` becomes `end` plus a blank line.
- The map's own Lua passes through untouched: the map header (followed by a newline), custom text triggers (each preceded by an empty `function InitTrig_<name>()` / `end` / blank, and followed by a blank line), and GUI Custom Script actions with their JASS indentation (4 spaces per block level, even in flat scripts). JASS-looking Custom Script (`call X()`) is a Lua syntax error in the editor too.
- Editor experiments: `scratchpad/p5/live_lua_custom.py` variants a, b, c1, c4, c5, c7 (header, text triggers, locals, Lua blocks and Custom Script inside If/Then/Else); all 13 editor samples in `scratchpad/lua_samples` match.

### Task 1: Transpiler (`wc3mcp.script.lua`)

**Files:** Create `src/wc3mcp/script/lua.py`; Test `tests/script/test_lua.py`.

**Interfaces:** `RAW = "\x01"`; `Types(*jass_sources)` with `functions`, `globals`, `add`, `copy`; `natives(catalog) -> Types` (cached); `style(lua) -> (indented, blank_after_locals)`; `editor_generated(lua) -> bool`; `transpile(jass, natives, indented=False, blank_after_locals=True) -> str` (CRLF; `ValueError` naming the JASS line for unsupported statements).

- [x] Port the scratch prototype `p5/j2l.py` (94/94 corpus maps, 7/7 campaign samples), add RAW pass-through and errors; unit tests for expressions, statements, raw lines, style detection.

### Task 2: Mark the map's own Lua in generated JASS

**Files:** Modify `src/wc3mcp/script/jass.py` (`raw_lines`, `JassGen(raw=)`: Custom Script lines and custom text with its empty InitTrig), `src/wc3mcp/script/build.py` (`custom_script`, `trigger_sections`, `splice`, `new_script` take `raw`).

- [x] JASS output unchanged with `raw=""` (corpus check 455/462 as before).

### Task 3: `script_build`, `map_save`, `map_new` for Lua

**Files:** Modify `src/wc3mcp/ops/script.py` (`lua_script(project, catalog, tf, ct, reference="")`; `script_build` rebuilds Lua whole, refuses hand-written Lua with `not_editor_script`, generates a missing script of either language using the other language's script as reference), `src/wc3mcp/ops/newmap.py` (`script_language="lua"` sets w3i `script_language=1` and writes war3map.lua), `src/wc3mcp/server.py` and warnings in `ops/info.py`, `ops/triggers.py`; Test `tests/ops/test_script.py`, `tests/ops/test_newmap.py`.

- [x] `test_script_build_keeps_editor_scripts` covers Lua sample maps; a Lua ladder map with a new GUI trigger, header, text trigger and Custom Script in an If block rebuilds and validates; hand-written Lua is refused; JASS -> Lua -> JASS language switch regenerates the original war3map.j byte for byte; `map_new(script_language="lua")` builds, validates and is stable.

### Task 4: Live editor check

**Files:** Modify `tests/desktop/test_world_live.py` (`assert_script_build_keeps` helper; `test_new_map_opens_and_saves_in_the_editor[jass|lua]`, the Lua map with header, two text triggers and Custom Script in If/Then/Else).

- [x] `pytest -m editor tests/desktop/test_world_live.py`: the editor saves the tool-built Lua map without errors and `script_build` leaves the editor's war3map.lua unchanged.

Also fixed on the way: `triggers_edit` rejected nothing when a literal was given for a parameter type that takes no literals (e.g. a comparison operator written as `"OperatorEqualENE"` instead of `{"preset": ...}`); the corpus writes literals only for integer, real, boolean and string based types, so anything else is now an `invalid_trigger` error.
