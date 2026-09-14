# Phase 2c: Triggers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read and edit a map's triggers headlessly: GUI triggers as JSON validated against the game's TriggerData, custom-text triggers, categories, global variables and the map custom script header, through `triggers_tree`, `trigger_get` and `triggers_edit`, plus trigger kinds in `data_search`/`data_get`.

**Architecture:** `gamedata/triggerdata.py` parses `UI/TriggerData.txt` (signatures, types, presets, categories, type compatibility). `formats/wtg.py` and `formats/wct.py` are byte-exact codecs. `ops/gui.py` converts ECA trees to/from JSON, renders editor text and checks GUI code. `ops/triggers.py` implements the three tools on a `MapProject`; edits are atomic and rewrite only `war3map.wtg`/`war3map.wct`.

**Tech Stack:** Python 3.13 (Store interpreter), stdlib, `mcp` FastMCP, pytest.

**Spec:** `docs/superpowers/specs/2026-09-14-wc3-mcp-design.md` (section 4 "Triggers (3)", "Game data (3)"; principles 1-2)

## Global Constraints

- Interpreter: `$PY = "%LOCALAPPDATA%\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\python.exe"`, run from `D:\Warcraft III\wc3-mcp`.
- Branch `phase2c-triggers`, stacked on `phase2b-object-data`. Do not push or merge until all phases are complete.
- No new dependencies. The game install is read-only; corpus tests read maps at runtime and never commit them.
- Codecs must round-trip byte-exact on the corpus before any write path uses them.
- Errors are `ToolError(code, message, hint=..., **details)`; every batch error carries `op_index`; failed batches write nothing.
- Commit messages end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`; stage explicit paths only.

## Verified facts (556 local maps: 465 Blizzard CASC maps + 91 ladder maps)

- Every `war3map.wtg` is `WTG!`, u32 `0x80000004`, i32 version 7; every `war3map.wct` is u32 `0x80000004`, i32 version 1. No older formats exist locally.
- wtg header: 8 pairs `(i32 counter, i32 n, n × i32 deleted ids)` for element kinds 1, 2, 4, 8, 16, 32, 64, 128, then i32 `2`. For triggers/comments/variables the counter equals live + deleted and the deleted ids are the gaps (next id = counter); category counters are irregular.
- Then i32 variable count; variable = cstr name, cstr type, u32 1, u32 is_array, u32 array_size, u32 initialized, cstr initial, i32 id (`0x06xxxxxx`), i32 parent (a category id, always).
- Then i32 element count; element = u32 kind:
  - 1 root / 2 library / 4 category: i32 id, cstr name, u32 is_comment, u32 expanded, i32 parent (root: id 0, name = map file name, parent −1; category ids `0x02xxxxxx`, top-level parent 0).
  - 8 trigger / 16 comment / 32 script: cstr name, cstr description, u32 is_comment, i32 id (`0x03`/`0x04` prefix), u32 enabled, u32 custom_text, u32 initially_off, u32 run_on_init, i32 parent, i32 ECA count, ECAs.
  - 64 variable: i32 id, cstr name, i32 parent.
  - Parents always precede children. Kinds 2, 32 and 128 have no live elements locally.
- ECA = i32 kind (0 event, 1 condition, 2 action), [i32 group — children only], cstr name, u32 enabled, parameters (count from TriggerData), i32 child count, children. Top-level ECAs are stored in insertion order (not grouped by kind).
- Parameter = i32 type (0 preset, 1 variable, 2 function, 3 string, −1 unset), cstr value, u32 has_call; if 1: i32 call kind (3 call; 0/1/2 when the argument type is eventcall / boolexpr or boolcall / code — always), cstr name, u32 has_params, params, u32 0; then u32 has_index; if 1: index parameter. `has_call` ⇔ type 2; `has_index` only on variables and always matches the variable's is_array.
- Call param value: kind 3 and 2 store the function name, kinds 0/1 store `""` (older files keep stale values).
- Child groups: IfThenElseMultiple 0 = conditions, 1 = then, 2 = else; And/OrMultiple 0 = conditions; every other `*Multiple` 0 = loop actions. A few non-block functions keep leftover children.
- wct: u32 marker, i32 1, cstr comment, sized header text, then one sized text per kind-8 element in element order (no count). Sized text = u32 size (0 = none) + bytes including a trailing NUL. `custom_text` = 1 ⇔ non-empty text (one exception).
- TriggerData: argument count = values after the version (calls: after version, events flag, return type) that are not empty or `nothing`; per-section lookup resolves every function in the corpus.
- Type compatibility accepting every enabled GUI call in the corpus: equal types; `AnyGlobal`; equal base types (TriggerTypes column 4); `boolcall` ← `boolexpr`; `VarAsString_X` ← variable of type `x`; `handle` ← any non-primitive; `musicfile` ← `sound`; SetVariable's second argument takes the first argument's variable type. Generated globals `gg_trg_`/`gg_rct_`/`gg_snd_`/`gg_cam_`/`gg_unit_`/`gg_item_`/`gg_dest_` are variables of type trigger/rect/sound/camerasetup/unit/item/destructable. Literals: integer `-?\d+`, real parses as float, boolean `true`/`false`, raw-code types 4 bytes. Unset (−1) parameters occur only in disabled ECAs. 35 `gg_trg_` references to missing triggers exist (warning, not error).
- Editor text: `_X_Parameters` pieces with `~Name` placeholders (8 functions have malformed layouts; SetVariable's layout starts with its display name); category prefix `"<Category> - "` unless TriggerCategories value 2 is `1`.

## File structure

- Create `src/wc3mcp/gamedata/triggerdata.py` — TriggerData model and parser.
- Modify `src/wc3mcp/gamedata/catalog.py` — `trigger_data` property; `trigger_function` / `trigger_type` / `trigger_preset` kinds.
- Create `src/wc3mcp/formats/wtg.py`, `src/wc3mcp/formats/wct.py` — codecs.
- Create `src/wc3mcp/ops/gui.py` — ECA JSON, editor text, checker.
- Create `src/wc3mcp/ops/triggers.py` — `triggers_tree`, `trigger_get`, `triggers_edit`.
- Modify `src/wc3mcp/server.py` — three tools, `Kind` literal.
- Modify `tests/corpus.py` — add a sample map with deleted-id counters.
- Tests: `tests/gamedata/test_triggerdata.py`, `tests/formats/test_wtg.py`, `tests/ops/test_gui.py`, `tests/ops/test_triggers.py`, `tests/test_server.py`.

---

### Task 1: TriggerData and trigger kinds in the catalog

**Files:**
- Create: `src/wc3mcp/gamedata/triggerdata.py`
- Modify: `src/wc3mcp/gamedata/catalog.py`
- Test: `tests/gamedata/test_triggerdata.py`

**Interfaces:**
- Consumes: `gamedata.profile.split_list`; `Catalog._read`, `Catalog.westring`.
- Produces: `triggerdata.EVENT, CONDITION, ACTION, CALL` (0-3), `KIND_NAMES`, dataclasses `TriggerType(name, global_ok, comparable, display, base)`, `Preset(name, type, code, display)`, `Function(kind, name, args, returns, display, layout, defaults, category, script_name)`, `TriggerData` with `categories: dict[str, tuple[str, bool]]`, `types`, `presets`, `functions` (tuple of 4 dicts), `parse(data, westring)`, `function(kind, name)`, `arg_count(kind, name) -> int | None`, `base(type)`, `compatible(expected, actual)`. `Catalog.trigger_data`; `Catalog.search/get` accept kinds `trigger_function`, `trigger_type`, `trigger_preset`.

- [ ] **Step 1: Write the failing test**

`tests/gamedata/test_triggerdata.py`:
```python
import pytest

from corpus import INSTALL, needs_install
from wc3mcp.casc.storage import open_storage
from wc3mcp.errors import ToolError
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.gamedata.triggerdata import ACTION, CALL, CONDITION, EVENT, Preset

pytestmark = needs_install


@pytest.fixture(scope="module")
def cat():
    return Catalog(open_storage(INSTALL), balance=None)


def test_function_signatures(cat):
    td = cat.trigger_data
    assert td.function(EVENT, "MapInitializationEvent").args == ()
    assert td.function(EVENT, "TriggerRegisterCommandEvent").args == ("abilcode", "unitorderEx")
    compare = td.function(CONDITION, "OperatorCompareInteger")
    assert compare.args == ("integer", "ComparisonOperator", "integer") and compare.display == "Integer Comparison"
    show = td.function(ACTION, "DisplayTextToForce")
    assert show.layout == ("Display to ", "~Player Group", " the text: ", "~Text") and show.category == "TC_GAME"
    assert td.function(ACTION, "TriggerSleepAction").defaults == ("2",)
    assert td.function(ACTION, "ForLoopAMultiple").display == "For Each Integer A, Do Multiple Actions"
    arith = td.function(CALL, "OperatorInt")
    assert arith.returns == "integer" and arith.args == ("integer", "ArithmeticOperator", "integer")
    assert td.function(ACTION, "GetTriggerUnit") is None and td.arg_count(CALL, "GetTriggerUnit") == 0
    assert td.arg_count(ACTION, "NoSuchFunction") is None and td.arg_count(9, "KillUnit") is None


def test_types_presets_and_categories(cat):
    td = cat.trigger_data
    assert td.types["unitcode"].base == "integer" and td.types["unitcode"].display == "Unit-Type"
    assert td.types["unit"].global_ok and td.base("unit") == "unit"
    assert td.presets["OperatorGreater"] == Preset("OperatorGreater", "ComparisonOperator", ">", "Greater than")
    assert td.categories["TC_GAME"] == ("Game", True) and td.categories["TC_WAIT"] == ("Wait", False)


def test_compatibility_rules(cat):
    td = cat.trigger_data
    assert td.compatible("unit", "unit") and td.compatible("AnyGlobal", "timer")
    assert td.compatible("StringExt", "string") and td.compatible("boolcall", "boolexpr")
    assert td.compatible("VarAsString_Real", "real") and td.compatible("handle", "unit")
    assert td.compatible("musicfile", "sound")
    assert not td.compatible("unit", "item") and not td.compatible("handle", "integer")
    assert not td.compatible("integer", "real")


def test_data_search_and_get(cat):
    hits = cat.search("trigger_function", "wait", limit=500)
    assert {"id": "TriggerSleepAction", "name": "Wait", "suffix": "action"} in hits
    assert cat.get("trigger_function", "DisplayTextToForce")["variants"] == [
        {"kind": "action", "args": ["force", "StringExt"], "returns": None,
         "text": "Display to ~Player Group the text: ~Text", "defaults": ["GetPlayersAll", "_"], "category": "Game"}]
    assert cat.get("trigger_type", "unitcode")["base"] == "integer"
    assert "OperatorGreater" in cat.get("trigger_type", "ComparisonOperator")["presets"]
    assert cat.get("trigger_preset", "OperatorGreater")["code"] == ">"
    with pytest.raises(ToolError) as e:
        cat.get("trigger_function", "NoSuchFunction")
    assert e.value.code == "not_found"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& $PY -m pytest tests/gamedata/test_triggerdata.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'wc3mcp.gamedata.triggerdata'`

- [ ] **Step 3: Write minimal implementation**

`src/wc3mcp/gamedata/triggerdata.py`:
```python
"""UI/TriggerData.txt: GUI trigger categories, variable types, preset values and function signatures."""
from dataclasses import dataclass

from .profile import split_list

EVENT, CONDITION, ACTION, CALL = 0, 1, 2, 3
KIND_NAMES = ("event", "condition", "action", "call")
_SECTIONS = {"TriggerEvents": EVENT, "TriggerConditions": CONDITION, "TriggerActions": ACTION, "TriggerCalls": CALL}


@dataclass(frozen=True)
class TriggerType:
    name: str
    global_ok: bool     # usable as a global variable type
    comparable: bool
    display: str
    base: str           # underlying type (unitcode -> integer); the name itself when it has none


@dataclass(frozen=True)
class Preset:
    name: str
    type: str
    code: str
    display: str


