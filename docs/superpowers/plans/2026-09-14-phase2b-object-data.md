# Phase 2b — Object Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read and edit custom and modified game objects (units, items, destructibles, doodads, abilities, buffs, upgrades) through MCP tools `objdata_list`, `objdata_get`, `objdata_edit`, backed by a byte-exact codec for the object modification files.

**Architecture:** `wc3mcp.formats.objmods` parses/serializes `war3map.w3u/.w3t/.w3b/.w3d/.w3a/.w3h/.w3q` and their `war3mapSkin.*` twins. `wc3mcp.ops.objdata` merges map modifications over base values from the Phase 1 catalog, resolves fields by raw code or name using the metadata SLKs, writes each field to the main or skin file the way the 2.x editor does, allocates custom ids, and applies edit batches atomically.

**Tech Stack:** Python 3.13.14 (Microsoft Store interpreter), stdlib, `mcp 1.27.0` (FastMCP), `pytest 9.0.3`.

**Spec:** `docs/superpowers/specs/2026-09-14-wc3-mcp-design.md` (build-order item 2, part 2b). Builds on `docs/superpowers/plans/2026-09-14-phase2a-map-info.md`.

## Global Constraints

- Interpreter by full path: `%LOCALAPPDATA%\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\python.exe` (written `$PY`). Run tests from `D:\Warcraft III\wc3-mcp`: `& $PY -m pytest <args>`.
- Branch: `phase2b-object-data` (stacked on `phase2a-map-info`; all phase branches are merged online after the last phase).
- No new dependencies. Never write under the game install. Corpus tests read local data at runtime and skip when missing.
- Object files: read and write format versions 2 and 3 only; a v3 object with a modification-set count other than 1 is rejected (never seen locally). Unknown raw codes and existing end tokens are preserved byte-for-byte.
- Every edit batch is atomic; errors are `ToolError` with `code`, `message`, `hint`, and `op_index` or other details.
- Commit messages end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- When writing code through tools, spell special characters as `\N{NAME}` or `\xNN` escapes (backslash-u escapes in tool parameters arrive as literal characters).
- Not in 2b: gameplay constants (`war3mapMisc.txt`), campaign object data (`war3campaign.*`, Phase 5), the combined `war3map.w3o` export format, reference checks against placed units or triggers.

## Verified facts this plan relies on (probed 2026-09-14 on 556 local maps)

- **Layout** (all 1,537 local object files, main and skin, parse byte-exactly): i32 version (2 or 3); original table then custom table, each: i32 object count, then per object: base id (4 bytes), new id (4 bytes, zero in the original table); v3 only: i32 set count (always 1) and i32 set flag (always 0); i32 modification count; per modification: id (4 bytes), i32 value type (0 int, 1 real, 2 unreal, 3 string), for `.w3d`/`.w3a`/`.w3q` only: i32 level (doodads: variation) and i32 data pointer; value (i32, f32, f32, or NUL-terminated UTF-8); end token (4 bytes). War3Net (`Serialization/Binary/Object/LevelObjectDataModification.cs`) confirms id, type, level, pointer, value, end token.
- **End tokens:** original-table modifications mostly store the base id, custom-table modifications mostly store zero; 581 modifications in old campaign maps hold unrelated ids. New modifications follow the majority convention; existing tokens are kept.
- **Value type by metadata `type`** (no metadata type maps to two value types locally): `real` → 1, `unreal` → 2; int (0) for `int`, `bool`, `attackBits`, `channelFlags`, `channelType`, `deathType`, `detectionType`, `fullFlags`, `spellDetail`, `stackFlags`, `teamColor`, `versionFlags`, and — types never used in local maps whose `UI/UnitEditorData.txt` values are numeric — `damageType`, `defenseTypeInt`, `interactionFlags`, `morphFlags`, `pickFlags`, `proctargetType`, `silenceFlags`; every other type (strings, lists, enums with text values such as `attackType`, `equipmentType`, `occlusionType`, models, icons, `upgradeCode`, ...) → string (3).
- **Level / data pointer:** for every local modification the data pointer equals the metadata `data` column (ability Data A = 1, ...), and fields with metadata `repeat > 0` use level ≥ 1 (non-repeat fields use 0) — except 9 legacy tooltip modifications stored at level 0, which are preserved.
- **Main vs skin file (v3):** a field is written to `war3mapSkin.<ext>` exactly when its metadata `netsafe` value is `1` or `11`; otherwise to `war3map.<ext>`. Doodad metadata has no `netsafe` column and doodad skin files hold no modifications. The editor mirrors every object in both files, with an empty modification list where it has no fields.
- **Custom ids:** units keep the base id's first character (`hfoo` → `h...`); items use `I`, destructibles `B`, doodads `D`, abilities `A`, buffs `B`, upgrades `R`; the three-character suffix uses `0-9A-Z`.
- **Sample data (WarChasers, `Maps/Scenario/(4)WarChasers.w3m`, v3):** custom unit `nC01` (base `negf`) has `uacq` = 1200.0 in the main file and `unam` = `juggernaut tower` in the skin file; unmodified `hfoo` resolves to catalog name `Footman`; custom item `IC17` (base `ankh`) has `igol` = 5000.
- Catalog metadata: `netsafe` values are `0`, `1`, `11` (unit/item metadata), and absent for doodads and three ability rows.

## File Structure

```
src/wc3mcp/gamedata/catalog.py   + FieldMeta.netsafe, public Catalog.applies()
src/wc3mcp/formats/objmods.py    ObjectMods codec (versions 2/3, level-carrying files)
src/wc3mcp/ops/strings.py        load_strings(project) shared by info and objdata
src/wc3mcp/ops/info.py           use ops.strings.load_strings
src/wc3mcp/ops/objdata.py        objdata_list / objdata_get / objdata_edit
src/wc3mcp/server.py             + objdata_list, objdata_get, objdata_edit tools
tests/gamedata/test_catalog.py   + netsafe / applies test
tests/formats/test_objmods.py
tests/ops/test_objdata.py
tests/test_server.py             + object data tool test
```

---

### Task 1: Catalog exposes `netsafe` and field applicability

**Files:**
- Modify: `src/wc3mcp/gamedata/catalog.py` (`FieldMeta`, `Catalog.fields`, `_applies` → `applies`)
- Test: `tests/gamedata/test_catalog.py` (append)

**Interfaces:**
- Produces: `FieldMeta.netsafe: str` (metadata `netsafe` column, `"0"` when absent); `Catalog.applies(kind, obj_id, meta) -> bool` (public; `get` uses it).

- [ ] **Step 1: Write the failing test**

