# Phase 3: World Editor and Game Driver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline; the user asked for no subagents after spend-limit failures). Steps use checkbox (`- [ ]`) syntax. Desktop behaviour below was verified live on 2026-09-15; tasks give interfaces, behaviour and tests, and the code is written test-first during execution.

**Goal:** Drive the World Editor (launch, status, open/save/close/compile, menus, dialogs, input, screenshots, log) and the game (windowed test runs with log watching and Preload results) from MCP tools, following the take-turns protocol.

**Architecture:** Package `wc3mcp.desktop`: `win.py` (Win32 helpers over pywin32/ctypes: windows, controls, menus, messages, input, screenshots), `editor.py` (editor driver built on window titles, runtime menus and dialogs), `game.py` (game runner). `server.py` exposes 12 tools and `map_save` refuses while the editor has the same map open with unsaved changes.

**Tech Stack:** Python 3.13 Store interpreter, pywin32 311, Pillow (ImageGrab), stdlib ctypes; FastMCP `Image` for screenshots.

**Spec:** `docs/superpowers/specs/2026-09-14-wc3-mcp-design.md` (section 4 "Editor driver (9)", "Game testing (3)"; section 5 "Take-turns protocol", "Game testing"; section 6 "User work").

## Global Constraints

- `$PY = "%LOCALAPPDATA%\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\python.exe"`; branch `phase3-editor-driver` stacked on `phase2d-script-build`; no push/merge until all phases are done.
- Never discard the user's unsaved editor work: any action that would lose unsaved changes raises `unsaved_changes` unless the caller passes `discard=true`. Only processes this server launched are closed or killed.
- The install is read-only; the editor and game run from it untouched. Tests that drive the desktop carry `@pytest.mark.editor` / `@pytest.mark.game` (deselected by default) and only use scratch copies of maps under `tmp_path`.
- Commits end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`; stage explicit paths.

## Verified facts (live probes, scratch maps only)

- `World Editor.exe` without `-launch` starts the Blizzard launcher/Battle.net instead of the editor. `World Editor.exe -launch` shows the main window in ~4 s; `-launch -loadfile <absolute path>` opens that map (~7-9 s).
- Main window: class `OsWindow`, has a menu bar built at runtime; title `Warcraft III World Editor` (no map), `Warcraft III World Editor - [Untitled]`, or `Warcraft III World Editor - [C:/path/with/forward/slashes.w3x]`; unsaved changes append ` *` inside the brackets. A permanent `#32770` "Tool Palette" window belongs to the editor.
- Menu labels contain `&` accelerators and `\t` shortcuts; command ids come from `GetMenuItemID` (e.g. File: Open 64188, Close Map 64189, Save Map 4, Test Map 16; Scenario: Map Description 1024; Module: Trigger Editor 1793, Object Editor 1795). Posting `WM_COMMAND id` works without focus.
- Dialogs are `#32770` windows with ordinary Win32 controls: "Map Properties" (Name edit id 14, OK id 10, Cancel id 11); the editor's "Open Document" dialog is custom (directory edit, tree view) — open maps by relaunching with `-loadfile` instead.
- Save (`File > Save Map`): a transient "Progress" dialog ("Generating Map Script"), then the title loses ` *` and the file's mtime changes.
- Save with a script error: "Error" (`Trigger 'Broken' has been disabled due to errors.`, OK id 2) and "Script Errors" (trigger name static, "1 compile error", ListBox id 12 with `Line  17: Symbol not declared - ...`, script Edit id 13, OK id 10); the file is not written and after OK the map is dirty (trigger disabled).
- Closing a dirty map (`File > Close Map`) shows "Warning" `Save changes to '<path>'?` with Yes id 6 / No id 7 / Cancel id 2. `File > Exit` does nothing without a map; `WM_CLOSE` on the main window exits (same prompt when dirty).
- Trigger Editor / Object Editor open as top-level `#32770` windows with their own menus; `WM_CLOSE` closes them.
- `Documents\Warcraft III\Logs\War3EditorLog.txt` stays empty; load problems are drawn in the viewport only.
- Game: `Warcraft III.exe -launch -loadfile <absolute path> -windowmode windowed -nowfpause` opens an `OsWindow` "Warcraft III" in ~3 s and runs the map; `Logs\War3Log.txt` is rewritten from `GameMain Started` and flushed in bursts; thousands of `Opening map/mod` lines are noise. A map-init trigger's `PreloadGenEnd("wc3mcp\\probe.txt")` produced `Documents\Warcraft III\CustomMapData\wc3mcp\probe.txt` ~48 s after launch, containing `call Preload( "wc3mcp-probe-ok" )`. `WM_CLOSE` closes the game.