@dataclass(frozen=True)
class Function:
    kind: int
    name: str
    args: tuple[str, ...]
    returns: str | None = None      # calls only
    display: str = ""
    layout: tuple[str, ...] = ()    # editor text pieces; "~Name" pieces are parameters
    defaults: tuple[str, ...] = ()
    category: str = ""
    script_name: str | None = None


def _text(value: str) -> str:
    return value.strip().strip('"')


class TriggerData:
    def __init__(self):
        self.categories: dict[str, tuple[str, bool]] = {}   # code -> (display name, shown before function text)
        self.types: dict[str, TriggerType] = {}
        self.presets: dict[str, Preset] = {}
        self.functions: tuple[dict[str, Function], ...] = ({}, {}, {}, {})

    @classmethod
    def parse(cls, data: bytes, westring=lambda s: s) -> "TriggerData":
        rows: dict[str, dict[str, str]] = {}
        section = None
        for line in data.decode("utf-8-sig", "replace").splitlines():
            s = line.strip()
            if not s or s.startswith("//"):
                continue
            if s.startswith("[") and "]" in s:
                section = rows.setdefault(s[1:s.index("]")], {})
            elif section is not None and "=" in s:
                key, value = s.split("=", 1)
                section[key.strip()] = value.strip()
        td = cls()
        for code, value in rows.get("TriggerCategories", {}).items():
            v = split_list(value) + ["", "", ""]
            td.categories[code] = (westring(v[0]), v[2].strip() != "1")
        for name, value in rows.get("TriggerTypes", {}).items():
            v = split_list(value) + [""] * 7
            td.types[name] = TriggerType(name, v[1] == "1", v[2] == "1", westring(v[3]), v[4] or name)
        for name, value in rows.get("TriggerParams", {}).items():
            v = split_list(value) + [""] * 4
            td.presets[name] = Preset(name, v[1], v[2], westring(_text(v[3])))
        for section_name, kind in _SECTIONS.items():
            entries = rows.get(section_name, {})
            for name, value in entries.items():
                if name.startswith("_"):
                    continue
                v = [x.strip() for x in split_list(value)]
                layout, defaults = entries.get(f"_{name}_Parameters"), entries.get(f"_{name}_Defaults")
                td.functions[kind][name] = Function(
                    kind, name, tuple(a for a in v[3 if kind == CALL else 1:] if a and a != "nothing"),
                    v[2] if kind == CALL and len(v) > 2 else None,
                    _text(entries.get(f"_{name}_DisplayName", name)),
                    tuple(split_list(layout)) if layout else (),
                    tuple(split_list(defaults)) if defaults else (),
                    entries.get(f"_{name}_Category") or entries.get(f"_{name}_CATEGORY", ""),
                    entries.get(f"_{name}_ScriptName"))
        return td

    def function(self, kind: int, name: str) -> Function | None:
        return self.functions[kind].get(name) if 0 <= kind < 4 else None

    def arg_count(self, kind: int, name: str) -> int | None:
        fn = self.function(kind, name)
        return None if fn is None else len(fn.args)

    def base(self, type_name: str) -> str:
        t = self.types.get(type_name)
        return t.base if t else type_name

    def compatible(self, expected: str, actual: str) -> bool:
        """Whether a value of type `actual` fits a parameter of type `expected`. These rules accept every enabled GUI
        function call in the 556 local Blizzard and ladder maps."""
        if actual == expected or expected == "AnyGlobal" or self.base(actual) == self.base(expected):
            return True
        if expected == "boolcall":
            return actual == "boolexpr"
        if expected.startswith("VarAsString_"):
            return actual == expected[len("VarAsString_"):].lower()
        if expected == "handle":
            return self.base(actual) not in ("integer", "real", "boolean", "string", "code")
        return expected == "musicfile" and actual == "sound"
```

In `src/wc3mcp/gamedata/catalog.py`:
- add `from .triggerdata import KIND_NAMES, TriggerData` to the imports;
- replace `KINDS = ...` with
```python
TRIGGER_KINDS = ("trigger_function", "trigger_type", "trigger_preset")
KINDS = tuple(OBJECT_KINDS) + tuple(ROW_KINDS) + tuple(PATH_KINDS) + TRIGGER_KINDS
```
- add after `westring`:
```python
    @cached_property
    def trigger_data(self) -> TriggerData:
        return TriggerData.parse(self._read("UI/TriggerData.txt") or b"", self.westring)

    def _trigger_rows(self, kind: str) -> list[dict]:
        td = self.trigger_data
        if kind == "trigger_function":
            return [{"id": f.name, "name": f.display, "suffix": KIND_NAMES[f.kind]}
                    for table in td.functions for f in table.values()]
        if kind == "trigger_type":
            return [{"id": t.name, "name": t.display, "suffix": "" if t.base == t.name else t.base}
                    for t in td.types.values()]
        return [{"id": p.name, "name": p.display, "suffix": p.type} for p in td.presets.values()]

    def _trigger_get(self, kind: str, obj_id: str, missing: ToolError) -> dict:
        td = self.trigger_data
        if kind == "trigger_function":
            found = [table[obj_id] for table in td.functions if obj_id in table]
            if not found:
                raise missing
            return {"kind": kind, "id": obj_id, "name": found[0].display, "variants": [
                {"kind": KIND_NAMES[f.kind], "args": list(f.args), "returns": f.returns, "text": "".join(f.layout),
                 "defaults": list(f.defaults), "category": td.categories.get(f.category, (f.category,))[0]}
                for f in found]}
        if kind == "trigger_type":
            t = td.types.get(obj_id)
            if t is None:
                raise missing
            return {"kind": kind, "id": obj_id, "name": t.display, "base": t.base, "global": t.global_ok,
                    "comparable": t.comparable, "presets": [p.name for p in td.presets.values() if p.type == obj_id]}
        p = td.presets.get(obj_id)
        if p is None:
            raise missing
        return {"kind": kind, "id": obj_id, "name": p.display, "type": p.type, "code": p.code}
```
- in `search`, directly after `self._check(kind)`:
```python
        if kind in TRIGGER_KINDS:
            q = query.casefold()
            hits = [r for r in self._trigger_rows(kind) if q in r["id"].casefold() or q in r["name"].casefold()]
            return hits[offset:offset + limit]
```
- in `get`, directly after the `missing = ToolError(...)` line:
```python
        if kind in TRIGGER_KINDS:
            return self._trigger_get(kind, obj_id, missing)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `& $PY -m pytest tests/gamedata -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/wc3mcp/gamedata/triggerdata.py src/wc3mcp/gamedata/catalog.py tests/gamedata/test_triggerdata.py
git commit -m "feat(gamedata): TriggerData signatures, types, presets and trigger data kinds" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: wtg and wct codecs

**Files:**
- Create: `src/wc3mcp/formats/wtg.py`, `src/wc3mcp/formats/wct.py`
- Modify: `tests/corpus.py` (`CASC_SAMPLE_MAPS`)
- Test: `tests/formats/test_wtg.py`

**Interfaces:**
- Consumes: `formats.binary.Reader/Writer/FormatError`; Task 1 `TriggerData.arg_count` (tests only).
- Produces: `wtg` constants `PRESET, VARIABLE, FUNCTION, STRING, INVALID`, `ROOT, LIBRARY, CATEGORY, TRIGGER, COMMENT, SCRIPT, VARIABLE_ELEMENT`, `ID_PREFIX`; dataclasses `Call(kind, name, params, unknown)`, `Param(type, value, call, index)`, `ECA(kind, name, enabled, params, children, group)`, `Variable(name, type, unknown, is_array, array_size, initialized, initial, id, parent)`, `Category(kind, id, name, is_comment, expanded, parent)`, `Trigger(kind, name, description, is_comment, id, enabled, custom_text, initially_off, run_on_init, parent, ecas)`, `VariableElement(id, name, parent)`, `TriggerFile(version, counters, definition_version, variables, elements, trailing)`; `parse(data, count: Callable[[int, str], int | None]) -> TriggerFile`, `serialize(tf) -> bytes`. `wct.CustomText(version, comment, header, texts)`, `wct.parse(data)`, `wct.serialize(ct)`.

- [ ] **Step 1: Write the failing test**

In `tests/corpus.py`, add to `CASC_SAMPLE_MAPS` after the `HumanX04Interlude` line:
```python
    "Campaign/Reforged/ROC/Human05.w3x",            # wtg with deleted-id counters (comments, kind 128)
```

`tests/formats/test_wtg.py`:
```python
import pytest

from corpus import HAVE_INSTALL, _storage, open_sample, sample_map_ids
from wc3mcp.formats import wct, wtg
from wc3mcp.formats.binary import FormatError
from wc3mcp.formats.wtg import ECA, Call, Category, Param, Trigger, TriggerFile, Variable, VariableElement

ARGS = {(0, "MapInitializationEvent"): 0, (1, "OperatorCompareBoolean"): 3, (2, "TriggerSleepAction"): 1,
        (2, "IfThenElseMultiple"): 0, (3, "GetBooleanAnd"): 2}


def fake_count(kind, name):
    return ARGS.get((kind, name))


def sample_file() -> TriggerFile:
    condition = ECA(1, "OperatorCompareBoolean", params=[
        Param(1, "flag", index=Param(3, "1")), Param(0, "OperatorEqualENE"),
        Param(2, "GetBooleanAnd", Call(3, "GetBooleanAnd", [Param(3, "true"), Param(-1, "")]))])
    block = ECA(2, "IfThenElseMultiple", children=[
        condition, ECA(2, "TriggerSleepAction", enabled=0, params=[Param(3, "1")], group=1)])
    start = Trigger(8, "Start", "desc", id=0x03000000, parent=0x02000000,
                    ecas=[ECA(0, "MapInitializationEvent"), ECA(2, "TriggerSleepAction", params=[Param(3, "2")]), block])
    return TriggerFile(
        counters=[(1, []), (0, []), (2, [1]), (1, []), (1, []), (0, []), (1, []), (0, [])],
        variables=[Variable("flag", "boolean", is_array=1, array_size=4, id=0x06000000, parent=0x02000000)],
        elements=[Category(1, 0, "map.w3x"), Category(4, 0x02000000, "Init", expanded=1, parent=0), start,
                  Trigger(16, "note", "a comment", is_comment=1, id=0x04000000, parent=0x02000000),
                  VariableElement(0x06000000, "flag", 0x02000000)])


def test_constructed_roundtrip():
    tf = sample_file()
    assert wtg.parse(wtg.serialize(tf), fake_count) == tf
    ct = wct.CustomText(comment="map notes", header="// header",
                        texts=[None, "function X takes nothing returns nothing\nendfunction"])
    assert wct.parse(wct.serialize(ct)) == ct


def test_rejects_unsupported_input():
    with pytest.raises(FormatError):
        wtg.parse(b"WTG!" + (7).to_bytes(4, "little") + bytes(8), fake_count)
    with pytest.raises(FormatError):
        wtg.parse(wtg.serialize(sample_file()), lambda kind, name: None)
    with pytest.raises(FormatError):
        wct.parse((1).to_bytes(4, "little") + bytes(8))


@pytest.fixture(scope="module")
def trigger_data():
    from wc3mcp.gamedata.catalog import Catalog

    return Catalog(_storage(), balance=None).trigger_data


@pytest.mark.skipif(not HAVE_INSTALL, reason="needs TriggerData from the install")
@pytest.mark.parametrize("map_id", sample_map_ids())
def test_corpus_roundtrip_is_byte_exact(map_id, trigger_data):
    arc = open_sample(map_id)
    data = arc.read("war3map.wtg")
    if data is None:
        pytest.skip("map has no trigger data")
    tf = wtg.parse(data, trigger_data.arg_count)
    assert tf.trailing == b"" and wtg.serialize(tf) == data
    text = arc.read("war3map.wct")
    ct = wct.parse(text)
    assert wct.serialize(ct) == text
    assert len(ct.texts) == sum(1 for e in tf.elements if isinstance(e, Trigger) and e.kind == wtg.TRIGGER)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& $PY -m pytest tests/formats/test_wtg.py -q`
Expected: FAIL with `ImportError: cannot import name 'wct' from 'wc3mcp.formats'`

- [ ] **Step 3: Write minimal implementation**

`src/wc3mcp/formats/wtg.py`:
```python
"""Trigger structure: war3map.wtg as saved by the 1.31+ editor (marker 0x80000004, version 7).
Byte-exact on all 556 local maps. Parameter lists have no stored length, so parsing needs each GUI function's
parameter count from TriggerData."""
from collections.abc import Callable
from dataclasses import dataclass, field