Append to `tests/gamedata/test_catalog.py`:
```python
def test_field_netsafe_and_applicability(cat):
    units = {f.id: f for f in cat.fields("unit")}
    assert units["unam"].netsafe == "1" and units["uhpm"].netsafe == "0"
    abilities = {f.id: f for f in cat.fields("ability")}
    assert cat.applies("ability", "AHbz", abilities["Hbz1"])
    assert not cat.applies("ability", "AHbz", abilities["hem1"])
    assert cat.applies("unit", "hfoo", units["uhpm"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& $PY -m pytest tests/gamedata/test_catalog.py -q`
Expected: FAIL with `AttributeError: 'FieldMeta' object has no attribute 'netsafe'`

- [ ] **Step 3: Write minimal implementation**

In `src/wc3mcp/gamedata/catalog.py`:

Add a field at the end of `FieldMeta` (after `not_specific`):
```python
    netsafe: str = "0"  # "1"/"11": cosmetic field that the 2.x editor stores in war3mapSkin.* files
```

In `Catalog.fields`, extend the `FieldMeta(...)` call's last line so it reads:
```python
                    use_specific=_codes(r.get("useSpecific")), not_specific=_codes(r.get("notSpecific")),
                    netsafe=r.get("netsafe") or "0"))
```

Rename the method `_applies` to `applies` (same body) and update its use in `get`:
```python
            if not self.applies(kind, obj_id, meta):
                continue
```

- [ ] **Step 4: Run test to verify it passes**

Run: `& $PY -m pytest tests/gamedata -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/wc3mcp/gamedata/catalog.py tests/gamedata/test_catalog.py
git commit -m "feat(gamedata): expose field netsafe flag and applicability" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

### Task 2: Object modification codec

**Files:**
- Create: `src/wc3mcp/formats/objmods.py`
- Test: `tests/formats/test_objmods.py`

**Interfaces:**
- Consumes: Phase 2a `Reader`, `Writer`, `FormatError`; corpus helpers `sample_map_ids`, `open_sample`.
- Produces: constants `INT, REAL, UNREAL, STRING = 0, 1, 2, 3`, `ZERO_ID = b"\0\0\0\0"`, `LEVEL_EXTENSIONS = frozenset({"w3d", "w3a", "w3q"})`, `EXTENSIONS = ("w3u", "w3t", "w3b", "w3d", "w3a", "w3h", "w3q")`; dataclasses `Mod(id: bytes, var_type: int, value, level=0, pointer=0, end=ZERO_ID)`, `ObjectEntry(base_id: bytes, new_id=ZERO_ID, mods=[], set_flag=0)`, `ObjectMods(version=3, levels=False, original=[], custom=[], trailing=b"")`; `parse(data: bytes, levels: bool) -> ObjectMods`; `serialize(ObjectMods) -> bytes`.

- [ ] **Step 1: Write the failing test**

`tests/formats/test_objmods.py`:
```python
import pytest

from corpus import open_sample, sample_map_ids
from wc3mcp.formats import objmods
from wc3mcp.formats.binary import FormatError
from wc3mcp.formats.objmods import STRING, UNREAL, ZERO_ID, Mod, ObjectEntry, ObjectMods


def test_constructed_roundtrip_with_and_without_levels():
    om = ObjectMods(3, levels=True, original=[ObjectEntry(b"AHbz", mods=[Mod(b"Hbz1", 0, 7, level=1, pointer=1, end=b"AHbz")])],
                    custom=[ObjectEntry(b"AHbz", b"A000", [Mod(b"anam", STRING, "Big Storm"), Mod(b"acdn", UNREAL, 0.5, 2)])])
    assert objmods.parse(objmods.serialize(om), levels=True) == om
    simple = ObjectMods(2, levels=False, custom=[ObjectEntry(b"hfoo", b"h000", [Mod(b"uhpm", 0, 777)])])
    assert objmods.parse(objmods.serialize(simple), levels=False) == simple


def test_rejects_unsupported_input():
    with pytest.raises(FormatError):
        objmods.parse((1).to_bytes(4, "little") + bytes(8), levels=False)
    two_sets = (3).to_bytes(4, "little") + (1).to_bytes(4, "little") + b"hfoo" + ZERO_ID + (2).to_bytes(4, "little")
    with pytest.raises(FormatError):
        objmods.parse(two_sets + bytes(16), levels=False)
    bad_type = ((2).to_bytes(4, "little") + (1).to_bytes(4, "little") + b"hfoo" + ZERO_ID + (1).to_bytes(4, "little")
                + b"uhpm" + (9).to_bytes(4, "little") + bytes(8) + (0).to_bytes(4, "little"))
    with pytest.raises(FormatError):
        objmods.parse(bad_type, levels=False)


@pytest.mark.parametrize("map_id", sample_map_ids())
def test_corpus_roundtrip_is_byte_exact(map_id):
    arc = open_sample(map_id)
    found = 0
    for ext in objmods.EXTENSIONS:
        for prefix in ("war3map", "war3mapSkin"):
            data = arc.read(f"{prefix}.{ext}")
            if data is None:
                continue
            found += 1
            om = objmods.parse(data, levels=ext in objmods.LEVEL_EXTENSIONS)
            assert om.trailing == b"" and objmods.serialize(om) == data, f"{prefix}.{ext}"
    if not found:
        pytest.skip("map has no object data")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& $PY -m pytest tests/formats/test_objmods.py -q`
Expected: FAIL with `ImportError: cannot import name 'objmods' from 'wc3mcp.formats'`

- [ ] **Step 3: Write minimal implementation**

`src/wc3mcp/formats/objmods.py`:
```python
"""Object modification files: war3map.w3u/.w3t/.w3b/.w3d/.w3a/.w3h/.w3q and their war3mapSkin.* twins.
Versions 2 and 3; byte-exact on every local map."""
from dataclasses import dataclass, field

from .binary import FormatError, Reader, Writer

INT, REAL, UNREAL, STRING = 0, 1, 2, 3
ZERO_ID = b"\0\0\0\0"
EXTENSIONS = ("w3u", "w3t", "w3b", "w3d", "w3a", "w3h", "w3q")
LEVEL_EXTENSIONS = frozenset({"w3d", "w3a", "w3q"})  # records carry a level (doodads: variation) and a data pointer


@dataclass
class Mod:
    id: bytes
    var_type: int
    value: int | float | str
    level: int = 0
    pointer: int = 0
    end: bytes = ZERO_ID


@dataclass
class ObjectEntry:
    base_id: bytes
    new_id: bytes = ZERO_ID
    mods: list[Mod] = field(default_factory=list)
    set_flag: int = 0  # v3: flag of the single modification set (always 0 locally)


