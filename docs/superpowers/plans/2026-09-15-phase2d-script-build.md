# Phase 2d: Script Build and Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task (inline; the user asked for no subagents after spend-limit failures). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Regenerate the trigger-dependent parts of `war3map.j` exactly as the World Editor writes them, validate scripts (pjass / JassHelper for JASS, a Lua 5.3 syntax checker for Lua) and cross-check map files, through `script_build`, `script_validate`, `map_validate` and an automatic rebuild in `map_save`.

**Architecture:** New package `wc3mcp.script`: `jass.py` (GUI triggers → JASS sections), `build.py` (globals, InitGlobals, custom script, InitCustomTriggers, RunInitializationTriggers, splice into the existing script), `luacheck.py`, `validate.py` (tool copies under `%LOCALAPPDATA%\wc3mcp\tools`). `wc3mcp.ops.validate` holds map cross-checks; `wc3mcp.ops.script` exposes the tools on a `MapProject`.

**Tech Stack:** Python 3.13 Store interpreter, stdlib, `mcp` FastMCP, pytest; pjass/JassHelper copied from the install.

**Spec:** `docs/superpowers/specs/2026-09-14-wc3-mcp-design.md` (section 4 "Script & validation", 5 "Working copy" step 3, 6 "Validation tiers", "Install read-only")

## Global Constraints

- `$PY = "%LOCALAPPDATA%\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\python.exe"`, run from `D:\Warcraft III\wc3-mcp`.
- Branch `phase2d-script-build` (stacked on `phase2c-triggers`); no push/merge until all phases are complete.
- No new dependencies. The install is read-only: tools are copied to `config.home() / "tools"` and run there with timeouts; processes started are always reaped.
- Commits end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`; stage explicit paths.
- Verified prototypes live in the session scratchpad `…/scratchpad/phase2d/` (`$S` below). Tasks copy them and apply the listed edits instead of retyping ~1,500 verified lines; every copied module keeps its corpus test.

## Verified facts (local corpus: 462 JASS maps, 94 Lua maps)

- `jass.py` prototype regenerates 28,874 of 28,879 present trigger sections byte-exact; the 5 misses are 4 duplicate trigger names (name-keyed comparison artefact; order-based comparison matches) and 1 section contradicting its wtg (Undead06 "Load Arthas").
- Rules include: helpers `Trig_<name>_Func<ECA#>[<param#>|Func<child#>]...` with `C` (conditions of block functions), `A` (callbacks); children numbered by file position; helpers emitted children-first; conditions `if ( not ( a op b ) )` vs call-style `not GetBooleanOr( h1(), h2() )`; IfThenElse inline with a `…001` condition helper; WaitForCondition as `loop / exitwhen ( h() ) / call TriggerSleepAction(RMaxBJ(bj_WAIT_FOR_COND_MIN_INTERVAL, t)) / endloop`; leftover children of non-block functions still emit helpers; description header keeps its first line, drops later empty lines; the Actions function is always present.
- Script names: `re.sub(r"[^A-Za-z0-9_]", "_", name.rstrip())`, plus a trailing `u` when that ends with `_` (1,380 corpus triggers).
- `build.py` prototype: user globals, trigger globals, InitGlobals, custom script, InitCustomTriggers, RunInitializationTriggers exact on 462/462 maps; `splice(original) == original` on 461/462 (the Undead06 contradiction).
- Sections/InitTrig calls exist for triggers with `enabled and not is_comment`; every kind-8 trigger declares `gg_trg_<script name>` once; RunInitializationTriggers lists listed, initially-on triggers with `run_on_init` or an enabled MapInitializationEvent.
- The bundled pjass is `git-f128812` (modern options). `pjass common.j Blizzard.j -` reads the map script from stdin; errors are `<file>:<line>: <message>` with exit code 1; 460/462 corpus scripts pass (2 real type errors in shipped maps), median 45 ms. JassHelper `--scriptonly common.j Blizzard.j in.j out.j` needs `jasshelper.conf`, `pjass.exe`, `sfmpq.dll` beside it, writes `logs\compileerrors.txt` in its cwd and on errors spawns a `--showerrors` window process that must be killed.
- The World Editor produces Lua by transpiling its JASS (`jass2lua`, `__jarray`, `FourCC`); no local Lua map has GUI code beyond melee init, so Lua regeneration is deferred (see Task 6) until the editor driver (Phase 3) can confirm output.
- `luacheck.py` prototype: all 94 corpus Lua scripts check clean (1.8 s total), 209 unit/mutation tests pass.
- `mapvalidate.py` prototype: zero errors on all 556 maps; warnings only for missing imports, unknown object base ids/fields, TRIGSTR references without entries.