from .binary import FormatError, Reader, Writer

MAGIC = b"WTG!"
FORMAT_MARKER = 0x80000004
PRESET, VARIABLE, FUNCTION, STRING, INVALID = 0, 1, 2, 3, -1
ROOT, LIBRARY, CATEGORY, TRIGGER, COMMENT, SCRIPT, VARIABLE_ELEMENT = 1, 2, 4, 8, 16, 32, 64
ID_PREFIX = {CATEGORY: 2, TRIGGER: 3, COMMENT: 4, VARIABLE_ELEMENT: 6}   # high byte of element ids

ArgCount = Callable[[int, str], "int | None"]


@dataclass
class Call:
    kind: int                                   # 0 event, 1 condition, 2 action, 3 call
    name: str
    params: list["Param"] | None = field(default_factory=list)   # None: the file stores no parameter list
    unknown: int = 0


@dataclass
class Param:
    type: int                                   # PRESET, VARIABLE, FUNCTION, STRING or INVALID
    value: str
    call: Call | None = None
    index: "Param | None" = None                # array index of a variable


@dataclass
class ECA:
    kind: int                                   # 0 event, 1 condition, 2 action
    name: str
    enabled: int = 1
    params: list[Param] = field(default_factory=list)
    children: list["ECA"] = field(default_factory=list)
    group: int = 0                              # block inside the parent (children only)


@dataclass
class Variable:
    name: str
    type: str
    unknown: int = 1
    is_array: int = 0
    array_size: int = 1
    initialized: int = 0
    initial: str = ""
    id: int = 0
    parent: int = 0


@dataclass
class Category:
    kind: int                                   # ROOT, LIBRARY or CATEGORY
    id: int
    name: str
    is_comment: int = 0
    expanded: int = 0
    parent: int = -1


@dataclass
class Trigger:
    kind: int                                   # TRIGGER, COMMENT or SCRIPT
    name: str
    description: str = ""
    is_comment: int = 0
    id: int = 0
    enabled: int = 1
    custom_text: int = 0
    initially_off: int = 0
    run_on_init: int = 0
    parent: int = 0
    ecas: list[ECA] = field(default_factory=list)


@dataclass
class VariableElement:
    id: int
    name: str
    parent: int = 0


@dataclass
class TriggerFile:
    version: int = 7
    counters: list[tuple[int, list[int]]] = field(default_factory=lambda: [(0, []) for _ in range(8)])
    definition_version: int = 2
    variables: list[Variable] = field(default_factory=list)
    elements: list = field(default_factory=list)   # Category | Trigger | VariableElement, parents first
    trailing: bytes = b""


def _count(count: ArgCount, kind: int, name: str) -> int:
    n = count(kind, name)
    if n is None:
        raise FormatError(f"unknown GUI function {name!r} (kind {kind}); the map may use a custom TriggerData")
    return n


def _param(r: Reader, count: ArgCount) -> Param:
    p = Param(r.i32(), r.cstr())
    if r.u32():
        call = Call(r.i32(), r.cstr())
        call.params = [_param(r, count) for _ in range(_count(count, call.kind, call.name))] if r.u32() else None
        call.unknown = r.u32()
        p.call = call
    if r.u32():
        p.index = _param(r, count)
    return p


def _eca(r: Reader, count: ArgCount, child: bool) -> ECA:
    e = ECA(r.i32(), "")
    if child:
        e.group = r.i32()
    e.name = r.cstr()
    e.enabled = r.u32()
    e.params = [_param(r, count) for _ in range(_count(count, e.kind, e.name))]
    e.children = [_eca(r, count, True) for _ in range(r.count(item_size=17))]
    return e


def parse(data: bytes, count: ArgCount) -> TriggerFile:
    r = Reader(data)
    if r.raw(4) != MAGIC:
        raise FormatError("not a trigger file (no WTG! header)")
    marker = r.u32()
    if marker != FORMAT_MARKER:
        raise FormatError(f"trigger format {marker:#x} is not supported (maps saved by editor 1.31+ only)")
    tf = TriggerFile(r.i32())
    if tf.version != 7:
        raise FormatError(f"trigger version {tf.version} is not supported")
    tf.counters = []
    for _ in range(8):
        n = r.i32()
        tf.counters.append((n, [r.i32() for _ in range(r.count(item_size=4))]))
    tf.definition_version = r.i32()
    for _ in range(r.count(item_size=27)):
        tf.variables.append(Variable(r.cstr(), r.cstr(), r.u32(), r.u32(), r.u32(), r.u32(), r.cstr(), r.i32(),
                                     r.i32()))
    for _ in range(r.count(item_size=13)):
        kind = r.u32()
        if kind in (ROOT, LIBRARY, CATEGORY):
            tf.elements.append(Category(kind, r.i32(), r.cstr(), r.u32(), r.u32(), r.i32()))
        elif kind in (TRIGGER, COMMENT, SCRIPT):
            t = Trigger(kind, r.cstr(), r.cstr(), r.u32(), r.i32(), r.u32(), r.u32(), r.u32(), r.u32(), r.i32())
            t.ecas = [_eca(r, count, False) for _ in range(r.count(item_size=13))]
            tf.elements.append(t)
        elif kind == VARIABLE_ELEMENT:
            tf.elements.append(VariableElement(r.i32(), r.cstr(), r.i32()))
        else:
            raise FormatError(f"unknown trigger element type {kind} at offset {r.pos - 4}")
    tf.trailing = r.rest()
    return tf


def _write_param(w: Writer, p: Param) -> None:
    w.i32(p.type)
    w.cstr(p.value)
    w.u32(p.call is not None)
    if p.call is not None:
        w.i32(p.call.kind)
        w.cstr(p.call.name)
        w.u32(p.call.params is not None)
        for sub in p.call.params or []:
            _write_param(w, sub)
        w.u32(p.call.unknown)
    w.u32(p.index is not None)
    if p.index is not None:
        _write_param(w, p.index)


def _write_eca(w: Writer, e: ECA, child: bool) -> None:
    w.i32(e.kind)
    if child:
        w.i32(e.group)
    w.cstr(e.name)
    w.u32(e.enabled)
    for p in e.params:
        _write_param(w, p)
    w.i32(len(e.children))
    for c in e.children:
        _write_eca(w, c, True)


def serialize(tf: TriggerFile) -> bytes:
    w = Writer()
    w.raw(MAGIC)
    w.u32(FORMAT_MARKER)
    w.i32(tf.version)
    for n, deleted in tf.counters:
        w.i32(n)
        w.i32(len(deleted))
        for d in deleted:
            w.i32(d)
    w.i32(tf.definition_version)
    w.i32(len(tf.variables))
    for v in tf.variables:
        w.cstr(v.name)
        w.cstr(v.type)
        for x in (v.unknown, v.is_array, v.array_size, v.initialized):
            w.u32(x)
        w.cstr(v.initial)
        w.i32(v.id)
        w.i32(v.parent)
    w.i32(len(tf.elements))
    for e in tf.elements:
        if isinstance(e, Category):
            w.u32(e.kind)
            w.i32(e.id)
            w.cstr(e.name)
            w.u32(e.is_comment)
            w.u32(e.expanded)
            w.i32(e.parent)
        elif isinstance(e, Trigger):
            w.u32(e.kind)
            w.cstr(e.name)
            w.cstr(e.description)
            w.u32(e.is_comment)
            w.i32(e.id)
            for x in (e.enabled, e.custom_text, e.initially_off, e.run_on_init):
                w.u32(x)
            w.i32(e.parent)
            w.i32(len(e.ecas))
            for x in e.ecas:
                _write_eca(w, x, False)
        else:
            w.u32(VARIABLE_ELEMENT)
            w.i32(e.id)
            w.cstr(e.name)
            w.i32(e.parent)
    w.raw(tf.trailing)
    return w.getvalue()
```

`src/wc3mcp/formats/wct.py`:
```python
"""Custom script text: war3map.wct as saved by the 1.31+ editor (marker 0x80000004, version 1)."""
from dataclasses import dataclass, field

from .binary import FormatError, Reader, Writer

FORMAT_MARKER = 0x80000004


@dataclass
class CustomText:
    version: int = 1
    comment: str = ""
    header: str | None = None                               # the map's custom script code; None when empty
    texts: list[str | None] = field(default_factory=list)   # one per TRIGGER element of war3map.wtg, in order


def _sized(r: Reader) -> str | None:
    size = r.u32()
    if size == 0:
        return None
    data = r.raw(size)
    if data[-1:] != b"\0":
        raise FormatError(f"custom text ending at offset {r.pos} is not NUL-terminated")
    return data[:-1].decode("utf-8", "surrogateescape")


def parse(data: bytes) -> CustomText:
    r = Reader(data)
    marker = r.u32()
    if marker != FORMAT_MARKER:
        raise FormatError(f"custom text format {marker:#x} is not supported (maps saved by editor 1.31+ only)")
    ct = CustomText(r.i32(), r.cstr())
    if ct.version != 1:
        raise FormatError(f"custom text version {ct.version} is not supported")
    ct.header = _sized(r)
    while r.pos < len(r.data):
        ct.texts.append(_sized(r))
    return ct


def _write_sized(w: Writer, text: str | None) -> None:
    if text is None:
        w.u32(0)
        return
    data = text.encode("utf-8", "surrogateescape") + b"\0"
    w.u32(len(data))
    w.raw(data)


def serialize(ct: CustomText) -> bytes:
    w = Writer()
    w.u32(FORMAT_MARKER)
    w.i32(ct.version)
    w.cstr(ct.comment)
    _write_sized(w, ct.header)
    for text in ct.texts:
        _write_sized(w, text)
    return w.getvalue()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `& $PY -m pytest tests/formats -q`
Expected: all passed (codec corpus tests now include Human05)

- [ ] **Step 5: Commit**

```bash
git add src/wc3mcp/formats/wtg.py src/wc3mcp/formats/wct.py tests/formats/test_wtg.py tests/corpus.py
git commit -m "feat(formats): byte-exact wtg and wct codecs (1.31+ trigger format)" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: GUI code as JSON, editor text and checks

**Files:**
- Create: `src/wc3mcp/ops/gui.py`
- Test: `tests/ops/test_gui.py`

**Interfaces:**
- Consumes: Task 1 `TriggerData` (`function`, `presets`, `types`, `categories`, `base`, `compatible`), `EVENT/CONDITION/ACTION/CALL`, `KIND_NAMES`; Task 2 `ECA`, `Param`, `Call`, `Variable`, param type constants; `formats.wts.TRIGSTR`, `TriggerStrings.resolve`; `Catalog.name`.
- Produces: `GENERATED` (prefix → type), `RAWCODE_TYPES`, `blocks(name) -> tuple[(key, kind, label), ...]`, `script_name(trigger_name) -> str`, `var_type(name, variables) -> str | None`, `literal_text(value) -> str | None`, `param_json(p)`, `eca_json(e) -> dict`, `param_from_json(value, expected, td, variables, path) -> Param`, `ecas_from_json(items, kind, td, variables, path) -> list[ECA]`, `Checker(td, variables, trigger_names)` with `.ecas(ecas, path)`, `.literal(value, expected, path)`, `.errors`, `.warnings`; `Renderer(td, catalog, variables, strings)` with `.lines(ecas) -> list[str]`. `variables` is `dict[str, Variable]`; `trigger_names` holds `script_name` values. JSON errors: `bad_value` (details `path`), `unknown_function` (details `path`).

JSON shapes: ECA `{"fn": name, "args": [...], "enabled": false, "if"/"then"/"else"/"conditions"/"actions": [ECA, ...]}` (`args` omitted when empty, `enabled` only when false, leftover children as `"children": [{..., "group": n}]` on read only). Argument: string literal, number or boolean (stored as text), `{"preset": name}`, `{"var": name, "index": arg}`, `{"call": name, "args": [...]}`, `null` for unset.

- [ ] **Step 1: Write the failing test**

`tests/ops/test_gui.py`:
```python
import json