@dataclass
class ObjectMods:
    version: int = 3
    levels: bool = False
    original: list[ObjectEntry] = field(default_factory=list)
    custom: list[ObjectEntry] = field(default_factory=list)
    trailing: bytes = b""


def parse(data: bytes, levels: bool) -> ObjectMods:
    r = Reader(data)
    version = r.i32()
    if version not in (2, 3):
        raise FormatError(f"unsupported object data version {version}")
    om = ObjectMods(version, levels)
    for table in (om.original, om.custom):
        for _ in range(r.count(item_size=12)):
            entry = ObjectEntry(r.raw(4), r.raw(4))
            if version >= 3:
                sets = r.i32()
                if sets != 1:
                    # ponytail: only single-set objects exist locally; add multi-set support when a real file has one
                    raise FormatError(f"object {entry.base_id!r}: {sets} modification sets are not supported")
                entry.set_flag = r.i32()
            for _ in range(r.count(item_size=12)):
                mod = Mod(r.raw(4), r.i32(), 0)
                if levels:
                    mod.level, mod.pointer = r.i32(), r.i32()
                if mod.var_type == INT:
                    mod.value = r.i32()
                elif mod.var_type in (REAL, UNREAL):
                    mod.value = r.f32()
                elif mod.var_type == STRING:
                    mod.value = r.cstr()
                else:
                    raise FormatError(f"unknown value type {mod.var_type} at offset {r.pos - 4}")
                mod.end = r.raw(4)
                entry.mods.append(mod)
            table.append(entry)
    om.trailing = r.rest()
    return om


def _four(b: bytes, what: str) -> bytes:
    if len(b) != 4:
        raise FormatError(f"{what} must be exactly 4 bytes")
    return b


def serialize(om: ObjectMods) -> bytes:
    w = Writer()
    w.i32(om.version)
    for table in (om.original, om.custom):
        w.i32(len(table))
        for entry in table:
            w.raw(_four(entry.base_id, "base id"))
            w.raw(_four(entry.new_id, "new id"))
            if om.version >= 3:
                w.i32(1)
                w.i32(entry.set_flag)
            w.i32(len(entry.mods))
            for mod in entry.mods:
                w.raw(_four(mod.id, "modification id"))
                w.i32(mod.var_type)
                if om.levels:
                    w.i32(mod.level)
                    w.i32(mod.pointer)
                if mod.var_type == INT:
                    w.i32(mod.value)
                elif mod.var_type in (REAL, UNREAL):
                    w.f32(mod.value)
                elif mod.var_type == STRING:
                    w.cstr(mod.value)
                else:
                    raise FormatError(f"unknown value type {mod.var_type}")
                w.raw(_four(mod.end, "end token"))
    w.raw(om.trailing)
    return w.getvalue()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `& $PY -m pytest tests/formats/test_objmods.py -q`
Expected: 2 unit tests pass; corpus cases pass for maps with object data and skip for the rest

- [ ] **Step 5: Commit**

```bash
git add src/wc3mcp/formats/objmods.py tests/formats/test_objmods.py
git commit -m "feat(formats): object modification codec (w3u/w3t/w3b/w3d/w3a/w3h/w3q, v2/v3)" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

### Task 3: Object data reading (`objdata_list`, `objdata_get`)

**Files:**
- Create: `src/wc3mcp/ops/strings.py`, `src/wc3mcp/ops/objdata.py`
- Modify: `src/wc3mcp/ops/info.py` (`_load` uses `load_strings`)
- Test: `tests/ops/test_objdata.py`

**Interfaces:**
- Consumes: Task 1 `FieldMeta.netsafe`, `Catalog.applies`, `Catalog.get/fields/name/ids`; Task 2 `objmods`; Phase 2a `TriggerStrings`, `TRIGSTR`; Phase 1 `MapProject`, `ToolError`.
- Produces: `strings.load_strings(project) -> TriggerStrings` (empty table when `war3map.wts` is missing); in `objdata`: `EXTENSIONS: dict[str, str]` (kind → extension), `var_type(meta_type: str) -> int`, `objdata_list(project, catalog, kind, custom_only=False) -> {"kind", "count", "objects": [{"id", "base", "custom", "modifications", "name"}]}` (custom objects first; unmodified mirror entries omitted), `objdata_get(project, catalog, kind, obj_id, fields=None) -> dict` — the catalog `get` document for the base object with `id`, `base`, `custom`, `levels` (max of base and modified levels), `name`, per field `value` (typed: int / float / string) or `values` (per level) plus `modified` (bool, or list of modified levels) and `value_ref` / `value_refs` for TRIGSTR-backed strings, and `unknown_modifications` (only when `fields` is None). Error codes: `bad_kind`, `bad_file`, `not_found`.
- Internal helpers reused by Task 4: `_load(project, kind) -> (main, skin, raw: dict[name, bytes | None])`, `_key(entry, custom)`, `_entries(files, obj_id)`, `_merged(entries)`, `_f32(v)`, `_name(catalog, kind, base, mods, strings)`.

- [ ] **Step 1: Write the failing test**

`tests/ops/test_objdata.py`:
```python
import pytest

from corpus import _storage, ladder_maps, open_sample, sample_map_ids
from wc3mcp.errors import ToolError
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.ops.objdata import objdata_get, objdata_list, var_type
from wc3mcp.project.workspace import MapProject

WARCHASERS = "casc:Maps/Scenario/(4)WarChasers.w3m"
pytestmark = pytest.mark.skipif(WARCHASERS not in sample_map_ids() or not ladder_maps(),
                                reason="needs the Warcraft III install and ladder maps")


@pytest.fixture(scope="module")
def catalog():
    return Catalog(_storage(), balance=None)  # base data: stable values


@pytest.fixture
def project(tmp_path):
    src = tmp_path / "WarChasers.w3m"
    src.write_bytes(open_sample(WARCHASERS).data)
    return MapProject.open(src)


@pytest.fixture
def plain_project(tmp_path):
    src = tmp_path / ladder_maps()[0].name
    src.write_bytes(ladder_maps()[0].read_bytes())
    return MapProject.open(src)


def test_var_type_rules():
    assert [var_type(t) for t in ("real", "unreal", "bool", "silenceFlags", "attackType", "modelList")] == [1, 2, 0, 0, 3, 3]


def test_list_includes_custom_and_modified_objects(project, catalog):
    units = {o["id"]: o for o in objdata_list(project, catalog, "unit")["objects"]}
    assert units["nC01"] == {"id": "nC01", "base": "negf", "custom": True, "modifications": 9,
                             "name": "juggernaut tower"}
    assert units["nzep"]["custom"] is False and units["nzep"]["modifications"] == 5
    assert all(o["custom"] for o in objdata_list(project, catalog, "unit", custom_only=True)["objects"])
    items = {o["id"]: o for o in objdata_list(project, catalog, "item")["objects"]}
    assert items["IC17"]["name"] == "Ankh of Reincarnation Deluxe"