---

### Task 1: Win32 helpers (`wc3mcp.desktop.win`)

**Files:** Create `src/wc3mcp/desktop/__init__.py`, `src/wc3mcp/desktop/win.py`; Test `tests/desktop/test_win.py`.

**Interfaces:** `menu_label(text) -> str` (drop `&`, cut at `\t`, strip); `menu_tree(hmenu) -> list[{"label", "id"|None, "items"?}]`; `find_command(tree, path) -> int` (`"File/Save Map"`, case-insensitive; `ToolError("no_menu_item")` listing siblings); `processes(image_name) -> list[int]`; `windows(pid, visible_only=True) -> list[int]`; `info(hwnd) -> {"hwnd", "class", "title", "rect", "visible", "enabled"}`; `controls(hwnd) -> list[dict]` (adds `"id"`, `"text"`, `"checked"` for buttons, `"items"` for list/combo boxes; tolerant of windows vanishing); `set_text`, `click`, `check`, `select` (ComboBox/ListBox by text or index, notifying the parent); `post_command(hwnd, id)`; `close(hwnd)`; `screenshot(hwnd=None, region=None) -> bytes` (PNG; brings the window forward and restores the previous foreground window); `send_input(hwnd, actions)` (client-area clicks, drags, key chords, text; same foreground handling).

- [ ] Unit tests (no desktop): `menu_label("&Save Map\tCtrl+S") == "Save Map"`; `find_command` on a synthetic tree resolves `"file/save map"` and raises `no_menu_item` with the sibling labels; `parse_keys("ctrl+shift+s")` returns the virtual-key sequence.
- [ ] Editor-marked test: `windows()` of a launched editor contains an `OsWindow` whose `menu_tree` has `File/Save Map` and `Module/Trigger Editor`.
- [ ] Implement; `& $PY -m pytest tests/desktop -q` → pass; commit `feat(desktop): Win32 window, control, menu, input and screenshot helpers`.

### Task 2: Editor lifecycle (`wc3mcp.desktop.editor`)

**Files:** Create `src/wc3mcp/desktop/editor.py`; Test `tests/desktop/test_editor.py`.

**Interfaces:** `parse_title(title) -> {"map": str|None, "untitled": bool, "dirty": bool}` (forward slashes → OS path); `Editor` (module-level `EDITOR` singleton) with `status() -> {"running", "pid", "launched_by_server", "map", "dirty", "busy", "dialogs": [titles], "windows": [titles]}`; `launch(map_path=None, timeout=120)` (`editor_running` if one runs); `open(map_path, discard=False)` (relaunch with `-loadfile`; `unsaved_changes` when dirty and not discard); `save(timeout=300, dismiss_errors=True) -> {"saved", "errors": [{"trigger", "message", "line"}], "disabled_triggers", "dialogs"}`; `close(discard=False)`; `quit(discard=False)`; `reload(discard=False)`; `compile()` = save reporting script errors. Error codes: `editor_not_running`, `editor_running`, `no_map`, `unsaved_changes`, `timeout`, `launch_failed`.

- [ ] Unit tests: `parse_title` for the four verified title forms.
- [ ] Editor-marked test on a scratch copy of a JASS ladder map (and one built with a `CustomScriptCode` `call UndefinedThing()` trigger through `triggers_edit` + `script_build` + `MapProject.save`): launch with map → status shows map, not dirty; set the Map Properties name through `desktop.win` → dirty; `close()` raises `unsaved_changes`; `save()` → saved and clean; broken map `compile()` → `saved False`, one error for trigger "Broken", `disabled_triggers == ["Broken"]`; `close(discard=True)`; `quit()` → not running.
- [ ] Implement; run; commit `feat(desktop): World Editor lifecycle driver with take-turns safety`.