import pytest

from corpus import HAVE_INSTALL, _storage, open_sample, sample_map_ids
from wc3mcp.errors import ToolError
from wc3mcp.formats import wtg
from wc3mcp.formats.wtg import Trigger, Variable
from wc3mcp.formats.wts import TriggerStrings
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.gamedata.triggerdata import ACTION, CALL, CONDITION, EVENT
from wc3mcp.ops.gui import Checker, Renderer, eca_json, ecas_from_json

pytestmark = pytest.mark.skipif(not HAVE_INSTALL, reason="needs TriggerData from the install")

SECTIONS = (("events", EVENT), ("conditions", CONDITION), ("actions", ACTION))
SPAWN = {
    "events": [{"fn": "TriggerRegisterTimerEventPeriodic", "args": ["1"]}],
    "conditions": [{"fn": "OperatorCompareInteger", "args": [{"var": "Count"}, {"preset": "OperatorGreater"}, "3"]}],
    "actions": [
        {"fn": "SetVariable", "args": [{"var": "Count"},
                                       {"call": "OperatorInt", "args": [{"var": "Count"}, {"preset": "OperatorAdd"}, "1"]}]},
        {"fn": "IfThenElseMultiple",
         "if": [{"fn": "OperatorCompareInteger", "args": [{"var": "Count"}, {"preset": "OperatorGreater"}, "10"]}],
         "then": [{"fn": "DisplayTextToForce", "args": [{"call": "GetPlayersAll"}, "Ten!"]}],
         "else": [{"fn": "TriggerSleepAction", "args": ["0.5"], "enabled": False}]},
    ],
}
VARIABLES = {"Count": Variable("Count", "integer"), "Heroes": Variable("Heroes", "unit", is_array=1, array_size=8)}


@pytest.fixture(scope="module")
def catalog():
    return Catalog(_storage(), balance=None)


def build(catalog, doc, variables=VARIABLES):
    return [e for key, kind in SECTIONS for e in ecas_from_json(doc.get(key), kind, catalog.trigger_data, variables, key)]


def as_json(ecas):
    return {key: [eca_json(e) for e in ecas if e.kind == kind] for key, kind in SECTIONS}


def test_json_converts_both_ways(catalog):
    ecas = build(catalog, SPAWN)
    assert [e.kind for e in ecas] == [EVENT, CONDITION, ACTION, ACTION]
    assert [(c.group, c.kind, c.enabled) for c in ecas[3].children] == [(0, CONDITION, 1), (1, ACTION, 1), (2, ACTION, 0)]
    add = ecas[2].params[1]
    assert (add.type, add.value, add.call.kind) == (wtg.FUNCTION, "OperatorInt", CALL)
    assert as_json(ecas) == SPAWN


def test_checker_accepts_valid_code_and_reports_mistakes(catalog):
    td = catalog.trigger_data
    ok = Checker(td, VARIABLES, set())
    ok.ecas(build(catalog, SPAWN), "trigger")
    assert ok.errors == [] and ok.warnings == []
    bad = Checker(td, VARIABLES, set())
    bad.ecas(build(catalog, {"actions": [
        {"fn": "KillUnit", "args": [{"var": "Count"}]},
        {"fn": "KillUnit", "args": [{"var": "Nope"}]},
        {"fn": "KillUnit", "args": [{"var": "Heroes"}]},
        {"fn": "TriggerSleepAction", "args": ["soon"]},
        {"fn": "KillUnit", "args": [None]},
        {"fn": "KillUnit", "args": [None], "enabled": False},
        {"fn": "TriggerExecute", "args": [{"var": "gg_trg_Missing"}]}]}), "trigger")
    assert len(bad.errors) == 5
    assert bad.errors[0] == "trigger[0].KillUnit.args[0]: expects unit, got integer"
    assert "unknown variable 'Nope'" in bad.errors[1] and "array" in bad.errors[2]
    assert "not a valid real" in bad.errors[3] and "not set" in bad.errors[4]
    assert bad.warnings == ["trigger[6].TriggerExecute.args[0]: no trigger matches 'gg_trg_Missing'"]


@pytest.mark.parametrize("item, code", [
    ({"fn": "MapInitializationEvent"}, "unknown_function"),
    ({"fn": "KillUnit"}, "bad_value"),
    ({"fn": "KillUnit", "args": [{"unit": 1}]}, "bad_value"),
    ({"fn": "KillUnit", "args": [{"call": "GetTriggerUnit"}], "colour": 1}, "bad_value"),
    ({"fn": "KillUnit", "args": [{"call": "NoSuchCall"}]}, "unknown_function"),
    ("KillUnit", "bad_value"),
])
def test_json_shape_errors(catalog, item, code):
    with pytest.raises(ToolError) as e:
        ecas_from_json([item], ACTION, catalog.trigger_data, VARIABLES, "actions")
    assert e.value.code == code and e.value.details["path"].startswith("actions[0]")


def test_render_editor_text(catalog):
    lines = Renderer(catalog.trigger_data, catalog, VARIABLES, TriggerStrings()).lines(build(catalog, SPAWN))
    assert lines == [
        "Events",
        "    Time - Every 1 seconds of game time",
        "Conditions",
        "    Count Greater than 3",
        "Actions",
        "    Set Count = (Count + 1)",
        "    If (All Conditions are True) then do (Then Actions) else do (Else Actions)",
        "        If - Conditions",
        "            Count Greater than 10",
        "        Then - Actions",
        "            Game - Display to (All players) the text: Ten!",
        "        Else - Actions",
        "            (disabled) Wait 0.5 seconds",
    ]


@pytest.mark.parametrize("map_id", sample_map_ids())
def test_corpus_code_checks_clean_and_json_is_stable(map_id, catalog):
    td = catalog.trigger_data
    data = open_sample(map_id).read("war3map.wtg")
    if data is None:
        pytest.skip("map has no trigger data")
    tf = wtg.parse(data, td.arg_count)
    variables = {v.name: v for v in tf.variables}
    checker = Checker(td, variables, set())
    for t in tf.elements:
        if not isinstance(t, Trigger) or t.kind != wtg.TRIGGER or t.custom_text:
            continue
        if t.enabled:
            checker.ecas(t.ecas, t.name)
        doc = as_json(t.ecas)
        if '"children"' in json.dumps(doc):
            continue
        again = {key: [eca_json(e) for e in ecas_from_json(doc[key], kind, td, variables, key)] for key, kind in SECTIONS}
        assert again == doc, t.name
    assert checker.errors == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& $PY -m pytest tests/ops/test_gui.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'wc3mcp.ops.gui'`

- [ ] **Step 3: Write minimal implementation**

`src/wc3mcp/ops/gui.py`:
```python
"""GUI triggers: ECA trees as JSON, editor-style text, and checks against TriggerData."""
import re

from ..errors import ToolError
from ..formats.wtg import ECA, FUNCTION, INVALID, PRESET, STRING, VARIABLE, Call, Param
from ..formats.wts import TRIGSTR
from ..gamedata.triggerdata import ACTION, CALL, CONDITION, EVENT, KIND_NAMES

GENERATED = {"gg_trg_": "trigger", "gg_rct_": "rect", "gg_snd_": "sound", "gg_cam_": "camerasetup",
             "gg_unit_": "unit", "gg_item_": "item", "gg_dest_": "destructable"}
CODE_KINDS = {"code": ACTION, "boolexpr": CONDITION, "boolcall": CONDITION, "eventcall": EVENT}
CODE_RETURNS = {EVENT: "eventcall", CONDITION: "boolexpr", ACTION: "code"}
RAWCODE_TYPES = {"unitcode": "unit", "itemcode": "item", "abilcode": "ability", "buffcode": "buff",
                 "techcode": "upgrade", "destructablecode": "destructible", "doodadcode": "doodad",
                 "heroskillcode": "ability"}
_BLOCKS = {"IfThenElseMultiple": (("if", CONDITION, "If - Conditions"), ("then", ACTION, "Then - Actions"),
                                  ("else", ACTION, "Else - Actions")),
           "AndMultiple": (("conditions", CONDITION, "Conditions"),),
           "OrMultiple": (("conditions", CONDITION, "Conditions"),)}
_LOOP = (("actions", ACTION, "Loop - Actions"),)
_ARG_HINT = 'an argument is a literal, {"preset": name}, {"var": name, "index": arg} or {"call": name, "args": [...]}'


def blocks(name: str) -> tuple[tuple[str, int, str], ...]:
    """Child blocks of a block function by group index: (JSON key, kind of its functions, editor label)."""
    return _BLOCKS.get(name) or (_LOOP if name.endswith("Multiple") else ())


def script_name(name: str) -> str:
    """The identifier the editor derives from a trigger name (gg_trg_<this>)."""
    return re.sub(r"[^A-Za-z0-9_]", "_", name)


def var_type(name: str, variables: dict) -> str | None:
    v = variables.get(name)
    if v is not None:
        return v.type
    return next((t for prefix, t in GENERATED.items() if name.startswith(prefix)), None)


def _argument_types(fn, first_var: str | None, variables: dict) -> list[str]:
    args = list(fn.args)
    if fn.name == "SetVariable" and len(args) == 2:
        args[1] = (var_type(first_var, variables) if first_var else None) or "?"
    return args


def literal_text(value) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format(value, "f").rstrip("0").rstrip(".") or "0"
    return value if isinstance(value, str) else None


# ---- JSON ------------------------------------------------------------------------------------------------------
def param_json(p: Param):
    if p.type == STRING:
        return p.value
    if p.type == PRESET:
        return {"preset": p.value}
    if p.type == VARIABLE:
        return {"var": p.value, "index": param_json(p.index)} if p.index is not None else {"var": p.value}
    if p.type == FUNCTION and p.call is not None:
        out = {"call": p.call.name}
        if p.call.params:
            out["args"] = [param_json(x) for x in p.call.params]
        return out
    return None


def eca_json(e: ECA) -> dict:
    out = {"fn": e.name}
    if e.params:
        out["args"] = [param_json(p) for p in e.params]
    if not e.enabled:
        out["enabled"] = False
    specs = blocks(e.name)
    for c in e.children:
        item = eca_json(c)
        if 0 <= c.group < len(specs):
            out.setdefault(specs[c.group][0], []).append(item)
        else:  # leftovers the editor keeps after a block function was replaced
            out.setdefault("children", []).append({**item, "group": c.group})
    return out


def _bad(path: str, message: str, **details) -> ToolError:
    return ToolError("bad_value", f"{path}: {message}", path=path, **details)


def _function(td, kind: int, name, path: str):
    fn = td.function(kind, name) if isinstance(name, str) else None
    if fn is None:
        other = [KIND_NAMES[k] for k in range(4) if k != kind and isinstance(name, str) and td.function(k, name)]
        raise ToolError("unknown_function", f"{path}: no {KIND_NAMES[kind]} named {name!r}"
                        + (f" ({name} is a {' / '.join(other)})" if other else ""),
                        hint="data_search kind=trigger_function finds functions", path=path)
    return fn


def _params(fn, args, td, variables: dict, path: str) -> list[Param]:
    args = [] if args is None else args
    if not isinstance(args, list):
        raise _bad(path, "args must be a list")
    first = args[0].get("var") if args and isinstance(args[0], dict) else None
    types = _argument_types(fn, first if isinstance(first, str) else None, variables)
    if len(args) != len(types):
        raise _bad(path, f"{fn.name} takes {len(types)} arguments ({', '.join(types) or 'none'}), got {len(args)}")
    return [param_from_json(a, t, td, variables, f"{path}.args[{i}]") for i, (a, t) in enumerate(zip(args, types))]