def test_get_merges_main_and_skin_over_base(project, catalog):
    doc = objdata_get(project, catalog, "unit", "nC01")
    assert (doc["base"], doc["custom"], doc["name"]) == ("negf", True, "juggernaut tower")
    assert doc["fields"]["uacq"]["value"] == 1200.0 and doc["fields"]["uacq"]["modified"] is True
    assert doc["fields"]["unam"]["value"] == "juggernaut tower"
    assert any(f["modified"] is False for f in doc["fields"].values())
    assert objdata_get(project, catalog, "item", "IC17", fields=["igol"])["fields"]["igol"]["value"] == 5000


def test_get_unmodified_objects_have_typed_base_values(plain_project, catalog):
    unit = objdata_get(plain_project, catalog, "unit", "hfoo", fields=["uhpm"])
    assert unit["custom"] is False and unit["name"] == "Footman"
    assert unit["fields"]["uhpm"]["value"] == 420 and unit["fields"]["uhpm"]["modified"] is False
    ability = objdata_get(plain_project, catalog, "ability", "AHbz", fields=["Hbz1"])
    assert ability["fields"]["Hbz1"]["values"] == [6, 8, 10] and ability["fields"]["Hbz1"]["modified"] == []


def test_unknown_kind_and_object(project, catalog):
    with pytest.raises(ToolError) as e:
        objdata_list(project, catalog, "hero")
    assert e.value.code == "bad_kind"
    with pytest.raises(ToolError) as e:
        objdata_get(project, catalog, "unit", "zzzz")
    assert e.value.code == "not_found"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& $PY -m pytest tests/ops/test_objdata.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'wc3mcp.ops.objdata'`

- [ ] **Step 3: Write minimal implementation**

`src/wc3mcp/ops/strings.py`:
```python
"""The map's trigger string table (war3map.wts)."""
from ..errors import ToolError
from ..formats.wts import TriggerStrings


def load_strings(project) -> TriggerStrings:
    try:
        return TriggerStrings.parse(project.read("war3map.wts"))
    except ToolError as e:
        if e.code != "no_such_file":
            raise
        return TriggerStrings()
```

In `src/wc3mcp/ops/info.py`, add `from .strings import load_strings` to the imports and replace `_load` with:
```python
def _load(project) -> tuple[w3i.MapInfo, TriggerStrings]:
    try:
        mi = w3i.parse(project.read("war3map.w3i"))
    except FormatError as e:
        raise ToolError("bad_file", f"war3map.w3i: {e}") from e
    return mi, load_strings(project)
```

`src/wc3mcp/ops/objdata.py`:
```python
"""Object data (the Object Editor): map modifications merged over base game data, plus atomic edits."""
import struct

from ..errors import ToolError
from ..formats import objmods
from ..formats.binary import FormatError
from ..formats.objmods import INT, LEVEL_EXTENSIONS, REAL, STRING, UNREAL, Mod, ObjectEntry, ObjectMods
from ..formats.wts import TRIGSTR, TriggerStrings
from .strings import load_strings

EXTENSIONS = {"unit": "w3u", "item": "w3t", "destructible": "w3b", "doodad": "w3d", "ability": "w3a",
              "buff": "w3h", "upgrade": "w3q"}
INT_TYPES = frozenset({
    "int", "bool", "attackBits", "channelFlags", "channelType", "deathType", "detectionType", "fullFlags",
    "spellDetail", "stackFlags", "teamColor", "versionFlags",
    # never used in local maps; UI/UnitEditorData.txt lists numeric values for them
    "damageType", "defenseTypeInt", "interactionFlags", "morphFlags", "pickFlags", "proctargetType", "silenceFlags",
})
NAME_FIELDS = ("name", "editorname", "bufftip")


def var_type(meta_type: str) -> int:
    if meta_type == "real":
        return REAL
    if meta_type == "unreal":
        return UNREAL
    return INT if meta_type in INT_TYPES else STRING


def _check_kind(kind: str) -> str:
    if kind not in EXTENSIONS:
        raise ToolError("bad_kind", f"object data kind {kind!r} is not supported",
                        hint="one of: " + ", ".join(EXTENSIONS))
    return EXTENSIONS[kind]


def _load(project, kind: str) -> tuple[ObjectMods, ObjectMods, dict]:
    """The main and skin files for `kind` (empty v3 tables when absent) plus their original bytes by name."""
    ext = _check_kind(kind)
    levels, files, raw = ext in LEVEL_EXTENSIONS, [], {}
    for prefix in ("war3map", "war3mapSkin"):
        name = f"{prefix}.{ext}"
        try:
            data = project.read(name)
        except ToolError as e:
            if e.code != "no_such_file":
                raise
            data = None
        raw[name] = data
        try:
            files.append(objmods.parse(data, levels) if data is not None else ObjectMods(3, levels))
        except FormatError as e:
            raise ToolError("bad_file", f"{name}: {e}") from e
    return files[0], files[1], raw


def _key(entry: ObjectEntry, custom: bool) -> str:
    return (entry.new_id if custom else entry.base_id).decode("latin-1")


def _entries(files, obj_id: str) -> list[tuple[ObjectMods, bool, ObjectEntry]]:
    return [(om, custom, entry) for om in files for custom, table in ((False, om.original), (True, om.custom))
            for entry in table if _key(entry, custom) == obj_id]


def _merged(entries) -> dict[tuple[str, int], Mod]:
    merged = {}
    for _, _, entry in entries:
        for mod in entry.mods:
            merged[(mod.id.decode("latin-1"), mod.level)] = mod
    return merged


def _f32(v: float) -> float:
    """Shortest decimal that encodes to the same float32 (0.300000012 -> 0.3)."""
    packed = struct.pack("<f", v)
    for digits in range(6, 10):
        candidate = float(f"{v:.{digits}g}")
        if struct.pack("<f", candidate) == packed:
            return candidate
    return v


def _typed(meta_type: str, raw):
    """Catalog values are raw SLK/profile strings; show them with the type the object editor stores."""
    vt = var_type(meta_type)
    if raw is None or vt == STRING:
        return raw
    try:
        return int(float(raw)) if vt == INT else _f32(float(raw))
    except ValueError:
        return raw


def _mod_out(mod: Mod, strings: TriggerStrings) -> tuple[object, str | None]:
    if mod.var_type in (REAL, UNREAL):
        return _f32(mod.value), None
    if mod.var_type == STRING and TRIGSTR.match(mod.value):
        return strings.resolve(mod.value), mod.value
    return mod.value, None