### Task 3: Editor UI access (menus, dialogs, input, screenshots, log)

**Files:** Modify `src/wc3mcp/desktop/editor.py`; Test `tests/desktop/test_editor.py` (append).

**Interfaces:** `Editor.menu(window=None) -> tree`, `Editor.invoke(path, window=None)` (window = title of a module window such as "Trigger Editor"; default main); `Editor.dialogs(include_palettes=False) -> [{"title", "hwnd", "controls"}]`; `Editor.dialog_act(dialog, actions) -> dialog snapshot` where an action is `{"control": id|text, "set_text"|"click"|"check"|"select": ...}`; `Editor.input(window, actions)`; `Editor.screenshot(target="main", region=None) -> bytes`; `Editor.log(lines=200) -> {"log", "crashes"}` (War3EditorLog.txt tail and the newest `Errors` folders).

- [ ] Editor-marked tests: `invoke("Scenario/Map Description...")` opens "Map Properties"; `dialog_act("Map Properties", [{"control": 14, "set_text": "X"}, {"control": "OK", "click": True}])` makes the map dirty; `invoke("Module/Trigger Editor")` opens a "Trigger Editor" window whose `menu(window="Trigger Editor")` is non-empty; `screenshot()` starts with the PNG signature; unknown dialog → `no_dialog`.
- [ ] Implement; run; commit `feat(desktop): editor menus, dialogs, input, screenshots and log`.

### Task 4: Game runner (`wc3mcp.desktop.game`)

**Files:** Create `src/wc3mcp/desktop/game.py`; Test `tests/desktop/test_game.py`.

**Interfaces:** `parse_preload(text) -> list[str]`; `interesting(lines) -> list[str]` (drops `Opening map/mod`, `prism: Info`); `Game` (module singleton `GAME`) with `test(map_path, timeout=240, results=None, close=True, screenshot=False) -> {"seconds", "results": {name: [str]}, "missing": [...], "log": [...], "crash": str|None, "closed", "screenshot"?}` (results are paths relative to `Documents\Warcraft III\CustomMapData`; stale result files are deleted before launch), `status()`, `close()` (only launched processes; `WM_CLOSE`, then kill after 20 s).

- [ ] Unit tests: `parse_preload` of the verified probe file; `interesting` filtering.
- [ ] Game-marked test: map built via `triggers_edit` (map-init `CustomScriptCode` Preload lines) + `script_build` + save in `tmp_path` → `test(path, results=["wc3mcp\\test.txt"])` returns the preload string and `closed True`.
- [ ] Implement; run; commit `feat(desktop): windowed game test runs with log and Preload results`.

### Task 5: Server tools and take-turns guard

**Files:** Modify `src/wc3mcp/server.py`, `tests/test_server.py`.

**Tools:** `editor_launch(map_path=None)`, `editor_status()`, `editor_map(action: open|save|close|reload|compile|quit, map_path=None, discard=False)`, `editor_menu(path=None, window=None)` (list when no path, invoke otherwise), `editor_screenshot(target="main", region=None) -> Image`, `editor_dialogs(include_palettes=False)`, `editor_dialog_act(dialog, actions)`, `editor_input(window, actions)`, `editor_log(lines=200)`, `game_test(path, timeout=240, results=None, close=True, screenshot=False)`, `game_status()`, `game_close()`. `map_save` (in place) raises `open_in_editor` when the editor has the same map open with unsaved changes, and adds a warning when it is open without changes ("reopen it in the editor to see the saved version").

- [ ] Tests: EXPECTED gains the 12 tools; unit test of the `map_save` guard with a stubbed `EDITOR.status`.
- [ ] Implement; full suite → pass; commit `feat(server): editor and game tools with take-turns guard on map_save`.