def param_from_json(value, expected: str, td, variables: dict, path: str) -> Param:
    if value is None:
        return Param(INVALID, "")
    text = literal_text(value)
    if text is not None:
        return Param(STRING, text)
    if isinstance(value, dict):
        keys = set(value)
        if keys == {"preset"} and isinstance(value["preset"], str):
            return Param(PRESET, value["preset"])
        if "var" in keys and keys <= {"var", "index"} and isinstance(value["var"], str):
            index = param_from_json(value["index"], "integer", td, variables, path + ".index") if "index" in keys else None
            return Param(VARIABLE, value["var"], index=index)
        if "call" in keys and keys <= {"call", "args"}:
            kind = CODE_KINDS.get(expected, CALL)
            fn = _function(td, kind, value["call"], path)
            params = _params(fn, value.get("args"), td, variables, path)
            return Param(FUNCTION, fn.name if kind in (CALL, ACTION) else "", Call(kind, fn.name, params))
    raise _bad(path, "unrecognized argument", hint=_ARG_HINT)


def ecas_from_json(items, kind: int, td, variables: dict, path: str) -> list[ECA]:
    if items is None:
        return []
    if not isinstance(items, list):
        raise _bad(path, "must be a list of functions")
    out = []
    for i, item in enumerate(items):
        where = f"{path}[{i}]"
        if not isinstance(item, dict) or "fn" not in item:
            raise _bad(where, 'expected {"fn": name, "args": [...]}')
        fn = _function(td, kind, item["fn"], where)
        specs = blocks(fn.name)
        extra = set(item) - {"fn", "args", "enabled"} - {key for key, _, _ in specs}
        if extra:
            raise _bad(where, f"unknown keys {sorted(extra)}")
        e = ECA(kind, fn.name, 0 if item.get("enabled") is False else 1, _params(fn, item.get("args"), td, variables, where))
        for group, (key, child_kind, _) in enumerate(specs):
            for child in ecas_from_json(item.get(key), child_kind, td, variables, f"{where}.{key}"):
                child.group = group
                e.children.append(child)
        out.append(e)
    return out


# ---- checks ----------------------------------------------------------------------------------------------------
class Checker:
    """Finds what would break script generation in enabled GUI code; silent on all enabled code in 556 local maps."""

    def __init__(self, td, variables: dict, trigger_names: set[str]):
        self.td, self.variables, self.trigger_names = td, variables, trigger_names
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def ecas(self, ecas: list[ECA], path: str) -> None:
        for i, e in enumerate(ecas):
            self._eca(e, e.kind, f"{path}[{i}]")

    def _eca(self, e: ECA, kind: int, path: str) -> None:
        if not e.enabled:
            return
        if e.kind != kind:
            self.errors.append(f"{path}: {e.name} is a {KIND_NAMES[e.kind]}, but this block takes {KIND_NAMES[kind]}s")
        fn = self.td.function(e.kind, e.name)
        if fn is None:
            self.errors.append(f"{path}: unknown {KIND_NAMES[e.kind]} {e.name!r}")
            return
        self._params(fn, e.params, f"{path}.{e.name}")
        specs = blocks(e.name)
        for i, c in enumerate(e.children):
            if 0 <= c.group < len(specs):
                self._eca(c, specs[c.group][1], f"{path}.{specs[c.group][0]}[{i}]")
            else:
                self._eca(c, c.kind, f"{path}.children[{i}]")

    def _params(self, fn, params: list[Param], path: str) -> None:
        first = params[0].value if params and params[0].type == VARIABLE else None
        if fn.name == "SetVariable" and first is None:
            self.errors.append(f"{path}: the first argument must be a variable")
            return
        types = _argument_types(fn, first, self.variables)
        if len(params) != len(types):
            self.errors.append(f"{path}: takes {len(types)} arguments, got {len(params)}")
            return
        for i, (p, t) in enumerate(zip(params, types)):
            self._param(p, t, f"{path}.args[{i}]")

    def _param(self, p: Param, expected: str, path: str) -> None:
        if p.type == STRING:
            self.literal(p.value, expected, path)
            return
        if p.type == PRESET:
            preset = self.td.presets.get(p.value)
            if preset is None:
                self.errors.append(f"{path}: unknown preset {p.value!r}")
                return
            actual = preset.type
        elif p.type == VARIABLE:
            actual = var_type(p.value, self.variables)
            if actual is None:
                self.errors.append(f"{path}: unknown variable {p.value!r}")
                return
            if p.value.startswith("gg_trg_") and p.value[len("gg_trg_"):] not in self.trigger_names:
                self.warnings.append(f"{path}: no trigger matches {p.value!r}")
            v = self.variables.get(p.value)
            if v is not None and bool(v.is_array) != (p.index is not None):
                self.errors.append(f"{path}: {p.value} is {'an array and needs' if v.is_array else 'not an array and takes no'} index")
            if p.index is not None:
                self._param(p.index, "integer", path + ".index")
        elif p.type == FUNCTION and p.call is not None:
            fn = self.td.function(p.call.kind, p.call.name)
            if fn is None:
                self.errors.append(f"{path}: unknown {KIND_NAMES[p.call.kind]} {p.call.name!r}")
                return
            self._params(fn, p.call.params or [], f"{path}.{fn.name}")
            actual = fn.returns if p.call.kind == CALL else CODE_RETURNS[p.call.kind]
        else:
            self.errors.append(f"{path}: argument is not set")
            return
        if not self.td.compatible(expected, actual or "nothing"):
            self.errors.append(f"{path}: expects {expected}, got {actual}")

    def literal(self, value: str, expected: str, path: str) -> None:
        if expected in RAWCODE_TYPES:
            ok = len(value.encode("utf-8")) == 4
        elif expected == "integer":
            ok = re.fullmatch(r"-?\d+", value) is not None
        elif expected == "real":
            try:
                float(value)
                ok = True
            except ValueError:
                ok = False
        elif expected == "boolean":
            ok = value in ("true", "false")
        else:
            return
        if not ok:
            self.errors.append(f"{path}: {value!r} is not a valid {expected}")


# ---- editor text -----------------------------------------------------------------------------------------------
class Renderer:
    """Editor-style text for GUI functions."""

    def __init__(self, td, catalog, variables: dict, strings):
        self.td, self.catalog, self.variables, self.strings = td, catalog, variables, strings

    def lines(self, ecas: list[ECA]) -> list[str]:
        out = []
        for title, kind in (("Events", EVENT), ("Conditions", CONDITION), ("Actions", ACTION)):
            out.append(title)
            for e in ecas:
                if e.kind == kind:
                    self._eca(e, 1, out)
        return out

    def _eca(self, e: ECA, depth: int, out: list[str]) -> None:
        fn = self.td.function(e.kind, e.name)
        text = self.call(fn, e.name, e.params)
        category = self.td.categories.get(fn.category) if fn else None
        if category and category[1] and category[0]:
            text = f"{category[0]} - {text}"
        out.append("    " * depth + ("" if e.enabled else "(disabled) ") + text)
        for group, (_, _, label) in enumerate(blocks(e.name)):
            out.append("    " * (depth + 1) + label)
            for c in e.children:
                if c.group == group:
                    self._eca(c, depth + 2, out)

    def call(self, fn, name: str, params: list[Param]) -> str:
        if fn is None:
            return f"{name}({', '.join(self.param(p, '') for p in params)})"
        first = params[0].value if params and params[0].type == VARIABLE else None
        types = _argument_types(fn, first, self.variables)
        pieces = list(fn.layout)
        if len(pieces) > 1 and pieces[0] == fn.display:
            pieces = pieces[1:]
        slots = [i for i, piece in enumerate(pieces) if piece.startswith("~")]
        if not pieces or len(slots) != len(params):
            if not params:
                return fn.display
            return f"{fn.display}({', '.join(self.param(p, t) for p, t in zip(params, types))})"
        for slot, p, t in zip(slots, params, types):
            pieces[slot] = self.param(p, t)
        return "".join(pieces)

    def param(self, p: Param, expected: str) -> str:
        if p.type == STRING:
            if TRIGSTR.match(p.value):
                return self.strings.resolve(p.value)
            kind = RAWCODE_TYPES.get(expected)
            name = self.catalog.name(kind, p.value) if kind and len(p.value) == 4 else ""
            return name or p.value
        if p.type == PRESET:
            preset = self.td.presets.get(p.value)
            return preset.display if preset and preset.display else p.value
        if p.type == VARIABLE:
            prefix = next((x for x in GENERATED if p.value.startswith(x)), None)
            text = p.value[len(prefix):].replace("_", " ") + " <gen>" if prefix else p.value
            return f"{text}[{self.param(p.index, 'integer')}]" if p.index is not None else text
        if p.type == FUNCTION and p.call is not None:
            return f"({self.call(self.td.function(p.call.kind, p.call.name), p.call.name, p.call.params or [])})"
        return "(unset)"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `& $PY -m pytest tests/ops/test_gui.py -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/wc3mcp/ops/gui.py tests/ops/test_gui.py
git commit -m "feat(ops): GUI trigger JSON, editor text and TriggerData checks" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Reading triggers (`triggers_tree`, `trigger_get`)

**Files:**
- Create: `src/wc3mcp/ops/triggers.py`
- Test: `tests/ops/test_triggers.py`

**Interfaces:**
- Consumes: Task 1 `Catalog.trigger_data`; Task 2 codecs; Task 3 `eca_json`, `Renderer`; `ops.strings.load_strings`; `MapProject.read/delete`.
- Produces: `triggers_tree(project, catalog) -> {"map", "comment", "has_custom_script", "categories": [{"id", "name", "parent", "comment"}], "triggers": [{"id", "name", "category", "type", "enabled", "initially_on", "run_on_init", "functions"}], "variables": [{"name", "type", "category", "array_size"?, "initial"?}]}`; `trigger_get(project, catalog, name=None) -> dict` (GUI: `events`/`conditions`/`actions` JSON + `text`; text trigger: `script`; `name=None`: `{"type": "map", "name", "comment", "script"}`). Trigger `type` is `gui`, `text` or `comment`. Helpers reused by Task 5: `SECTIONS`, `_read`, `_load(project, td) -> (TriggerFile, CustomText)`, `_triggers(tf)`, `_root(tf)`, `_category_names(tf)`. Errors: `no_triggers`, `bad_file`, `not_found`.

- [ ] **Step 1: Write the failing test**

`tests/ops/test_triggers.py`:
```python
import pytest

from corpus import HAVE_INSTALL, _storage, ladder_maps, open_sample
from wc3mcp.errors import ToolError
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.ops.triggers import trigger_get, triggers_tree
from wc3mcp.project.workspace import MapProject

WARCHASERS = "casc:Maps/Scenario/(4)WarChasers.w3m"
pytestmark = pytest.mark.skipif(not HAVE_INSTALL or not ladder_maps(),
                                reason="needs the Warcraft III install and ladder maps")


@pytest.fixture(scope="module")
def catalog():
    return Catalog(_storage(), balance=None)


@pytest.fixture
def melee(tmp_path):
    src = tmp_path / ladder_maps()[0].name
    src.write_bytes(ladder_maps()[0].read_bytes())
    return MapProject.open(src)


@pytest.fixture
def warchasers(tmp_path):
    src = tmp_path / "WarChasers.w3m"
    src.write_bytes(open_sample(WARCHASERS).data)
    return MapProject.open(src)


def test_tree_of_a_melee_map(melee, catalog):
    tree = triggers_tree(melee, catalog)
    assert tree["map"] == ladder_maps()[0].name and tree["variables"] == [] and not tree["has_custom_script"]
    assert [(c["name"], c["parent"]) for c in tree["categories"]] == [("Initialization", None)]
    [melee_init] = tree["triggers"]
    assert {k: v for k, v in melee_init.items() if k != "id"} == {
        "name": "Melee Initialization", "category": "Initialization", "type": "gui", "enabled": True,
        "initially_on": True, "run_on_init": False, "functions": 9}