def _name(catalog, kind: str, base: str, mods: dict, strings: TriggerStrings) -> str:
    by_field = {f.field.lower(): f.id for f in catalog.fields(kind)}
    for key in NAME_FIELDS:
        rawcode = by_field.get(key)
        mod = rawcode and (mods.get((rawcode, 0)) or mods.get((rawcode, 1)))
        if mod:
            return str(_mod_out(mod, strings)[0])
    return catalog.name(kind, base)


def objdata_list(project, catalog, kind: str, custom_only: bool = False) -> dict:
    main, skin, _ = _load(project, kind)
    strings = load_strings(project)
    found: dict[str, dict] = {}
    for om in (main, skin):
        for custom, table in ((False, om.original), (True, om.custom)):
            for entry in table:
                oid = _key(entry, custom)
                item = found.setdefault(oid, {"id": oid, "base": entry.base_id.decode("latin-1"), "custom": custom,
                                              "modifications": 0})
                item["modifications"] += len(entry.mods)
    objects = []
    for oid, item in found.items():
        if (custom_only and not item["custom"]) or (not item["custom"] and item["modifications"] == 0):
            continue
        item["name"] = _name(catalog, kind, item["base"], _merged(_entries((main, skin), oid)), strings)
        objects.append(item)
    objects.sort(key=lambda o: (not o["custom"], o["id"]))
    return {"kind": kind, "count": len(objects), "objects": objects}


def objdata_get(project, catalog, kind: str, obj_id: str, fields: list[str] | None = None) -> dict:
    main, skin, _ = _load(project, kind)
    strings = load_strings(project)
    entries = _entries((main, skin), obj_id)
    custom = any(c for _, c, _ in entries)
    base = entries[0][2].base_id.decode("latin-1") if entries else obj_id
    doc = catalog.get(kind, base, fields)
    mods = _merged(entries)
    top = max([doc["levels"]] + [level for _, level in mods])
    used = set()
    for rawcode, entry in doc["fields"].items():
        if "values" in entry:
            values = [_typed(entry["type"], v) for v in entry["values"]]
            values += [None] * (top - len(values))
            modified = []
            for level in range(1, top + 1):
                mod = mods.get((rawcode, level)) or (mods.get((rawcode, 0)) if level == 1 else None)
                if mod is None:
                    continue
                values[level - 1], ref = _mod_out(mod, strings)
                used.add((rawcode, mod.level))
                modified.append(level)
                if ref:
                    entry.setdefault("value_refs", {})[str(level)] = ref
            entry["values"], entry["modified"] = values, modified
        else:
            entry["value"] = _typed(entry["type"], entry["value"])
            mod = mods.get((rawcode, 0))
            entry["modified"] = mod is not None
            if mod is not None:
                entry["value"], ref = _mod_out(mod, strings)
                used.add((rawcode, 0))
                if ref:
                    entry["value_ref"] = ref
    if fields is None:
        doc["unknown_modifications"] = [{"id": rid, "level": level, "value": _mod_out(mod, strings)[0]}
                                        for (rid, level), mod in mods.items() if (rid, level) not in used]
    doc.update({"id": obj_id, "base": base, "custom": custom, "levels": top,
                "name": _name(catalog, kind, base, mods, strings)})
    return doc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& $PY -m pytest tests/ops/test_objdata.py tests/ops/test_info.py -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/wc3mcp/ops/strings.py src/wc3mcp/ops/objdata.py src/wc3mcp/ops/info.py tests/ops/test_objdata.py
git commit -m "feat(ops): object data listing and merged object view" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

### Task 4: Object data edits (`objdata_edit`)

**Files:**
- Modify: `src/wc3mcp/ops/objdata.py` (append edit functions)
- Test: `tests/ops/test_objdata.py` (append)

**Interfaces:**
- Consumes: Task 3 helpers (`_load`, `_key`, `_entries`, `var_type`, `EXTENSIONS`, `load_strings`), Task 2 `objmods`, Task 1 `Catalog.applies`, `FieldMeta.netsafe`.
- Produces: `objdata_edit(project, catalog, kind, ops: list) -> {"changed": bool, "created": [ids], "warnings": []}`. Ops:
  - `{"op": "create", "base": "hfoo", "id": "h000" (optional), "set": {field: value, ...} (optional)}`
  - `{"op": "set", "id": "h000", "set": {field: value, ...}}` — works on custom objects and on base objects (which become modified originals)
  - `{"op": "reset", "id": "...", "fields": [field, ...] (optional; omitted = everything)}`
  - `{"op": "delete", "id": "..."}` — removes a custom object, or all modifications of a base object
  - A field key is a raw code (`uhpm`), a metadata field name (`HP`), or a display name (`Hit Points Maximum (Base)`); fields with levels take `{"1": value, "3": value}`; list values for text fields are joined with commas.
- Error codes: `bad_op`, `not_found`, `id_taken`, `ids_exhausted`, `bad_value` (details `path`), `unknown_field`, `ambiguous_field` (details `candidates`), `field_not_applicable`; every error carries `op_index`.

- [ ] **Step 1: Write the failing test**