---

### Task 1: Editor script names

**Files:** Modify `src/wc3mcp/ops/gui.py` (`script_name`); Test `tests/ops/test_gui.py` (`test_script_names_follow_the_editor`, already extended with `----Observatory Quest----` → `____Observatory_Quest____u`).

- [ ] Run `& $PY -m pytest tests/ops/test_gui.py -q -k script_names` → FAIL.
- [ ] Implement:
```python
def script_name(name: str) -> str:
    """The identifier the editor derives from a trigger name (gg_trg_<this>): trailing spaces dropped, leading kept,
    and a trailing '_' followed by 'u' (JASS identifiers cannot end with an underscore)."""
    ident = re.sub(r"[^A-Za-z0-9_]", "_", name.rstrip())
    return ident + "u" if ident.endswith("_") else ident
```
- [ ] Run `& $PY -m pytest tests/ops -q` → pass; commit `fix(ops): trailing-underscore trigger script names get the editor's 'u' suffix`.

### Task 2: GUI triggers → JASS (`wc3mcp.script.jass`)

**Files:** Create `src/wc3mcp/script/__init__.py` (docstring only), `src/wc3mcp/script/jass.py` (copy of `$S/jassgen.py`); Test `tests/script/test_jass.py`.

**Interfaces:** Produces `BAR`, `JassGen(td, variables_by_name).section(trigger, wct_text) -> str` (LF newlines).

- [ ] Write the test:
```python
import re

import pytest

from corpus import HAVE_INSTALL, _storage, open_sample, sample_map_ids
from wc3mcp.formats import wct, wtg
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.script.jass import BAR, JassGen

pytestmark = pytest.mark.skipif(not HAVE_INSTALL, reason="needs TriggerData from the install")


@pytest.fixture(scope="module")
def td():
    return Catalog(_storage(), balance=None).trigger_data


@pytest.mark.parametrize("map_id", sample_map_ids())
def test_trigger_sections_match_the_editor(map_id, td):
    arc = open_sample(map_id)
    script, data = arc.read("war3map.j"), arc.read("war3map.wtg")
    if script is None or data is None:
        pytest.skip("not a JASS map with triggers")
    tf, ct = wtg.parse(data, td.arg_count), wct.parse(arc.read("war3map.wct"))
    text = script.decode("utf-8").replace("\r\n", "\n")
    expected = [p for p in re.split(r"(?m)^(?=" + re.escape(BAR) + r"\n(?:// Trigger: |function InitCustomTriggers))", text)
                if p.startswith(BAR + "\n// Trigger: ")]
    gen = JassGen(td, {v.name: v for v in tf.variables})
    triggers = [e for e in tf.elements if isinstance(e, wtg.Trigger) and e.kind == wtg.TRIGGER]
    got = [gen.section(t, s) for t, s in zip(triggers, ct.texts) if t.enabled and not t.is_comment]
    assert got == expected
```
- [ ] Run → FAIL (`No module named 'wc3mcp.script'`).
- [ ] Copy `$S/jassgen.py` to `src/wc3mcp/script/jass.py`; replace its header (docstring, imports and the local `script_name`) with:
```python
"""GUI triggers -> the World Editor's JASS: one trigger's section of war3map.j, byte-identical to the editor's output
(28,874 of 28,879 local corpus triggers; the rest contradict their stored trigger data)."""
from ..formats.wtg import ECA, FUNCTION, PRESET, STRING, VARIABLE
from ..gamedata.triggerdata import ACTION, CALL, CONDITION, EVENT
from ..ops.gui import RAWCODE_TYPES, script_name, var_type
```
- [ ] Run `& $PY -m pytest tests/script -q` → pass; commit `feat(script): editor-identical JASS for GUI triggers`.

### Task 3: Trigger-dependent script parts and splice (`wc3mcp.script.build`)