def test_tree_lists_variables(warchasers, catalog):
    tree = triggers_tree(warchasers, catalog)
    assert len(tree["variables"]) == 54 and len(tree["triggers"]) == 151
    assert (tree["variables"][0]["name"], tree["variables"][0]["type"]) == ("jugg3", "unit")


def test_get_gui_trigger(melee, catalog):
    doc = trigger_get(melee, catalog, "Melee Initialization")
    assert doc["events"] == [{"fn": "MapInitializationEvent"}] and doc["conditions"] == []
    assert doc["actions"][0] == {"fn": "MeleeStartingVisibility"} and len(doc["actions"]) == 8
    assert doc["description"] == "Default melee game initialization for all players"
    assert doc["text"].splitlines()[:5] == [
        "Events", "    Map initialization", "Conditions", "Actions",
        "    Melee Game - Use melee time of day (for all players)"]


def test_get_map_header_and_errors(melee, catalog):
    header = trigger_get(melee, catalog)
    assert header["type"] == "map" and header["script"] == "" and header["comment"].startswith("Enter map-specific")
    with pytest.raises(ToolError) as e:
        trigger_get(melee, catalog, "Nope")
    assert e.value.code == "not_found"
    melee.delete("war3map.wtg")
    with pytest.raises(ToolError) as e:
        triggers_tree(melee, catalog)
    assert e.value.code == "no_triggers"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& $PY -m pytest tests/ops/test_triggers.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'wc3mcp.ops.triggers'`

- [ ] **Step 3: Write minimal implementation**

`src/wc3mcp/ops/triggers.py`:
```python
"""The Trigger Editor: war3map.wtg and war3map.wct as a tree, per-trigger JSON and text, and atomic edits."""
from ..errors import ToolError
from ..formats import wct, wtg
from ..formats.binary import FormatError
from ..formats.wtg import COMMENT, ROOT, TRIGGER, Category, Trigger, VariableElement
from ..gamedata.triggerdata import ACTION, CONDITION, EVENT
from .gui import Renderer, eca_json
from .strings import load_strings

SECTIONS = (("events", EVENT), ("conditions", CONDITION), ("actions", ACTION))


def _read(project, name: str) -> bytes | None:
    try:
        return project.read(name)
    except ToolError as e:
        if e.code != "no_such_file":
            raise
        return None


def _triggers(tf) -> list[Trigger]:
    return [e for e in tf.elements if isinstance(e, Trigger) and e.kind == TRIGGER]


def _root(tf) -> Category:
    return next((e for e in tf.elements if isinstance(e, Category) and e.kind == ROOT), Category(ROOT, 0, ""))


def _category_names(tf) -> dict[int, str]:
    return {e.id: e.name for e in tf.elements if isinstance(e, Category) and e.kind != ROOT}


def _load(project, td) -> tuple[wtg.TriggerFile, wct.CustomText]:
    data = _read(project, "war3map.wtg")
    if data is None:
        raise ToolError("no_triggers", "this map has no war3map.wtg (protected or script-only map)",
                        hint="map_file_read war3map.j or war3map.lua shows its script")
    text = _read(project, "war3map.wct")
    try:
        tf = wtg.parse(data, td.arg_count)
        ct = wct.parse(text) if text is not None else wct.CustomText()
    except FormatError as e:
        raise ToolError("bad_file", f"trigger data: {e}") from e
    count = len(_triggers(tf))
    if text is None:
        ct.texts = [None] * count
    elif len(ct.texts) != count:
        raise ToolError("bad_file", f"war3map.wct has {len(ct.texts)} trigger texts for {count} triggers")
    return tf, ct


def _type(t: Trigger) -> str:
    if t.kind == COMMENT or t.is_comment:
        return "comment"
    return "text" if t.custom_text else "gui"


def _find_trigger(tf, name) -> Trigger:
    t = next((e for e in tf.elements if isinstance(e, Trigger) and e.name == name), None)
    if t is None:
        raise ToolError("not_found", f"no trigger named {name!r}", hint="triggers_tree lists triggers")
    return t


def triggers_tree(project, catalog) -> dict:
    tf, ct = _load(project, catalog.trigger_data)
    names = _category_names(tf)
    categories, triggers = [], []
    for e in tf.elements:
        if isinstance(e, Category) and e.kind != ROOT:
            categories.append({"id": e.id, "name": e.name, "parent": names.get(e.parent), "comment": bool(e.is_comment)})
        elif isinstance(e, Trigger):
            triggers.append({"id": e.id, "name": e.name, "category": names.get(e.parent), "type": _type(e),
                             "enabled": bool(e.enabled), "initially_on": not e.initially_off,
                             "run_on_init": bool(e.run_on_init), "functions": len(e.ecas)})
    variables = []
    for v in tf.variables:
        item = {"name": v.name, "type": v.type, "category": names.get(v.parent)}
        if v.is_array:
            item["array_size"] = v.array_size
        if v.initialized:
            item["initial"] = v.initial
        variables.append(item)
    return {"map": _root(tf).name, "comment": ct.comment, "has_custom_script": bool(ct.header),
            "categories": categories, "triggers": triggers, "variables": variables}


def trigger_get(project, catalog, name: str | None = None) -> dict:
    td = catalog.trigger_data
    tf, ct = _load(project, td)
    if name is None:
        return {"type": "map", "name": _root(tf).name, "comment": ct.comment, "script": ct.header or ""}
    t = _find_trigger(tf, name)
    doc = {"id": t.id, "name": t.name, "category": _category_names(tf).get(t.parent), "description": t.description,
           "type": _type(t), "enabled": bool(t.enabled), "initially_on": not t.initially_off,
           "run_on_init": bool(t.run_on_init)}
    if doc["type"] == "text":
        doc["script"] = ct.texts[next(i for i, x in enumerate(_triggers(tf)) if x is t)] or ""
    elif doc["type"] == "gui":
        for key, kind in SECTIONS:
            doc[key] = [eca_json(e) for e in t.ecas if e.kind == kind]
        variables = {v.name: v for v in tf.variables}
        doc["text"] = "\n".join(Renderer(td, catalog, variables, load_strings(project)).lines(t.ecas))
    return doc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `& $PY -m pytest tests/ops/test_triggers.py -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/wc3mcp/ops/triggers.py tests/ops/test_triggers.py
git commit -m "feat(ops): trigger tree and per-trigger JSON/text" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Editing triggers (`triggers_edit`)

**Files:**
- Modify: `src/wc3mcp/ops/triggers.py` (imports + edit section)
- Test: `tests/ops/test_triggers.py` (append)

**Interfaces:**
- Consumes: Task 4 helpers; Task 3 `Checker`, `ecas_from_json`, `literal_text`, `script_name`; Task 2 `ID_PREFIX`, element classes, `Variable`; `MapProject.write/status`.
- Produces: `triggers_edit(project, catalog, ops) -> {"changed", "created": [names], "warnings"}`; `SCRIPT_WARNING`. Ops:
  - `{"op": "category", "name", "new_name"?, "parent"?: name | null, "comment"?: bool}` (upsert)
  - `{"op": "variable", "name", "type" (required when new), "array_size"?: int | null, "initial"?, "category"?, "new_name"?}` (upsert; rename updates GUI references)
  - `{"op": "trigger", "name", "category"?, "description"?, "enabled"?, "initially_on"?, "run_on_init"?, "events"?, "conditions"?, "actions"?, "script"?, "new_name"?}` (upsert; new items default to the first category; rename updates `gg_trg_` references)
  - `{"op": "delete", "what": "trigger" | "category" | "variable", "name"}`
  - `{"op": "header", "script"?, "comment"?}`
- Error codes: `bad_op`, `bad_value`, `not_found`, `ambiguous`, `name_taken`, `in_use`, `not_empty`, `unknown_function`, `invalid_trigger` (details `errors`); all with `op_index`.

- [ ] **Step 1: Write the failing test**

Append to `tests/ops/test_triggers.py`:
```python
from wc3mcp.formats import wct, wtg
from wc3mcp.ops.triggers import SCRIPT_WARNING, triggers_edit

SPAWN_ACTIONS = [
    {"fn": "SetVariable", "args": [{"var": "Count"},
                                   {"call": "OperatorInt", "args": [{"var": "Count"}, {"preset": "OperatorAdd"}, "1"]}]},
    {"fn": "IfThenElseMultiple",
     "if": [{"fn": "OperatorCompareInteger", "args": [{"var": "Count"}, {"preset": "OperatorGreater"}, "10"]}],
     "then": [{"fn": "DisplayTextToForce", "args": [{"call": "GetPlayersAll"}, "Ten!"]}]},
]


def test_create_category_variable_and_gui_trigger(melee, catalog):
    result = triggers_edit(melee, catalog, [
        {"op": "category", "name": "Spawns"},
        {"op": "variable", "name": "Count", "type": "integer", "initial": 0, "category": "Spawns"},
        {"op": "trigger", "name": "Spawn Tick", "category": "Spawns",
         "events": [{"fn": "TriggerRegisterTimerEventPeriodic", "args": [1]}], "actions": SPAWN_ACTIONS}])
    assert result == {"changed": True, "created": ["Spawns", "Count", "Spawn Tick"], "warnings": [SCRIPT_WARNING]}
    tree = triggers_tree(melee, catalog)
    assert [c["name"] for c in tree["categories"]] == ["Initialization", "Spawns"]
    assert tree["variables"] == [{"name": "Count", "type": "integer", "category": "Spawns", "initial": "0"}]
    assert (tree["triggers"][1]["name"], tree["triggers"][1]["category"]) == ("Spawn Tick", "Spawns")
    doc = trigger_get(melee, catalog, "Spawn Tick")
    assert doc["events"] == [{"fn": "TriggerRegisterTimerEventPeriodic", "args": ["1"]}]
    assert doc["actions"] == SPAWN_ACTIONS
    assert "    Time - Every 1 seconds of game time" in doc["text"].splitlines()
    tf = wtg.parse(melee.read("war3map.wtg"), catalog.trigger_data.arg_count)
    ids = [e.id for e in tf.elements]
    assert len(ids) == len(set(ids)) and [e.id >> 24 for e in tf.elements if e.name == "Spawn Tick"] == [3]
    assert len(wct.parse(melee.read("war3map.wct")).texts) == 2


def test_text_trigger_header_and_renames(melee, catalog):
    triggers_edit(melee, catalog, [
        {"op": "variable", "name": "Score", "type": "integer", "array_size": 12},
        {"op": "trigger", "name": "Setup", "script": "function InitTrig_Setup takes nothing returns nothing\nendfunction"},
        {"op": "trigger", "name": "Use Score", "actions": [
            {"fn": "SetVariable", "args": [{"var": "Score", "index": 1}, 5]},
            {"fn": "ConditionalTriggerExecute", "args": [{"var": "gg_trg_Setup"}]}]},
        {"op": "header", "script": "// shared helpers"}])
    assert trigger_get(melee, catalog, "Setup")["script"].startswith("function InitTrig_Setup")
    assert trigger_get(melee, catalog)["script"] == "// shared helpers"
    triggers_edit(melee, catalog, [{"op": "variable", "name": "Score", "new_name": "Points"},
                                   {"op": "trigger", "name": "Setup", "new_name": "Game Setup"}])
    actions = trigger_get(melee, catalog, "Use Score")["actions"]
    assert actions[0]["args"][0] == {"var": "Points", "index": "1"}
    assert actions[1]["args"] == [{"var": "gg_trg_Game_Setup"}]
    tree = triggers_tree(melee, catalog)
    assert tree["variables"][0]["array_size"] == 12 and tree["has_custom_script"]