Append to `tests/ops/test_objdata.py`:
```python
from wc3mcp.formats import objmods
from wc3mcp.ops.objdata import objdata_edit
from wc3mcp.ops.strings import load_strings


def test_create_custom_unit_writes_main_and_skin_files(plain_project, catalog):
    result = objdata_edit(plain_project, catalog, "unit", [
        {"op": "create", "base": "hfoo", "set": {"Name": "Arena Guard", "HP": 777}}])
    assert result == {"changed": True, "created": ["h000"], "warnings": []}
    main = objmods.parse(plain_project.read("war3map.w3u"), False)
    skin = objmods.parse(plain_project.read("war3mapSkin.w3u"), False)
    assert [(e.base_id, e.new_id) for e in main.custom] == [(b"hfoo", b"h000")]
    assert [(e.base_id, e.new_id) for e in skin.custom] == [(b"hfoo", b"h000")]
    assert [(m.id, m.value, m.end) for m in main.custom[0].mods] == [(b"uhpm", 777, objmods.ZERO_ID)]
    assert [(m.id, m.value) for m in skin.custom[0].mods] == [(b"unam", "Arena Guard")]
    doc = objdata_get(plain_project, catalog, "unit", "h000", fields=["uhpm", "unam"])
    assert doc["custom"] and doc["name"] == "Arena Guard" and doc["fields"]["uhpm"]["value"] == 777


def test_create_ability_with_level_values(plain_project, catalog):
    result = objdata_edit(plain_project, catalog, "ability", [
        {"op": "create", "base": "AHbz", "set": {"Hbz1": {"1": 7, "3": 12}}}])
    assert result["created"] == ["A000"]
    mods = objmods.parse(plain_project.read("war3map.w3a"), True).custom[0].mods
    assert [(m.id, m.level, m.pointer, m.value) for m in mods] == [(b"Hbz1", 1, 1, 7), (b"Hbz1", 3, 1, 12)]
    doc = objdata_get(plain_project, catalog, "ability", "A000", fields=["Hbz1"])
    assert doc["fields"]["Hbz1"]["values"] == [7, 8, 12] and doc["fields"]["Hbz1"]["modified"] == [1, 3]


def test_modify_reset_and_delete(project, catalog):
    objdata_edit(project, catalog, "unit", [{"op": "set", "id": "nzep", "set": {"uhpm": 999}}])
    assert objdata_get(project, catalog, "unit", "nzep", fields=["uhpm"])["fields"]["uhpm"]["value"] == 999
    objdata_edit(project, catalog, "unit", [{"op": "reset", "id": "nzep", "fields": ["uhpm"]}])
    assert objdata_get(project, catalog, "unit", "nzep", fields=["uhpm"])["fields"]["uhpm"]["modified"] is False
    objdata_edit(project, catalog, "unit", [{"op": "delete", "id": "nC01"}])
    assert "nC01" not in {o["id"] for o in objdata_list(project, catalog, "unit")["objects"]}


def test_updating_an_existing_modification_keeps_its_record(project, catalog):
    def uhpm_mod():
        main = objmods.parse(project.read("war3map.w3u"), False)
        return next(m for e in main.original if e.base_id == b"hmtt" for m in e.mods if m.id == b"uhpm")

    before = uhpm_mod()
    objdata_edit(project, catalog, "unit", [{"op": "set", "id": "hmtt", "set": {"uhpm": 1100}}])
    after = uhpm_mod()
    assert after.value == 1100 and after.end == before.end


def test_setting_trigstr_backed_text_updates_the_string_table(plain_project, catalog):
    objdata_edit(plain_project, catalog, "unit", [{"op": "create", "base": "hfoo", "set": {"Name": "placeholder"}}])
    skin = objmods.parse(plain_project.read("war3mapSkin.w3u"), False)
    skin.custom[0].mods[0].value = "TRIGSTR_900"
    plain_project.write("war3mapSkin.w3u", objmods.serialize(skin))
    strings = load_strings(plain_project)
    strings.set(900, "Old Name")
    plain_project.write("war3map.wts", strings.serialize())
    assert objdata_get(plain_project, catalog, "unit", "h000")["name"] == "Old Name"
    objdata_edit(plain_project, catalog, "unit", [{"op": "set", "id": "h000", "set": {"Name": "New Name"}}])
    assert load_strings(plain_project).get(900) == "New Name"
    assert objmods.parse(plain_project.read("war3mapSkin.w3u"), False).custom[0].mods[0].value == "TRIGSTR_900"


@pytest.mark.parametrize("op, code", [
    ({"op": "create", "base": "zzzz"}, "not_found"),
    ({"op": "create", "base": "hfoo", "id": "hfoo"}, "id_taken"),
    ({"op": "create", "base": "hfoo", "id": "toolong"}, "bad_value"),
    ({"op": "set", "id": "hfoo", "set": {"no such field": 1}}, "unknown_field"),
    ({"op": "set", "id": "hfoo", "set": {"uhpm": "many"}}, "bad_value"),
    ({"op": "set", "id": "hfoo", "set": {"uhpm": {"1": 5}}}, "bad_value"),
    ({"op": "set", "id": "zzzz", "set": {"uhpm": 5}}, "not_found"),
    ({"op": "explode", "id": "hfoo"}, "bad_op"),
])
def test_edit_errors(plain_project, catalog, op, code):
    with pytest.raises(ToolError) as e:
        objdata_edit(plain_project, catalog, "unit", [op])
    assert e.value.code == code and e.value.details["op_index"] == 0


def test_ambiguous_field_and_atomic_batch(plain_project, catalog):
    with pytest.raises(ToolError) as e:
        objdata_edit(plain_project, catalog, "ability", [
            {"op": "create", "base": "AHbz", "set": {"Hbz1": {"1": 7}}},
            {"op": "set", "id": "AHbz", "set": {"Data": {"1": 1}}}])
    assert e.value.code == "ambiguous_field" and e.value.details["op_index"] == 1
    assert plain_project.status()["dirty"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& $PY -m pytest tests/ops/test_objdata.py -q`