**Files:** Modify `src/wc3mcp/gamedata/triggerdata.py` (`type_defaults`); Create `src/wc3mcp/script/build.py` (from `$S/globals/scriptgen.py`); Test `tests/script/test_build.py`.

**Interfaces:** `TriggerData.type_defaults: dict[str, str]` ([TriggerTypeDefaults] value 0). `build.triggers(tf)`, `listed(t)`, `runs_on_init(t)`, `user_globals(tf, td)`, `trigger_globals(tf)`, `init_globals(tf, td)`, `custom_script(ct)`, `trigger_sections(tf, ct, td)`, `init_custom_triggers(tf)`, `run_initialization_triggers(tf)`, `splice(original: str, tf, ct, td) -> str` (raises `ValueError` when the script is not editor-generated).

- [ ] Write the test:
```python
import pytest

from corpus import HAVE_INSTALL, _storage, open_sample, sample_map_ids
from wc3mcp.formats import wct, wtg
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.script import build

pytestmark = pytest.mark.skipif(not HAVE_INSTALL, reason="needs TriggerData from the install")


@pytest.fixture(scope="module")
def td():
    return Catalog(_storage(), balance=None).trigger_data


def test_type_defaults(td):
    assert td.type_defaults["group"] == "CreateGroup()" and td.type_defaults["boolean"] == "false"


@pytest.mark.parametrize("map_id", sample_map_ids())
def test_splice_reproduces_editor_scripts(map_id, td):
    arc = open_sample(map_id)
    script, data = arc.read("war3map.j"), arc.read("war3map.wtg")
    if script is None or data is None:
        pytest.skip("not a JASS map with triggers")
    original = script.decode("utf-8")
    assert build.splice(original, wtg.parse(data, td.arg_count), wct.parse(arc.read("war3map.wct")), td) == original


def test_splice_rejects_foreign_scripts(td):
    with pytest.raises(ValueError):
        build.splice("function main takes nothing returns nothing\r\nendfunction\r\n", wtg.TriggerFile(), wct.CustomText(), td)
```
- [ ] Run → FAIL.
- [ ] In `TriggerData.__init__` add `self.type_defaults: dict[str, str] = {}`; in `parse` add
```python
        for name, value in rows.get("TriggerTypeDefaults", {}).items():
            td.type_defaults[name] = split_list(value)[0].strip()
```
- [ ] Copy `$S/globals/scriptgen.py` to `src/wc3mcp/script/build.py`; replace everything above `# ---- globals ----` with:
```python
"""Trigger-dependent parts of an editor-generated war3map.j, from war3map.wtg + war3map.wct, and splice() that swaps
them into an existing script keeping every other byte. Exact on all local JASS corpus maps."""
import re

from ..formats import wtg
from ..gamedata.triggerdata import EVENT
from ..ops.gui import RAWCODE_TYPES, script_name
from .jass import BAR, JassGen

BANNER = "//" + "*" * 75


def banner(title: str) -> str:
    return f"{BANNER}\n//*\n//*  {title}\n//*\n{BANNER}\n"


def triggers(tf) -> list:
    return [e for e in tf.elements if isinstance(e, wtg.Trigger) and e.kind == wtg.TRIGGER]


def listed(t) -> bool:
    """Triggers that get a script section and an InitTrig call."""
    return bool(t.enabled) and not t.is_comment


def runs_on_init(t) -> bool:
    return listed(t) and not t.initially_off and bool(
        t.run_on_init or any(e.kind == EVENT and e.enabled and e.name == "MapInitializationEvent" for e in t.ecas))
```
  and change `init_globals(tf, td, defaults=None)` / `splice(..., defaults=None)` to use `td.type_defaults` (drop the `defaults` parameters and `DEFAULTS`).
- [ ] Run `& $PY -m pytest tests/script tests/gamedata -q` → pass; commit `feat(script): regenerate globals, InitGlobals and trigger sections into editor scripts`.

### Task 4: Lua syntax checker (`wc3mcp.script.luacheck`)

**Files:** Create `src/wc3mcp/script/luacheck.py` (verbatim copy of `$S/luacheck/luacheck.py`, first docstring line kept); Test `tests/script/test_luacheck.py` (copy of `$S/luacheck/test_luacheck.py` with `from luacheck import …` changed to `from wc3mcp.script.luacheck import …` and corpus paths replaced by `sample_map_ids()` Lua maps).