def test_delete_rules(melee, catalog):
    triggers_edit(melee, catalog, [
        {"op": "variable", "name": "Count", "type": "integer"},
        {"op": "trigger", "name": "Counter", "actions": [{"fn": "SetVariable", "args": [{"var": "Count"}, 1]}]}])
    for op, code in (({"op": "delete", "what": "variable", "name": "Count"}, "in_use"),
                     ({"op": "delete", "what": "category", "name": "Initialization"}, "not_empty")):
        with pytest.raises(ToolError) as e:
            triggers_edit(melee, catalog, [op])
        assert e.value.code == code
    triggers_edit(melee, catalog, [{"op": "delete", "what": "trigger", "name": "Counter"},
                                   {"op": "delete", "what": "variable", "name": "Count"}])
    tree = triggers_tree(melee, catalog)
    assert [t["name"] for t in tree["triggers"]] == ["Melee Initialization"] and tree["variables"] == []
    tf = wtg.parse(melee.read("war3map.wtg"), catalog.trigger_data.arg_count)
    assert tf.counters[3][1] and tf.counters[6][1]
    assert len(wct.parse(melee.read("war3map.wct")).texts) == 1


@pytest.mark.parametrize("op, code", [
    ({"op": "trigger", "name": "Bad", "actions": [{"fn": "KillUnit", "args": [{"call": "GetPlayersAll"}]}]},
     "invalid_trigger"),
    ({"op": "trigger", "name": "Bad", "events": [{"fn": "KillUnit", "args": [{"call": "GetTriggerUnit"}]}]},
     "unknown_function"),
    ({"op": "trigger", "name": "Bad", "actions": [{"fn": "KillUnit"}]}, "bad_value"),
    ({"op": "trigger", "name": "Melee_Initialization"}, "name_taken"),
    ({"op": "trigger", "name": "Bad", "category": "Nope"}, "not_found"),
    ({"op": "trigger", "name": "Bad", "script": "x", "actions": []}, "bad_op"),
    ({"op": "trigger", "name": "Bad", "colour": "red"}, "bad_op"),
    ({"op": "variable", "name": "1bad", "type": "integer"}, "bad_value"),
    ({"op": "variable", "name": "Ok", "type": "spaceship"}, "bad_value"),
    ({"op": "variable", "name": "Ok"}, "bad_op"),
    ({"op": "variable", "name": "Ok", "type": "integer", "initial": "many"}, "bad_value"),
    ({"op": "delete", "what": "unit", "name": "x"}, "bad_op"),
    ({"op": "explode"}, "bad_op"),
])
def test_edit_errors_are_atomic(melee, catalog, op, code):
    with pytest.raises(ToolError) as e:
        triggers_edit(melee, catalog, [{"op": "category", "name": "First"}, op])
    assert e.value.code == code and e.value.details["op_index"] == 1
    assert melee.status()["dirty"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& $PY -m pytest tests/ops/test_triggers.py -q`
Expected: FAIL with `ImportError: cannot import name 'SCRIPT_WARNING' from 'wc3mcp.ops.triggers'`

- [ ] **Step 3: Write minimal implementation**

In `src/wc3mcp/ops/triggers.py`, replace the import block with:
```python
import re

from ..errors import ToolError
from ..formats import wct, wtg
from ..formats.binary import FormatError
from ..formats.wtg import CATEGORY, COMMENT, ROOT, TRIGGER, VARIABLE, Category, Trigger, Variable, VariableElement
from ..gamedata.triggerdata import ACTION, CONDITION, EVENT
from .gui import Checker, Renderer, eca_json, ecas_from_json, literal_text, script_name
from .strings import load_strings
```

Append to `src/wc3mcp/ops/triggers.py`:
```python
# ---- edits -----------------------------------------------------------------------------------------------------
COUNTER = {CATEGORY: 2, TRIGGER: 3, COMMENT: 4, wtg.VARIABLE_ELEMENT: 6}   # index into TriggerFile.counters
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
ALLOWED = {
    "category": {"name", "new_name", "parent", "comment"},
    "variable": {"name", "new_name", "type", "array_size", "initial", "category"},
    "trigger": {"name", "new_name", "category", "description", "enabled", "initially_on", "run_on_init", "events",
                "conditions", "actions", "script"},
    "delete": {"what", "name"},
    "header": {"script", "comment"},
}
SCRIPT_WARNING = ("war3map.j / war3map.lua were not regenerated; save the map in the World Editor (or run script_build "
                  "once available) before testing it in the game")
_HINT = ('ops: {"op": "category", "name": "Spawns"}, {"op": "variable", "name": "Count", "type": "integer"}, '
         '{"op": "trigger", "name": "Spawn", "events": [...], "actions": [...]} or {..., "script": "..."}, '
         '{"op": "delete", "what": "trigger", "name": "Spawn"}, {"op": "header", "script": "..."}')


def _all_params(ecas):
    for e in ecas:
        stack = list(e.params)
        while stack:
            p = stack.pop()
            yield p
            if p.index is not None:
                stack.append(p.index)
            if p.call is not None:
                stack.extend(p.call.params or [])
        yield from _all_params(e.children)


class _Edit:
    def __init__(self, project, catalog):
        self.project, self.catalog, self.td = project, catalog, catalog.trigger_data
        self.tf, self.ct = _load(project, self.td)
        self.before = (wtg.serialize(self.tf), wct.serialize(self.ct))
        self.text = {t.id: s for t, s in zip(_triggers(self.tf), self.ct.texts)}
        self.created: list[str] = []
        self.warnings: list[str] = []

    # lookups
    def _category(self, name, path: str) -> Category:
        found = [e for e in self.tf.elements if isinstance(e, Category) and e.kind == CATEGORY and e.name == name]
        if not found:
            raise ToolError("not_found", f"{path}: no category named {name!r}", hint="triggers_tree lists categories")
        if len(found) > 1:
            raise ToolError("ambiguous", f"{path}: {len(found)} categories are named {name!r}", hint="rename one first")
        return found[0]

    def _first_category(self, path: str) -> Category:
        c = next((e for e in self.tf.elements if isinstance(e, Category) and e.kind == CATEGORY), None)
        if c is None:
            raise ToolError("bad_op", f"{path}: the map has no trigger category yet; create one first", hint=_HINT)
        return c

    def _variable(self, name) -> Variable | None:
        return next((v for v in self.tf.variables if v.name == name), None)

    def _variable_element(self, v: Variable) -> VariableElement | None:
        return next((e for e in self.tf.elements if isinstance(e, VariableElement) and e.id == v.id), None)

    def _trigger(self, name) -> Trigger | None:
        return next((e for e in _triggers(self.tf) if e.name == name), None)

    def _users(self, variable_name: str, skip=None) -> list[str]:
        return [t.name for t in _triggers(self.tf) if t is not skip
                and any(p.type == VARIABLE and p.value == variable_name for p in _all_params(t.ecas))]

    def _rename_references(self, old: str, new: str) -> None:
        for t in _triggers(self.tf):
            for p in _all_params(t.ecas):
                if p.type == VARIABLE and p.value == old:
                    p.value = new
        if any(old in (s or "") for s in [self.ct.header, *self.text.values()]):
            self.warnings.append(f"custom script text still mentions {old}; update it by hand")

    # element order and ids
    def _new_id(self, kind: int) -> int:
        i, prefix = COUNTER[kind], wtg.ID_PREFIX[kind]
        n, deleted = self.tf.counters[i]
        used = [e.id & 0xFFFFFF for e in [*self.tf.elements, *self.tf.variables] if (e.id >> 24) == prefix]
        low = max([n] + [u + 1 for u in used])
        self.tf.counters[i] = (low + 1, deleted)
        return (prefix << 24) | low

    def _remove(self, element, kind: int) -> None:
        self.tf.elements = [e for e in self.tf.elements if e is not element]
        n, deleted = self.tf.counters[COUNTER[kind]]
        self.tf.counters[COUNTER[kind]] = (n, deleted + [element.id & 0xFFFFFF])

    def _subtree(self, element_id: int) -> set[int]:
        ids = {element_id}
        for e in self.tf.elements:  # parents precede children
            if e.parent in ids:
                ids.add(e.id)
        return ids

    def _place(self, elements: list, parent_id: int) -> None:
        block = self._subtree(parent_id)
        at = max((i for i, e in enumerate(self.tf.elements) if e.id in block), default=len(self.tf.elements) - 1) + 1
        self.tf.elements[at:at] = elements

    def _move(self, element, parent_id: int, path: str) -> None:
        moving_ids = self._subtree(element.id)
        if parent_id in moving_ids:
            raise ToolError("bad_op", f"{path}: a category cannot move into itself", hint=_HINT)
        moving = [e for e in self.tf.elements if e.id in moving_ids]
        self.tf.elements = [e for e in self.tf.elements if e.id not in moving_ids]
        element.parent = parent_id
        self._place(moving, parent_id)

    # ops
    def op_category(self, op: dict, path: str) -> None:
        name = op.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ToolError("bad_op", f"{path}: name is required", hint=_HINT)
        exists = any(isinstance(e, Category) and e.kind == CATEGORY and e.name == name for e in self.tf.elements)
        parent_id = _root(self.tf).id
        if op.get("parent") is not None:
            parent_id = self._category(op["parent"], f"{path}.parent").id
        if exists:
            c = self._category(name, path)
            if "parent" in op and c.parent != parent_id:
                self._move(c, parent_id, path)
        else:
            c = Category(CATEGORY, self._new_id(CATEGORY), name, parent=parent_id)
            self._place([c], parent_id)
            self.created.append(name)
        if "comment" in op:
            c.is_comment = int(bool(op["comment"]))
        if "new_name" in op:
            new = op["new_name"]
            if not isinstance(new, str) or not new.strip():
                raise ToolError("bad_value", f"{path}: new_name must be a non-empty name", path=f"{path}.new_name")
            c.name = new

    def op_variable(self, op: dict, path: str) -> None:
        name = op.get("name")
        if not isinstance(name, str) or not NAME_RE.match(name):
            raise ToolError("bad_value", f"{path}: variable names start with a letter and use letters, digits and _",
                            path=f"{path}.name")
        v = self._variable(name)
        if v is None:
            if "type" not in op:
                raise ToolError("bad_op", f"{path}: type is required for a new variable", hint=_HINT)
            category = self._category(op["category"], f"{path}.category") if "category" in op else self._first_category(path)
            v = Variable(name, "", id=self._new_id(wtg.VARIABLE_ELEMENT), parent=category.id)
            self.tf.variables.append(v)
            self._place([VariableElement(v.id, name, category.id)], category.id)
            self.created.append(name)
        elif "category" in op:
            category = self._category(op["category"], f"{path}.category")
            v.parent = category.id
            element = self._variable_element(v)
            if element is not None:
                self._move(element, category.id, path)
        if "type" in op:
            t = self.td.types.get(op["type"]) if isinstance(op["type"], str) else None
            if t is None or not t.global_ok:
                raise ToolError("bad_value", f"{path}: {op['type']!r} is not a variable type",
                                hint="data_search kind=trigger_type lists types", path=f"{path}.type")
            v.type = t.name
        if "array_size" in op:
            size = op["array_size"]
            if size is not None and (not isinstance(size, int) or isinstance(size, bool) or not 1 <= size <= 32768):
                raise ToolError("bad_value", f"{path}: array_size must be 1-32768 or null", path=f"{path}.array_size")
            v.is_array, v.array_size = (1, size) if size else (0, 1)
        if "initial" in op:
            text = "" if op["initial"] is None else literal_text(op["initial"])
            if text is None:
                raise ToolError("bad_value", f"{path}: initial must be a literal", path=f"{path}.initial")
            v.initial, v.initialized = text, int(text != "")
        if v.initialized:
            checker = Checker(self.td, {}, set())
            checker.literal(v.initial, v.type, f"{path}.initial")
            if checker.errors:
                raise ToolError("bad_value", checker.errors[0], path=f"{path}.initial")
        if "new_name" in op:
            new = op["new_name"]
            if not isinstance(new, str) or not NAME_RE.match(new):
                raise ToolError("bad_value", f"{path}: new_name is not a valid variable name", path=f"{path}.new_name")
            if self._variable(new) is not None:
                raise ToolError("name_taken", f"{path}: a variable named {new!r} already exists")
            self._rename_references(v.name, new)
            element = self._variable_element(v)
            if element is not None:
                element.name = new
            v.name = new

    def _check_trigger_name(self, name, current, path: str) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ToolError("bad_value", f"{path}: trigger names must be non-empty text", path=path)
        if any(t is not current and script_name(t.name) == script_name(name) for t in _triggers(self.tf)):
            raise ToolError("name_taken", f"{path}: trigger {name!r} clashes with an existing trigger name",
                            hint="names that differ only in spaces or punctuation share one script name")

    def op_trigger(self, op: dict, path: str) -> None:
        name = op.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ToolError("bad_op", f"{path}: name is required", hint=_HINT)
        sections = [key for key, _ in SECTIONS if key in op]
        if "script" in op and sections:
            raise ToolError("bad_op", f"{path}: give either script or events/conditions/actions", hint=_HINT)
        t = self._trigger(name)
        if t is None:
            self._check_trigger_name(name, None, path)
            category = self._category(op["category"], f"{path}.category") if "category" in op else self._first_category(path)
            t = Trigger(TRIGGER, name, id=self._new_id(TRIGGER), parent=category.id)
            self._place([t], category.id)
            self.text[t.id] = None
            self.created.append(name)
        elif "category" in op:
            self._move(t, self._category(op["category"], f"{path}.category").id, path)
        if "description" in op:
            if not isinstance(op["description"], str):
                raise ToolError("bad_value", f"{path}: description must be text", path=f"{path}.description")
            t.description = op["description"]
        for key, attr, invert in (("enabled", "enabled", False), ("initially_on", "initially_off", True),
                                  ("run_on_init", "run_on_init", False)):
            if key in op:
                if not isinstance(op[key], bool):
                    raise ToolError("bad_value", f"{path}: {key} must be true or false", path=f"{path}.{key}")
                setattr(t, attr, int(op[key] != invert))
        if "script" in op:
            if not isinstance(op["script"], str):
                raise ToolError("bad_value", f"{path}: script must be text", path=f"{path}.script")
            t.custom_text, t.ecas, self.text[t.id] = 1, [], op["script"]
        elif sections:
            variables = {v.name: v for v in self.tf.variables}
            current = {key: ([] if t.custom_text else [e for e in t.ecas if e.kind == kind]) for key, kind in SECTIONS}
            for key, kind in SECTIONS:
                if key in op:
                    current[key] = ecas_from_json(op[key], kind, self.td, variables, f"{path}.{key}")
            checker = Checker(self.td, variables, {script_name(x.name) for x in _triggers(self.tf)})
            for key, _ in SECTIONS:
                checker.ecas(current[key], f"{path}.{key}")
            if checker.errors:
                raise ToolError("invalid_trigger", f"{path}: {len(checker.errors)} problem(s), first: {checker.errors[0]}",
                                hint="data_get kind=trigger_function shows argument types", errors=checker.errors[:20])
            self.warnings += checker.warnings
            t.ecas = current["events"] + current["conditions"] + current["actions"]
            t.custom_text, self.text[t.id] = 0, None
        if "new_name" in op:
            self._check_trigger_name(op["new_name"], t, f"{path}.new_name")
            self._rename_references("gg_trg_" + script_name(t.name), "gg_trg_" + script_name(op["new_name"]))
            t.name = op["new_name"]

    def op_delete(self, op: dict, path: str) -> None:
        what, name = op.get("what"), op.get("name")
        if what == "variable":
            v = self._variable(name)
            if v is None:
                raise ToolError("not_found", f"{path}: no variable named {name!r}", hint="triggers_tree lists variables")
            users = self._users(v.name)
            if users:
                raise ToolError("in_use", f"{path}: variable {name!r} is used by {len(users)} trigger(s)",
                                hint="change those triggers first", triggers=users[:20])
            self.tf.variables = [x for x in self.tf.variables if x is not v]
            element = self._variable_element(v)
            if element is not None:
                self._remove(element, wtg.VARIABLE_ELEMENT)
        elif what == "trigger":
            t = self._trigger(name)
            if t is None:
                raise ToolError("not_found", f"{path}: no trigger named {name!r}", hint="triggers_tree lists triggers")
            users = self._users("gg_trg_" + script_name(t.name), skip=t)
            if users:
                raise ToolError("in_use", f"{path}: trigger {name!r} is used by {len(users)} trigger(s)",
                                hint="change those triggers first", triggers=users[:20])
            self._remove(t, TRIGGER)
            self.text.pop(t.id, None)
        elif what == "category":
            c = self._category(name, path)
            children = [e for e in self.tf.elements if e.parent == c.id]
            if children:
                raise ToolError("not_empty", f"{path}: category {name!r} still holds {len(children)} item(s)",
                                hint="move or delete them first")
            self._remove(c, CATEGORY)
        else:
            raise ToolError("bad_op", f'{path}: what must be "trigger", "category" or "variable"', hint=_HINT)

    def op_header(self, op: dict, path: str) -> None:
        for key in ("script", "comment"):
            if key in op and not isinstance(op[key], str):
                raise ToolError("bad_value", f"{path}: {key} must be text", path=f"{path}.{key}")
        if "script" in op:
            self.ct.header = op["script"] or None
        if "comment" in op:
            self.ct.comment = op["comment"]

    def finish(self) -> dict:
        self.ct.texts = [self.text.get(t.id) for t in _triggers(self.tf)]
        data, text = wtg.serialize(self.tf), wct.serialize(self.ct)
        if data != self.before[0]:
            self.project.write("war3map.wtg", data)
        if text != self.before[1]:
            self.project.write("war3map.wct", text)
        changed = (data, text) != self.before
        if changed:
            self.warnings.append(SCRIPT_WARNING)
        return {"changed": changed, "created": self.created, "warnings": self.warnings}


def triggers_edit(project, catalog, ops: list) -> dict:
    edit = _Edit(project, catalog)
    for i, op in enumerate(ops):
        path = f"ops[{i}]"
        try:
            action = op.get("op") if isinstance(op, dict) else None
            if action not in ALLOWED:
                raise ToolError("bad_op", f"{path}: unknown op {action!r}", hint=_HINT)
            extra = set(op) - {"op"} - ALLOWED[action]
            if extra:
                raise ToolError("bad_op", f"{path}: unknown keys {sorted(extra)}", hint=_HINT)
            getattr(edit, f"op_{action}")(op, path)
        except ToolError as e:
            e.details.setdefault("op_index", i)
            raise
    return edit.finish()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `& $PY -m pytest tests/ops/test_triggers.py -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/wc3mcp/ops/triggers.py tests/ops/test_triggers.py
git commit -m "feat(ops): atomic trigger, variable, category and header edits" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Server tools and full verification

**Files:**
- Modify: `src/wc3mcp/server.py`, `tests/test_server.py`

**Interfaces:**
- Consumes: Task 4 `triggers_tree`, `trigger_get`; Task 5 `triggers_edit`; Task 1 trigger kinds; server `_tool`, `_project`, `_catalog`.
- Produces: MCP tools `triggers_tree(path)`, `trigger_get(path, name=None)`, `triggers_edit(path, ops)`; `data_search`/`data_get` accept `trigger_function`, `trigger_type`, `trigger_preset`.

- [ ] **Step 1: Write the failing test**

In `tests/test_server.py`, extend `EXPECTED`:
```python
EXPECTED = {"map_open", "map_close", "map_save", "map_status", "map_file_read", "map_file_write", "map_snapshot",
            "data_search", "data_get", "data_file", "info_get", "info_edit", "imports_edit",
            "objdata_list", "objdata_get", "objdata_edit", "triggers_tree", "trigger_get", "triggers_edit"}
```

Append to `tests/test_server.py`:
```python
@needs_install
def test_trigger_tools(tmp_path):
    maps = ladder_maps()
    if not maps:
        pytest.skip("no ladder maps in Documents")
    src = tmp_path / maps[0].name
    src.write_bytes(maps[0].read_bytes())
    path = str(src)
    payload(call("map_open", {"path": path}))
    assert payload(call("triggers_tree", {"path": path}))["triggers"][0]["name"] == "Melee Initialization"
    created = payload(call("triggers_edit", {"path": path, "ops": [{"op": "trigger", "name": "Hello", "actions": [
        {"fn": "DisplayTextToForce", "args": [{"call": "GetPlayersAll"}, "Hi"]}]}]}))
    assert created["created"] == ["Hello"]
    doc = payload(call("trigger_get", {"path": path, "name": "Hello"}))
    assert doc["text"].splitlines()[-1] == "    Game - Display to (All players) the text: Hi"
    found = payload(call("data_search", {"kind": "trigger_function", "query": "DisplayTextToForce"}))
    assert "DisplayTextToForce" in [r["id"] for r in found["results"]]
    err = call("triggers_edit", {"path": path, "ops": [{"op": "trigger", "name": "Hello", "actions": [{"fn": "Nope"}]}]})
    assert err.isError and json.loads(err.content[0].text.split(": ", 1)[1])["code"] == "unknown_function"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& $PY -m pytest tests/test_server.py -q`
Expected: FAIL in `test_tools_are_registered`, `test_stdio_server_starts` and `test_trigger_tools`

- [ ] **Step 3: Write minimal implementation**

In `src/wc3mcp/server.py`:
- add to the local imports: `from .ops import triggers as triggers_ops`
- extend `Kind` with the trigger kinds:
```python
Kind = Literal["unit", "item", "ability", "buff", "upgrade", "destructible", "doodad", "tile", "cliff", "water",
               "sound", "model", "icon", "file", "trigger_function", "trigger_type", "trigger_preset"]
```
- in the `data_search` docstring, after "(model, icon, file)", add: "; trigger_function / trigger_type / trigger_preset search GUI trigger functions, variable types and preset values"
- add after `objdata_edit`:
```python
@_tool
def triggers_tree(path: str) -> dict:
    """Trigger Editor overview of an open map: categories, triggers (type gui/text/comment, enabled, initially on,
    run on map init, function count) and global variables."""
    return triggers_ops.triggers_tree(_project(path), _catalog("enUS", "Custom_V1", True))


@_tool
def trigger_get(path: str, name: str | None = None) -> dict:
    """One trigger. GUI triggers come as events/conditions/actions JSON (the shape triggers_edit takes) plus the
    editor's text; text triggers as script. Without name: the map's custom script header and comment."""
    return triggers_ops.trigger_get(_project(path), _catalog("enUS", "Custom_V1", True), name)


@_tool
def triggers_edit(path: str, ops: list[dict]) -> dict:
    """All-or-nothing Trigger Editor changes. ops:
    {"op": "category", "name", "parent"?, "new_name"?};
    {"op": "variable", "name", "type", "array_size"?, "initial"?, "category"?, "new_name"?};
    {"op": "trigger", "name", "category"?, "description"?, "enabled"?, "initially_on"?, "run_on_init"?,
     "events"/"conditions"/"actions": [{"fn": "KillUnit", "args": [{"call": "GetTriggerUnit"}]}, ...] or
     "script": "<JASS or Lua>", "new_name"?};
    {"op": "delete", "what": "trigger"|"category"|"variable", "name"}; {"op": "header", "script"?, "comment"?}.
    An argument is a literal, {"preset": name}, {"var": name, "index"?} or {"call": name, "args": [...]}; block
    functions take "if"/"then"/"else" (IfThenElseMultiple), "conditions" (And/OrMultiple) or "actions" (loops).
    GUI code is checked against TriggerData; data_search kind=trigger_function finds functions."""
    return triggers_ops.triggers_edit(_project(path), _catalog("enUS", "Custom_V1", True), ops)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& $PY -m pytest tests/test_server.py -q`
Expected: 8 passed

Run: `& $PY -m pytest -q`
Expected: every test passes

- [ ] **Step 5: Commit**

```bash
git add src/wc3mcp/server.py tests/test_server.py
git commit -m "feat(server): triggers_tree, trigger_get and triggers_edit tools" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```