Expected: FAIL with `ImportError: cannot import name 'objdata_edit' from 'wc3mcp.ops.objdata'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/wc3mcp/ops/objdata.py`:
```python
# ---- edits -----------------------------------------------------------------------------------------------------
ID_PREFIX = {"item": "I", "destructible": "B", "doodad": "D", "ability": "A", "buff": "B", "upgrade": "R"}
ID_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
SKIN_NETSAFE = frozenset({"1", "11"})
_HINT = ('ops: {"op": "create", "base": "hfoo", "set": {"Name": "Guard"}}, {"op": "set", "id": "h000", "set": '
         '{"uhpm": 500}}, {"op": "reset", "id": "h000", "fields": ["uhpm"]}, {"op": "delete", "id": "h000"}')


def _next_id(kind: str, base: str, taken: set[str]) -> str:
    prefix = base[0] if kind == "unit" else ID_PREFIX[kind]
    for n in range(36 ** 3):
        candidate = prefix + ID_ALPHABET[n // 1296] + ID_ALPHABET[n // 36 % 36] + ID_ALPHABET[n % 36]
        if candidate not in taken:
            return candidate
    raise ToolError("ids_exhausted", f"no free {kind} id with prefix {prefix!r}")


def _field(catalog, kind: str, base: str, key, path: str):
    fields = catalog.fields(kind)
    meta = next((f for f in fields if f.id == key), None)
    if meta is None:
        lowered = key.lower() if isinstance(key, str) else None
        candidates = [f for f in fields if lowered in (f.field.lower(), f.display_name.lower())
                      and catalog.applies(kind, base, f)]
        if len(candidates) > 1:
            raise ToolError("ambiguous_field", f"{path}: {key!r} matches several fields", hint="use the raw code",
                            candidates=[f"{f.id} ({f.display_name})" for f in candidates][:20])
        if not candidates:
            raise ToolError("unknown_field", f"{path}: no {kind} field {key!r}",
                            hint="objdata_get or data_get lists raw codes and field names")
        meta = candidates[0]
    if not catalog.applies(kind, base, meta):
        raise ToolError("field_not_applicable", f"{path}: field {meta.id} does not apply to {base}")
    return meta


def _number(text: str) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _convert(meta, value, path: str) -> tuple[int, object]:
    vt = var_type(meta.type)
    if vt == STRING:
        if isinstance(value, list) and all(isinstance(v, str) for v in value):
            value = ",".join(value)
        if not isinstance(value, str):
            raise ToolError("bad_value", f"{path}: {meta.id} expects text", path=path)
        return vt, value
    if isinstance(value, bool):
        value = int(value)
    if vt == INT and isinstance(value, float) and value.is_integer():
        value = int(value)
    if (vt == INT and not isinstance(value, int)) or (vt != INT and not isinstance(value, (int, float))):
        raise ToolError("bad_value", f"{path}: {meta.id} expects {'an integer' if vt == INT else 'a number'}",
                        path=path)
    low, high = _number(meta.min), _number(meta.max)
    if (low is not None and value < low) or (high is not None and value > high):
        raise ToolError("bad_value", f"{path}: {meta.id} must be between {meta.min} and {meta.max}", path=path)
    return vt, value if vt == INT else float(value)


def _level_values(meta, value, path: str) -> list[tuple[int, object]]:
    if meta.repeat > 0:
        if not isinstance(value, dict) or not value:
            raise ToolError("bad_value", f'{path}: {meta.id} has levels; give {{"1": value, "2": value}}', path=path)
        pairs = []
        for level, v in value.items():
            if not (isinstance(level, str) and level.isdigit() and int(level) >= 1):
                raise ToolError("bad_value", f"{path}: level keys must be numbers starting at 1", path=path)
            pairs.append((int(level), v))
        return pairs
    if isinstance(value, dict):
        raise ToolError("bad_value", f"{path}: {meta.id} has no levels", path=path)
    return [(0, value)]


def _entry_in(om: ObjectMods, custom: bool, base: bytes, new: bytes) -> ObjectEntry:
    table, key = (om.custom, new) if custom else (om.original, base)
    for entry in table:
        if (entry.new_id if custom else entry.base_id) == key:
            return entry
    entry = ObjectEntry(base, new if custom else objmods.ZERO_ID)
    table.append(entry)
    return entry


def _set(files, kind: str, custom: bool, base: bytes, new: bytes, meta, level: int, vt: int, value,
         strings: TriggerStrings) -> None:
    rid = meta.id.encode("latin-1")
    levels = EXTENSIONS[kind] in LEVEL_EXTENSIONS
    level = level if levels else 0
    for om in files:  # update an existing record wherever it lives (older maps keep skin fields in the main file)
        for mod in _entry_in(om, custom, base, new).mods:
            if mod.id == rid and mod.level == level:
                m = TRIGSTR.match(mod.value) if vt == STRING and isinstance(mod.value, str) else None
                if m:
                    strings.set(int(m.group(1)), value)
                else:
                    mod.var_type, mod.value = vt, value
                return
    target = files[1] if meta.netsafe in SKIN_NETSAFE else files[0]
    _entry_in(target, custom, base, new).mods.append(
        Mod(rid, vt, value, level, meta.data if levels else 0, objmods.ZERO_ID if custom else base))


def _set_many(files, catalog, kind: str, custom: bool, base: bytes, new: bytes, values, strings, path: str) -> None:
    if not isinstance(values, dict):
        raise ToolError("bad_op", f"{path}: set must be an object of field: value", hint=_HINT)
    for key, value in values.items():
        fpath = f"{path}.set.{key}"
        meta = _field(catalog, kind, base.decode("latin-1"), key, fpath)
        for level, v in _level_values(meta, value, fpath):
            vt, converted = _convert(meta, v, fpath)
            _set(files, kind, custom, base, new, meta, level, vt, converted, strings)


def _locate(files, base_ids: set[str], kind: str, obj_id, path: str) -> tuple[bool, bytes, bytes]:
    if not isinstance(obj_id, str):
        raise ToolError("bad_op", f"{path}: id must be a string", hint=_HINT)
    entries = _entries(files, obj_id)
    if entries:
        _, custom, entry = entries[0]
        return custom, entry.base_id, entry.new_id if custom else objmods.ZERO_ID
    if obj_id in base_ids:
        return False, obj_id.encode("latin-1"), objmods.ZERO_ID
    raise ToolError("not_found", f"{path}: no {kind} {obj_id!r} in this map or the game data",
                    hint="objdata_list shows map objects; data_search finds base objects")


def _remove(files, custom: bool, key: bytes) -> None:
    for om in files:
        if custom:
            om.custom = [e for e in om.custom if e.new_id != key]
        else:
            om.original = [e for e in om.original if e.base_id != key]


def objdata_edit(project, catalog, kind: str, ops: list) -> dict:
    main, skin, raw = _load(project, kind)
    files = (main, skin)
    strings = load_strings(project)
    wts_before = strings.serialize()
    base_ids = set(catalog.ids(kind))
    taken = base_ids | {_key(e, True) for om in files for e in om.custom}
    created = []
    for i, op in enumerate(ops):
        path = f"ops[{i}]"
        try:
            if not isinstance(op, dict):
                raise ToolError("bad_op", f"{path}: each op must be an object", hint=_HINT)
            action = op.get("op")
            if action == "create":
                base = op.get("base")
                if not isinstance(base, str) or base not in base_ids:
                    raise ToolError("not_found", f"{path}: base {kind} {base!r} does not exist",
                                    hint="data_search finds base object ids")
                new = op.get("id")
                if new is None:
                    new = _next_id(kind, base, taken)
                elif not (isinstance(new, str) and len(new) == 4 and all(33 <= ord(c) < 127 for c in new)):
                    raise ToolError("bad_value", f"{path}: id must be 4 printable ASCII characters", path=f"{path}.id")
                elif new in taken:
                    raise ToolError("id_taken", f"{path}: id {new!r} is already used", hint="omit id to allocate one")
                taken.add(new)
                created.append(new)
                base_b, new_b = base.encode("latin-1"), new.encode("latin-1")
                for om in files:  # the editor lists every object in both the main and the skin file
                    _entry_in(om, True, base_b, new_b)
                _set_many(files, catalog, kind, True, base_b, new_b, op.get("set", {}), strings, path)
            elif action == "set":
                custom, base_b, new_b = _locate(files, base_ids, kind, op.get("id"), path)
                for om in files:
                    _entry_in(om, custom, base_b, new_b)
                _set_many(files, catalog, kind, custom, base_b, new_b, op.get("set"), strings, path)
            elif action == "reset":
                custom, base_b, new_b = _locate(files, base_ids, kind, op.get("id"), path)
                keys = op.get("fields")
                if keys is None and not custom:
                    _remove(files, False, base_b)
                    continue
                if keys is not None and not (isinstance(keys, list) and all(isinstance(k, str) for k in keys)):
                    raise ToolError("bad_op", f"{path}: fields must be a list of field keys", hint=_HINT)
                rawcodes = None if keys is None else {
                    _field(catalog, kind, base_b.decode("latin-1"), k, f"{path}.fields[{j}]").id.encode("latin-1")
                    for j, k in enumerate(keys)}
                for _, is_custom, entry in _entries(files, op["id"]):
                    entry.mods = [m for m in entry.mods if rawcodes is not None and m.id not in rawcodes]
            elif action == "delete":
                custom, base_b, new_b = _locate(files, base_ids, kind, op.get("id"), path)
                _remove(files, custom, new_b if custom else base_b)
            else:
                raise ToolError("bad_op", f"{path}: unknown op {action!r}", hint=_HINT)
        except ToolError as e:
            e.details.setdefault("op_index", i)
            raise
    try:
        payloads = [(name, objmods.serialize(om)) for om, name in zip(files, raw)
                    if raw[name] is not None or om.original or om.custom]
    except (FormatError, struct.error) as e:
        raise ToolError("bad_value", f"cannot encode object data: {e}", path="") from e
    changed = False
    for name, data in payloads:
        if data != raw[name]:
            project.write(name, data)
            changed = True
    wts_after = strings.serialize()
    if wts_after != wts_before:
        project.write("war3map.wts", wts_after)
        changed = True
    return {"changed": changed, "created": created, "warnings": []}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `& $PY -m pytest tests/ops/test_objdata.py -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/wc3mcp/ops/objdata.py tests/ops/test_objdata.py