- [ ] Copy the test, fix imports, run → FAIL; copy the module; run `& $PY -m pytest tests/script -q` → pass; commit `feat(script): pure-Python Lua 5.3 syntax checker`.

### Task 5: Script validation tools (`wc3mcp.script.validate`)

**Files:** Create `src/wc3mcp/script/validate.py` (from `$S/pjass/validate.py`); Test `tests/script/test_validate.py`.

**Interfaces:** `tool_dir(catalog) -> Path` (copies `install/_retail_/x86_64/JassHelper` to `config.home()/tools/jasshelper` when missing or when `pjass.exe` size differs, and writes `common.j`/`Blizzard.j` from `catalog._read("Scripts/common.j")` there); `is_vjass(text) -> bool`; `validate_jass(text, catalog, vjass=None, timeout=60) -> {"ok", "errors": [{"line", "message", "section", "trigger", "source"}], "tool", "seconds"}`; `validate_lua(text) -> same shape` (tool "luacheck").

- [ ] Test: WarChasers `war3map.j` → ok; inject `set udg_DoesNotExist = 5` after `function Trig_RoboX_Actions…` → one error with trigger "RoboX"; a vJASS `library`/`struct` sample → ok with `tool == "jasshelper --scriptonly"`; `validate_lua("function f(\nend end")` → one error on line 2; after each run no `jasshelper.exe` process remains.
- [ ] Copy prototype, replace `__main__` self-test with the tool-dir helpers above, keep `_pjass`, `_jasshelper`, `section_index`, `_locate`; run tests → pass; commit `feat(script): pjass/JassHelper and Lua syntax validation`.

### Task 6: Map cross-checks and project operations

**Files:** Create `src/wc3mcp/ops/validate.py` (from `$S/mapvalidate/mapvalidate.py`, using `gui.script_name`), `src/wc3mcp/ops/script.py`; Tests `tests/ops/test_validate.py`, `tests/ops/test_script.py`.

**Interfaces:** `validate.validate(files: dict[str, bytes], catalog, has_file=None) -> {"errors", "warnings"}`; `script.script_build(project, catalog) -> {"changed", "language", "warnings"}` (JASS maps: splice war3map.j; Lua maps: `ToolError("lua_not_supported", …, hint="save the map in the World Editor to regenerate war3map.lua")` — ponytail until Phase 3 can confirm transpiled Lua; maps without war3map.wtg: `no_triggers`); `script.script_validate(project, catalog) -> {"language", ...validate result}`; `script.map_validate(project, catalog) -> {"errors", "warnings"}`.

- [ ] Tests: corpus sample maps give zero `map_validate` errors; melee ladder map + `triggers_edit` creating a DisplayTextToForce trigger → `script_build` changes war3map.j so it contains `function InitTrig_Hello` and `call InitTrig_Hello(  )`, then `script_validate` is ok; a CustomScriptCode action `call UndefinedThing()` → `script_validate` error with trigger "Hello"; a Lua ladder map → `lua_not_supported`.
- [ ] Implement, run `& $PY -m pytest tests/ops -q` → pass; commit `feat(ops): script_build, script_validate and map_validate`.

### Task 7: Server tools and save-time rebuild

**Files:** Modify `src/wc3mcp/server.py` (tools `script_build`, `script_validate`, `map_validate`; `map_save(..., rebuild_script: Literal["auto", "always", "never"] = "auto", validate: bool = True)`), `src/wc3mcp/ops/triggers.py` and `src/wc3mcp/ops/info.py` (warning texts now point at `map_save`/`script_build`), `tests/test_server.py`.

- [ ] `map_save`: `auto` rebuilds when `war3map.wtg` or `war3map.wct` is dirty and the map is JASS with trigger data (Lua maps add a warning); `always` rebuilds whenever possible; then, when `validate`, runs `map_validate` and refuses with `ToolError("validation_failed", …, errors=…)` on errors; the result gains `"script": {...}` and `"validation": {...}`.
- [ ] Tests: EXPECTED gains the three tools; `test_script_tools` edits a trigger, saves with default options, reopens the saved map and finds the regenerated trigger in war3map.j; full suite passes.
- [ ] Commit `feat(server): script tools and automatic script rebuild on save`.