git commit -m "feat(ops): atomic object data edits with id allocation and skin-file placement" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

### Task 5: Server tools and full verification

**Files:**
- Modify: `src/wc3mcp/server.py` (import + three tools), `tests/test_server.py` (`EXPECTED` + new test)

**Interfaces:**
- Consumes: Task 3 `objdata_list`, `objdata_get`; Task 4 `objdata_edit`; Phase 1 `_tool`, `_project`, `_catalog`.
- Produces: MCP tools `objdata_list(path, kind, custom_only=False, balance="Custom_V1")`, `objdata_get(path, kind, id, fields=None, balance="Custom_V1")`, `objdata_edit(path, kind, ops, balance="Custom_V1")`.

- [ ] **Step 1: Write the failing test**

In `tests/test_server.py`, extend `EXPECTED`:
```python
EXPECTED = {"map_open", "map_close", "map_save", "map_status", "map_file_read", "map_file_write", "map_snapshot",
            "data_search", "data_get", "data_file", "info_get", "info_edit", "imports_edit",
            "objdata_list", "objdata_get", "objdata_edit"}
```

Append to `tests/test_server.py`:
```python
@needs_install
def test_object_data_tools(tmp_path):
    maps = ladder_maps()
    if not maps:
        pytest.skip("no ladder maps in Documents")
    src = tmp_path / maps[0].name
    src.write_bytes(maps[0].read_bytes())
    path = str(src)
    payload(call("map_open", {"path": path}))
    created = payload(call("objdata_edit", {"path": path, "kind": "unit", "balance": None, "ops": [
        {"op": "create", "base": "hfoo", "set": {"Name": "Tool Guard", "HP": 555}}]}))["created"]
    assert created == ["h000"]
    doc = payload(call("objdata_get", {"path": path, "kind": "unit", "id": "h000", "fields": ["uhpm"],
                                       "balance": None}))
    assert doc["fields"]["uhpm"]["value"] == 555 and doc["name"] == "Tool Guard"
    listed = payload(call("objdata_list", {"path": path, "kind": "unit", "custom_only": True, "balance": None}))
    assert [o["id"] for o in listed["objects"]] == ["h000"]
    err = call("objdata_edit", {"path": path, "kind": "unit", "balance": None,
                                "ops": [{"op": "set", "id": "h000", "set": {"nope": 1}}]})
    assert err.isError and json.loads(err.content[0].text.split(": ", 1)[1])["code"] == "unknown_field"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& $PY -m pytest tests/test_server.py -q`
Expected: FAIL in `test_tools_are_registered`, `test_stdio_server_starts` (missing names) and `test_object_data_tools` (unknown tool)

- [ ] **Step 3: Write minimal implementation**

In `src/wc3mcp/server.py`, add to the local imports:
```python
from .ops import objdata as objdata_ops
```

Add after the `Kind = Literal[...]` definition:
```python
ObjectKind = Literal["unit", "item", "destructible", "doodad", "ability", "buff", "upgrade"]
```

Add these tools after `imports_edit`:
```python
@_tool
def objdata_list(path: str, kind: ObjectKind, custom_only: bool = False, balance: str | None = "Custom_V1") -> dict:
    """Custom and modified objects of one kind in an open map (the Object Editor's left pane): id, base id,
    custom flag, number of modifications and display name."""
    return objdata_ops.objdata_list(_project(path), _catalog("enUS", balance, True), kind, custom_only)


@_tool
def objdata_get(path: str, kind: ObjectKind, id: str, fields: list[str] | None = None,
                balance: str | None = "Custom_V1") -> dict:
    """One object as the Object Editor shows it: base game values merged with this map's modifications. Each field
    has raw code, name, type, value (or per-level values) and whether the map modifies it. fields filters by raw code,
    field name or display-name substring."""
    return objdata_ops.objdata_get(_project(path), _catalog("enUS", balance, True), kind, id, fields)


@_tool
def objdata_edit(path: str, kind: ObjectKind, ops: list[dict], balance: str | None = "Custom_V1") -> dict:
    """Create and change objects with an all-or-nothing batch: {"op": "create", "base": "hfoo", "set": {"Name":
    "Guard", "HP": 500}} (id optional, allocated like the editor), {"op": "set", "id": "h000", "set": {"Hbz1":
    {"1": 7, "2": 9}}} (per-level fields take level keys), {"op": "reset", "id": "h000", "fields": ["uhpm"]},
    {"op": "delete", "id": "h000"}. Fields accept raw codes, field names or display names."""
    return objdata_ops.objdata_edit(_project(path), _catalog("enUS", balance, True), kind, ops)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& $PY -m pytest tests/test_server.py -q`
Expected: 7 passed

Run: `& $PY -m pytest -q`
Expected: every test passes

- [ ] **Step 5: Commit**

```bash
git add src/wc3mcp/server.py tests/test_server.py
git commit -m "feat(server): objdata_list, objdata_get and objdata_edit tools" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```