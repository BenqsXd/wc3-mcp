# Phase 2a — Strings, Map Info, Imports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Typed, lossless editing of map strings (`war3map.wts`), map info (`war3map.w3i`, versions 31/33/39) and the import list (`war3map.imp`), exposed as MCP tools `info_get`, `info_edit`, `imports_edit`.

**Architecture:** Byte-exact codecs in `wc3mcp.formats` (lossless text parser for wts; binary codecs for w3i and imp on shared `Reader`/`Writer` helpers), a generic JSON batch-edit engine in `wc3mcp.ops.edits`, and ops modules that convert codecs to editable JSON (TRIGSTR text resolved through wts) and back atomically on a `MapProject`.

**Tech Stack:** Python 3.13.14 (Microsoft Store interpreter), stdlib, `mcp 1.27.0` (FastMCP), `pytest 9.0.3`.

**Spec:** `docs/superpowers/specs/2026-09-14-wc3-mcp-design.md` (build-order item 2, split into 2a strings/info/imports, 2b object data, 2c triggers, 2d script build/validate). Builds on `docs/superpowers/plans/2026-09-14-phase1-foundation.md`.

## Global Constraints

- Interpreter by full path: `%LOCALAPPDATA%\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\python.exe` (written `$PY`; in PowerShell set `$PY = "<that path>"`). Run tests from `D:\Warcraft III\wc3-mcp`: `& $PY -m pytest <args>`.
- Branch: `phase2a-map-info` (stacked on `phase1-foundation`; PR #1 not merged yet).
- No new dependencies. Never write under the game install. Corpus tests read local data at runtime and skip when missing.
- Codecs are byte-exact on every local sample; `info_edit` refuses to write w3i format versions other than 31, 33, 39 (`WRITABLE_VERSIONS`).
- Every `*_edit` batch is atomic: validate everything first, then write; errors are `ToolError` with `code`, `message`, `hint`, and `op_index` or `path` details.
- Commit messages end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`; repo-local git email is the GitHub noreply address (already configured).
- Not in 2a: object data, triggers, script generation/validation, campaign scope (`scope: campaign` arrives with Phase 5), creating maps from scratch.

## Verified facts this plan relies on (probed 2026-09-14 on 556 local maps)

- **w3i v31** (368 maps) and **v33** (2 maps) parse byte-exactly with the War3Net layout (`Serialization/Binary/Info/MapInfo.cs`): header → strings → camera bounds (8 f32) + complements (4 i32) → playable width/height → flags (u32) → tileset (u8) → loading screen background (i32), model, text, title, subtitle → game data set (i32) → prologue path/text/title/subtitle → fog style (i32), start z, end z, density (f32), fog color (4 bytes BGRA) → global weather (4 bytes) → sound environment (string) → light environment (u8) → water tint (4 bytes BGRA) → script language (i32, v28+) → supported modes, game data version (v31+) → default + max camera zoom (v32+) → min camera zoom (v33+) → players → forces → upgrades → tech → random unit tables → random item tables. Game version (4 i32) exists from v27. Players: id, controller, race, flags, name, start x/y (f32), ally low/high (u32), enemy low/high (u32, v31+). A single byte 255 in place of the upgrade count marks a truncated (protected) file.
- **w3i v39** (186 maps, game 2.0.4 / 3.0 data) parses byte-exactly with these additions, derived empirically: one i32 after the loading screen background number; six 4-byte values after global weather (typically 0, 10000.0f, 10000.0f, 1.0f, 0, 0 — likely the 2.0 fog settings: Height Start/End, Linear Start/End, Max Opacity, Draw Fog Over Sky; order unverified); ten i32 after the camera zooms (observed `(0,100,10,0,10|50,20,100,0,100,-1)`); and a player whose flags include `0x40` carries one extra i32 after its flags (observed 1 or 0). Rules "never extra" and "always extra" fail (132/186 and 182/186); "flags & 0x40" is exact on 186/186.
- Map flag bits (War3Net `MapFlags`): 0 hide minimap in preview, 1 modify ally priorities, 2 melee map, 3 playable map size was large, 4 masked areas partially visible, 5 fixed player settings for custom forces, 6 use custom forces, 7 use custom techtree, 8 use custom abilities, 9 use custom upgrades, 10 map properties menu opened, 11 water waves on cliff shores, 12 water waves on rolling shores, 13 terrain fog, 14 requires expansion, 15 item classification system, 16 water tinting, 17 accurate probability, 18 custom ability skin, 19 disable deny icon, 20 force default camera zoom, 21 force max camera zoom, 22 force min camera zoom. Player flags: 0x1 fixed start position, 0x2 race selectable. Force flags: 0x1 allied, 0x2 allied victory, 0x4 share vision, 0x10 share unit control, 0x20 share advanced unit control. Controllers 1 user, 2 computer, 3 neutral, 4 rescuable; races 1 human, 2 orc, 3 undead, 4 night elf; upgrade availability 0 unavailable, 1 available, 2 researched; script language 0 JASS, 1 Lua; random table position types 0 unit, 1 building, 2 item.
- **wts**: 7,327 local files (map + `_Locales\*` overrides) round-trip byte-exactly with a lossless line parser. Real files contain UTF-8 BOM (`EF BB BF`), a double-encoded BOM (`C3 AF C2 BB C2 BF`) in some locale files, CRLF (some LF), blank lines before the first block, extra blank lines between blocks, non-comment lines between `STRING n` and `{`, and duplicate ids with identical text.
- **imp v1**: u32 version (1), u32 count, then per entry u8 flag + NUL-terminated path. Paths use `/` and are stored as written (no implicit `war3mapImported\` prefix in modern maps). Flags seen: 0, 1, 13, 16, 17, 21, 24, 25, 29; `war3mapImported/` files in v39 maps use 21 (536) or 29 (542). Bit meanings are undocumented (War3Net `UNK1..UNK16`); new imports use 29.

## File Structure

```
src/wc3mcp/formats/__init__.py
src/wc3mcp/formats/wts.py        TriggerStrings (lossless), TRIGSTR regex
src/wc3mcp/formats/binary.py     Reader, Writer, FormatError
src/wc3mcp/formats/imp.py        ImportList codec
src/wc3mcp/formats/w3i.py        MapInfo codec (v25-v39 read, byte-exact on 31/33/39)
src/wc3mcp/ops/__init__.py
src/wc3mcp/ops/edits.py          apply_ops: set / append / remove on JSON paths
src/wc3mcp/ops/info.py           info_get / info_edit (w3i <-> JSON, TRIGSTR via wts)
src/wc3mcp/ops/imports.py        imports_list / imports_edit
src/wc3mcp/server.py             + info_get, info_edit, imports_edit tools
tests/corpus.py                  + sample_map_ids(), open_sample()
tests/formats/test_wts.py  tests/formats/test_imp.py  tests/formats/test_w3i.py
tests/ops/test_edits.py    tests/ops/test_info.py     tests/ops/test_imports.py
tests/test_server.py             + info/import tool test
```

---

### Task 1: Sample maps for corpus tests + lossless trigger strings

**Files:**
- Modify: `tests/corpus.py` (append helpers)
- Create: `src/wc3mcp/formats/__init__.py`, `src/wc3mcp/formats/wts.py`
- Test: `tests/formats/test_wts.py`

**Interfaces:**
- Consumes: Phase 1 `wc3mcp.casc.storage.open_storage`, `wc3mcp.mpq.reader.Archive`, `tests/corpus.py` (`INSTALL`, `HAVE_INSTALL`, `ladder_maps`).
- Produces: `corpus.CASC_SAMPLE_MAPS: tuple[str, ...]`, `corpus.sample_map_ids() -> list[str]` (`"ladder:<file name>"`, `"casc:<path>"`), `corpus.open_sample(map_id) -> Archive` (cached); `wts.TRIGSTR` (compiled regex, group 1 = id); `wts.Entry(id, lead, header, comments, opening, body, closing)`; `wts.TriggerStrings(entries=[], tail="", newline="\r\n")` with `parse(data: bytes)` (classmethod), `serialize() -> bytes`, `get(id) -> str | None`, `set(id, text) -> None`, `add(text, id=None) -> int`, `remove(id) -> int`, `resolve(value: str) -> str`.

- [ ] **Step 1: Add sample-map helpers**

In `tests/corpus.py`, add `import functools` to the imports at the top of the file, then append:
```python
CASC_SAMPLE_MAPS = (
    "Campaign/Reforged/ROC/Human01.w3x",            # w3i v39, many imports, locale strings
    "Campaign/Classic/ROC/Undead02Interlude.w3m",   # w3i v39
    "Campaign/Classic/TFT/HumanX01.w3x",            # w3i v39 players with flag 0x40
    "Campaign/Reforged/ROC/Prologue01.w3x",         # w3i v39
    "Maps/Scenario/(4)WarChasers.w3m",              # w3i v33, JASS
    "Maps/FrozenThrone/Community/2023Season2/(8)RoyalGardens_S2_v1.2.w3x",  # w3i v33, Lua
    "Maps/FrozenThrone/(10)RagingStream.w3x",       # w3i v31
    "Campaign/Classic/TFT/HumanX04Interlude.w3x",   # w3i v31, object data v2
)


@functools.cache
def _storage():
    from wc3mcp.casc.storage import open_storage

    return open_storage(INSTALL)


@functools.cache
def _ladder_by_name() -> dict:
    return {p.name: p for p in ladder_maps()}


def sample_map_ids() -> list[str]:
    ids = [f"ladder:{name}" for name in _ladder_by_name()]
    if HAVE_INSTALL:
        ids += [f"casc:{m}" for m in CASC_SAMPLE_MAPS]
    return ids


@functools.cache
def open_sample(map_id: str):
    from wc3mcp.mpq.reader import Archive

    kind, name = map_id.split(":", 1)
    if kind == "casc":
        return Archive(_storage().read("War3.w3mod:" + name))
    return Archive.open(_ladder_by_name()[name])
```

- [ ] **Step 2: Write the failing test**

`tests/formats/test_wts.py`:
```python
import pytest

from corpus import open_sample, sample_map_ids
from wc3mcp.formats.wts import TriggerStrings

SAMPLE = ("\ufeffSTRING 1\r\n{\r\nHammerfall\r\n}\r\n\r\n"
          "STRING 2\r\n// Units: hfoo\r\n{\r\nline one\r\nline two\r\n}\r\n\r\n").encode("utf-8")


def test_lossless_parse_get_resolve():
    ts = TriggerStrings.parse(SAMPLE)
    assert ts.serialize() == SAMPLE
    assert ts.get(1) == "Hammerfall" and ts.get(2) == "line one\nline two" and ts.get(3) is None
    assert ts.resolve("TRIGSTR_002") == "line one\nline two"
    assert ts.resolve("plain") == "plain" and ts.resolve("TRIGSTR_9") == "TRIGSTR_9"


def test_set_add_remove_keep_file_style():
    ts = TriggerStrings.parse(SAMPLE)
    ts.set(1, "New Name")
    assert ts.add("Added\ntext") == 3
    assert ts.remove(2) == 1
    assert ts.serialize() == ("\ufeffSTRING 1\r\n{\r\nNew Name\r\n}\r\n"
                              "\r\nSTRING 3\r\n{\r\nAdded\r\ntext\r\n}\r\n\r\n").encode("utf-8")


def test_double_encoded_bom_and_lf_files():
    data = "\u00ef\u00bb\u00bfSTRING 0\n{\nPlayer 1\n}\n".encode("utf-8")
    ts = TriggerStrings.parse(data)
    assert ts.get(0) == "Player 1" and ts.newline == "\n" and ts.serialize() == data
    ts.add("Force 1")
    assert ts.serialize().endswith(b"\nSTRING 1\n{\nForce 1\n}\n")


def test_empty_file_gets_bom_on_first_add():
    ts = TriggerStrings.parse(b"")
    assert ts.add("Hello") == 1
    assert ts.serialize() == "\ufeffSTRING 1\r\n{\r\nHello\r\n}\r\n".encode("utf-8")


def test_set_missing_id_adds_it_and_empty_text():
    ts = TriggerStrings.parse(SAMPLE)
    ts.set(10, "")
    assert ts.get(10) == ""
    assert TriggerStrings.parse(ts.serialize()).get(10) == ""


@pytest.mark.parametrize("map_id", sample_map_ids())
def test_corpus_roundtrip(map_id):
    arc = open_sample(map_id)
    names = [n for n in arc.list() if n.lower().endswith(".wts")]
    assert names
    for name in names:
        data = arc.read(name)
        ts = TriggerStrings.parse(data)
        assert ts.serialize() == data, name
        assert all(ts.get(e.id) is not None for e in ts.entries)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `& $PY -m pytest tests/formats/test_wts.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'wc3mcp.formats'`

- [ ] **Step 4: Write minimal implementation**

`src/wc3mcp/formats/__init__.py`:
```python
"""Byte-exact codecs for Warcraft III map files."""
```

`src/wc3mcp/formats/wts.py`:
```python
"""war3map.wts — trigger strings. Parsed losslessly: everything outside the string bodies is kept verbatim."""
import re
from dataclasses import dataclass, field

_HEADER = re.compile(r"^(?:\ufeff|\u00ef\u00bb\u00bf)?STRING\s+(-?\d+)\s*$")  # plain or double-encoded BOM
TRIGSTR = re.compile(r"^TRIGSTR_(-?\d+)$")


@dataclass
class Entry:
    id: int
    lead: str            # text before the STRING line (blank lines, BOM, stray lines)
    header: str          # the STRING line including its line ending
    comments: list[str]  # lines between the STRING line and "{"
    opening: str         # the "{" line
    body: str            # raw lines between the braces, including their line endings
    closing: str         # the "}" line ("" if the file ended early)


def _text(body: str) -> str:
    for nl in ("\r\n", "\n", "\r"):
        if body.endswith(nl):
            body = body[:-len(nl)]
            break
    return body.replace("\r\n", "\n")


@dataclass
class TriggerStrings:
    entries: list[Entry] = field(default_factory=list)
    tail: str = ""
    newline: str = "\r\n"

    @classmethod
    def parse(cls, data: bytes) -> "TriggerStrings":
        text = data.decode("utf-8", "surrogateescape")
        lines = text.splitlines(keepends=True)
        ts = cls(newline="\n" if "\n" in text and "\r\n" not in text else "\r\n")
        lead, i = "", 0
        while i < len(lines):
            m = _HEADER.match(lines[i].rstrip("\r\n"))
            if not m:
                lead += lines[i]
                i += 1
                continue
            j = i + 1
            while j < len(lines) and not lines[j].rstrip("\r\n").startswith("{"):
                j += 1
            if j >= len(lines):  # no opening brace: keep the rest verbatim
                lead += "".join(lines[i:])
                break
            k = j + 1
            while k < len(lines) and lines[k].rstrip("\r\n") != "}":
                k += 1
            ts.entries.append(Entry(int(m.group(1)), lead, lines[i], lines[i + 1:j], lines[j],
                                    "".join(lines[j + 1:k]), lines[k] if k < len(lines) else ""))
            lead, i = "", k + 1
        ts.tail = lead
        return ts

    def serialize(self) -> bytes:
        text = "".join(e.lead + e.header + "".join(e.comments) + e.opening + e.body + e.closing
                       for e in self.entries) + self.tail
        return text.encode("utf-8", "surrogateescape")

    def get(self, sid: int) -> str | None:
        return next((_text(e.body) for e in self.entries if e.id == sid), None)

    def _body(self, text: str) -> str:
        return text.replace("\r\n", "\n").replace("\n", self.newline) + self.newline if text else ""

    def set(self, sid: int, text: str) -> None:
        hits = [e for e in self.entries if e.id == sid]
        if not hits:
            self.add(text, sid)
        for e in hits:  # duplicate ids occur in real files; keep them consistent
            e.body = self._body(text)

    def add(self, text: str, sid: int | None = None) -> int:
        if sid is None:
            sid = max((e.id for e in self.entries), default=0) + 1
        nl = self.newline
        if self.entries:
            lead = nl
        else:
            lead, self.tail = (self.tail or "\ufeff"), ""
        self.entries.append(Entry(sid, lead, f"STRING {sid}{nl}", [], "{" + nl, self._body(text), "}" + nl))
        return sid

    def remove(self, sid: int) -> int:
        before = len(self.entries)
        self.entries = [e for e in self.entries if e.id != sid]
        return before - len(self.entries)

    def resolve(self, value: str) -> str:
        m = TRIGSTR.match(value)
        if not m:
            return value
        text = self.get(int(m.group(1)))
        return value if text is None else text
```

- [ ] **Step 5: Run test to verify it passes**

Run: `& $PY -m pytest tests/formats/test_wts.py -q`
Expected: all passed (5 unit tests + one per sample map, ~138)

- [ ] **Step 6: Commit**

```bash
git add tests/corpus.py src/wc3mcp/formats/__init__.py src/wc3mcp/formats/wts.py tests/formats/test_wts.py
git commit -m "feat(formats): lossless trigger strings codec and sample-map corpus helpers" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

### Task 2: Binary helpers + import list codec

**Files:**
- Create: `src/wc3mcp/formats/binary.py`, `src/wc3mcp/formats/imp.py`
- Test: `tests/formats/test_imp.py`

**Interfaces:**
- Consumes: Task 1 `corpus.sample_map_ids`, `corpus.open_sample`.
- Produces: `binary.FormatError(ValueError)`; `binary.Reader(data)` with `.pos`, `i32() u32() f32() u8() raw(n) cstr() count(item_size=1) peek_u8() rest()`; `binary.Writer()` with `i32(v) u32(v) f32(v) u8(v) raw(b) cstr(s) getvalue() -> bytes`; `imp.DEFAULT_FLAG = 29`; `imp.ImportEntry(flag: int, path: str)`; `imp.ImportList(version=1, entries=[], trailing=b"")`; `imp.parse(data) -> ImportList`; `imp.serialize(ImportList) -> bytes`.

- [ ] **Step 1: Write the failing test**

`tests/formats/test_imp.py`:
```python
import pytest

from corpus import open_sample, sample_map_ids
from wc3mcp.formats import imp
from wc3mcp.formats.binary import FormatError


def test_build_serialize_parse():
    lst = imp.ImportList(1, [imp.ImportEntry(29, "war3mapImported/a.blp"), imp.ImportEntry(13, "conversation.json")])
    data = imp.serialize(lst)
    assert data == b"\x01\x00\x00\x00\x02\x00\x00\x00\x1dwar3mapImported/a.blp\x00\x0dconversation.json\x00"
    assert imp.parse(data) == lst


def test_rejects_bad_input():
    with pytest.raises(FormatError):
        imp.parse(b"\x01\x00\x00\x00\xff\xff\x00\x00")  # count larger than the data
    with pytest.raises(FormatError):
        imp.parse(b"\x01\x00\x00\x00\x01\x00\x00\x00\x1dno-terminator")
    with pytest.raises(FormatError):
        imp.parse(b"\x07\x00\x00\x00\x00\x00\x00\x00")  # unknown version


@pytest.mark.parametrize("map_id", sample_map_ids())
def test_corpus_roundtrip(map_id):
    data = open_sample(map_id).read("war3map.imp")
    if data is None:
        pytest.skip("map has no import list")
    lst = imp.parse(data)
    assert lst.trailing == b"" and imp.serialize(lst) == data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& $PY -m pytest tests/formats/test_imp.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'wc3mcp.formats.imp'`

- [ ] **Step 3: Write minimal implementation**

`src/wc3mcp/formats/binary.py`:
```python
"""Little-endian binary reading/writing shared by the map file codecs."""
import struct


class FormatError(ValueError):
    pass


class Reader:
    def __init__(self, data: bytes):
        self.data, self.pos = bytes(data), 0

    def _take(self, n: int) -> bytes:
        if n < 0 or self.pos + n > len(self.data):
            raise FormatError(f"unexpected end of data at offset {self.pos} (need {n} bytes)")
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def i32(self) -> int:
        return struct.unpack("<i", self._take(4))[0]

    def u32(self) -> int:
        return struct.unpack("<I", self._take(4))[0]

    def f32(self) -> float:
        return struct.unpack("<f", self._take(4))[0]

    def u8(self) -> int:
        return self._take(1)[0]

    def raw(self, n: int) -> bytes:
        return self._take(n)

    def cstr(self) -> str:
        end = self.data.find(b"\0", self.pos)
        if end < 0:
            raise FormatError(f"unterminated string at offset {self.pos}")
        value = self.data[self.pos:end].decode("utf-8", "surrogateescape")
        self.pos = end + 1
        return value

    def count(self, item_size: int = 1) -> int:
        """An i32 element count, rejected if its items could not fit in the remaining data."""
        n = self.i32()
        if n < 0 or n * item_size > len(self.data) - self.pos:
            raise FormatError(f"implausible count {n} at offset {self.pos - 4}")
        return n

    def peek_u8(self) -> int:
        return self.data[self.pos] if self.pos < len(self.data) else -1

    def rest(self) -> bytes:
        chunk = self.data[self.pos:]
        self.pos = len(self.data)
        return chunk


class Writer:
    def __init__(self):
        self.buf = bytearray()

    def i32(self, v: int) -> None:
        self.buf += struct.pack("<i", v)

    def u32(self, v: int) -> None:
        self.buf += struct.pack("<I", v)

    def f32(self, v: float) -> None:
        self.buf += struct.pack("<f", v)

    def u8(self, v: int) -> None:
        self.buf.append(v)

    def raw(self, b: bytes) -> None:
        self.buf += b

    def cstr(self, s: str) -> None:
        self.buf += s.encode("utf-8", "surrogateescape") + b"\0"

    def getvalue(self) -> bytes:
        return bytes(self.buf)
```

`src/wc3mcp/formats/imp.py`:
```python
"""war3map.imp — the editor's import list (files the World Editor keeps when saving)."""
from dataclasses import dataclass, field

from .binary import FormatError, Reader, Writer

DEFAULT_FLAG = 29  # most common flag in maps saved by the 2.x editor; bit meanings are undocumented


@dataclass
class ImportEntry:
    flag: int
    path: str  # as stored: '/' separators, no implicit prefix


@dataclass
class ImportList:
    version: int = 1
    entries: list[ImportEntry] = field(default_factory=list)
    trailing: bytes = b""


def parse(data: bytes) -> ImportList:
    r = Reader(data)
    version = r.i32()
    if version != 1:
        raise FormatError(f"unsupported import list version {version}")
    imports = ImportList(version)
    for _ in range(r.count(item_size=2)):
        imports.entries.append(ImportEntry(r.u8(), r.cstr()))
    imports.trailing = r.rest()
    return imports


def serialize(imports: ImportList) -> bytes:
    w = Writer()
    w.i32(imports.version)
    w.i32(len(imports.entries))
    for e in imports.entries:
        w.u8(e.flag)
        w.cstr(e.path)
    w.raw(imports.trailing)
    return w.getvalue()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `& $PY -m pytest tests/formats/test_imp.py -q`
Expected: 2 passed plus corpus cases (maps without an import list are skipped)

- [ ] **Step 5: Commit**

```bash
git add src/wc3mcp/formats/binary.py src/wc3mcp/formats/imp.py tests/formats/test_imp.py
git commit -m "feat(formats): binary reader/writer and import list codec" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

### Task 3: Map info codec (`war3map.w3i`)

**Files:**
- Create: `src/wc3mcp/formats/w3i.py`
- Test: `tests/formats/test_w3i.py`

**Interfaces:**
- Consumes: Task 2 `Reader`, `Writer`, `FormatError`; Task 1 corpus helpers.
- Produces: `w3i.WRITABLE_VERSIONS = frozenset({31, 33, 39})`; `w3i.PLAYER_FLAG_V39_EXTRA = 0x40`; dataclasses `Player(id, controller, race, flags, name, start_x, start_y, ally_low, ally_high, enemy_low=0, enemy_high=0, v39_value=1)`, `Force(flags, players, name)`, `UpgradeChange(players, id: bytes, level, availability)`, `TechChange(players, id: bytes)`, `RandomUnitTable(id, name, positions: list[int], lines: list[tuple[int, list[bytes]]])`, `RandomItemTable(id, name, sets: list[list[tuple[int, bytes]]])`, `MapInfo(version, ...)` with the fields shown below; `w3i.parse(data) -> MapInfo`; `w3i.serialize(MapInfo) -> bytes`. Player/force masks are u32 bit sets (bit n = player n); rawcodes are 4 raw bytes; colors are 4 bytes B, G, R, A.

- [ ] **Step 1: Write the failing test**

`tests/formats/test_w3i.py`:
```python
import pytest

from corpus import open_sample, sample_map_ids
from wc3mcp.formats import w3i
from wc3mcp.formats.binary import FormatError

HUMANX01 = "casc:Campaign/Classic/TFT/HumanX01.w3x"


def _sample_info() -> w3i.MapInfo:
    mi = w3i.MapInfo(39, map_version=3, editor_version=6127, game_version=[2, 0, 4, 23839], name="TRIGSTR_001",
                     camera_bounds=[-1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0], camera_complements=[1, 2, 3, 4],
                     playable_width=84, playable_height=84, flags=0x1C, script_language=1)
    mi.players.append(w3i.Player(0, 1, 2, 0x41, "TRIGSTR_002", 128.0, -256.0, 2, 0, 0, 1, v39_value=0))
    mi.forces.append(w3i.Force(0x3, 0xFFFFFFFF, "TRIGSTR_003"))
    mi.upgrades.append(w3i.UpgradeChange(1, b"Rhme", 0, 2))
    mi.tech.append(w3i.TechChange(3, b"hfoo"))
    mi.random_unit_tables.append(w3i.RandomUnitTable(0, "Group", [0, 2],
                                                     [(50, [b"hfoo", b"ratf"]), (50, [b"\0\0\0\0", b"ratc"])]))
    mi.random_item_tables.append(w3i.RandomItemTable(1, "Items", [[(100, b"ratf")], [(60, b"ckng"), (40, b"modt")]]))
    return mi


def test_constructed_info_roundtrip_v39_and_v31():
    mi = _sample_info()
    assert w3i.parse(w3i.serialize(mi)) == mi
    mi.version = 31
    mi.players[0].flags = 1
    mi.players[0].v39_value = 1
    assert w3i.parse(w3i.serialize(mi)) == mi


def test_rejects_unknown_versions_and_short_data():
    with pytest.raises(FormatError):
        w3i.parse((40).to_bytes(4, "little") + bytes(100))
    with pytest.raises(FormatError):
        w3i.parse((31).to_bytes(4, "little") + bytes(10))


def test_v39_player_flag_0x40_carries_extra_int():
    if HUMANX01 not in sample_map_ids():
        pytest.skip("Warcraft III install not found")
    info = w3i.parse(open_sample(HUMANX01).read("war3map.w3i"))
    assert info.version == 39
    assert any(p.flags & w3i.PLAYER_FLAG_V39_EXTRA for p in info.players)


@pytest.mark.parametrize("map_id", sample_map_ids())
def test_corpus_roundtrip_is_byte_exact(map_id):
    data = open_sample(map_id).read("war3map.w3i")
    info = w3i.parse(data)
    assert info.version in w3i.WRITABLE_VERSIONS
    assert info.trailing == b"" and not info.truncated
    assert w3i.serialize(info) == data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& $PY -m pytest tests/formats/test_w3i.py -q`
Expected: FAIL with `ImportError: cannot import name 'w3i' from 'wc3mcp.formats'`

- [ ] **Step 3: Write minimal implementation**

`src/wc3mcp/formats/w3i.py`:
```python
"""war3map.w3i — map info. Reads format versions 25-39; byte-exact on local v31/v33/v39 maps. The v39 additions
were derived from Warcraft III 3.0.0.24268 campaign maps; their meaning is not documented."""
from dataclasses import dataclass, field

from .binary import FormatError, Reader, Writer

WRITABLE_VERSIONS = frozenset({31, 33, 39})
PLAYER_FLAG_V39_EXTRA = 0x40  # v39: the player record has one extra i32 after its flags when this bit is set


@dataclass
class Player:
    id: int
    controller: int
    race: int
    flags: int
    name: str
    start_x: float
    start_y: float
    ally_low: int
    ally_high: int
    enemy_low: int = 0
    enemy_high: int = 0
    v39_value: int = 1


@dataclass
class Force:
    flags: int
    players: int
    name: str


@dataclass
class UpgradeChange:
    players: int
    id: bytes
    level: int
    availability: int


@dataclass
class TechChange:
    players: int
    id: bytes


@dataclass
class RandomUnitTable:
    id: int
    name: str
    positions: list[int]
    lines: list[tuple[int, list[bytes]]]


@dataclass
class RandomItemTable:
    id: int
    name: str
    sets: list[list[tuple[int, bytes]]]


@dataclass
class MapInfo:
    version: int
    map_version: int = 0
    editor_version: int = 0
    game_version: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
    name: str = ""
    author: str = ""
    description: str = ""
    players_recommended: str = ""
    camera_bounds: list[float] = field(default_factory=lambda: [0.0] * 8)
    camera_complements: list[int] = field(default_factory=lambda: [0] * 4)
    playable_width: int = 0
    playable_height: int = 0
    flags: int = 0
    tileset: int = ord("L")
    loading_screen_background: int = -1
    loading_screen_model: str = ""
    loading_screen_text: str = ""
    loading_screen_title: str = ""
    loading_screen_subtitle: str = ""
    game_data_set: int = 0
    prologue_path: str = ""
    prologue_text: str = ""
    prologue_title: str = ""
    prologue_subtitle: str = ""
    fog_style: int = 0
    fog_start_z: float = 0.0
    fog_end_z: float = 0.0
    fog_density: float = 0.0
    fog_color: bytes = b"\0\0\0\xff"
    global_weather: bytes = b"\0\0\0\0"
    sound_environment: str = ""
    light_environment: int = 0
    water_tint: bytes = b"\xff\xff\xff\xff"
    script_language: int = 0
    supported_modes: int = 3
    game_data_version: int = 1
    default_camera_zoom: int = 0
    max_camera_zoom: int = 0
    min_camera_zoom: int = 0
    v39_after_loading_background: int = 1
    v39_after_weather: list[int] = field(default_factory=lambda: [0, 0x461C4000, 0x461C4000, 0x3F800000, 0, 0])
    v39_after_zoom: list[int] = field(default_factory=lambda: [0, 100, 10, 0, 10, 20, 100, 0, 100, -1])
    players: list[Player] = field(default_factory=list)
    forces: list[Force] = field(default_factory=list)
    upgrades: list[UpgradeChange] = field(default_factory=list)
    tech: list[TechChange] = field(default_factory=list)
    random_unit_tables: list[RandomUnitTable] = field(default_factory=list)
    random_item_tables: list[RandomItemTable] = field(default_factory=list)
    truncated: bool = False  # protected maps end with byte 255 right after the forces
    trailing: bytes = b""


def parse(data: bytes) -> MapInfo:
    r = Reader(data)
    v = r.i32()
    if not 25 <= v <= 39:
        raise FormatError(f"unsupported w3i format version {v}")
    mi = MapInfo(v, map_version=r.i32(), editor_version=r.i32())
    if v >= 27:
        mi.game_version = [r.i32() for _ in range(4)]
    mi.name, mi.author, mi.description, mi.players_recommended = r.cstr(), r.cstr(), r.cstr(), r.cstr()
    mi.camera_bounds = [r.f32() for _ in range(8)]
    mi.camera_complements = [r.i32() for _ in range(4)]
    mi.playable_width, mi.playable_height, mi.flags, mi.tileset = r.i32(), r.i32(), r.u32(), r.u8()
    mi.loading_screen_background = r.i32()
    if v >= 39:
        mi.v39_after_loading_background = r.i32()
    mi.loading_screen_model, mi.loading_screen_text = r.cstr(), r.cstr()
    mi.loading_screen_title, mi.loading_screen_subtitle = r.cstr(), r.cstr()
    mi.game_data_set = r.i32()
    mi.prologue_path, mi.prologue_text, mi.prologue_title, mi.prologue_subtitle = r.cstr(), r.cstr(), r.cstr(), r.cstr()
    mi.fog_style, mi.fog_start_z, mi.fog_end_z, mi.fog_density = r.i32(), r.f32(), r.f32(), r.f32()
    mi.fog_color, mi.global_weather = r.raw(4), r.raw(4)
    if v >= 39:
        mi.v39_after_weather = [r.u32() for _ in range(6)]
    mi.sound_environment, mi.light_environment, mi.water_tint = r.cstr(), r.u8(), r.raw(4)
    if v >= 28:
        mi.script_language = r.i32()
    if v >= 31:
        mi.supported_modes, mi.game_data_version = r.i32(), r.i32()
    if v >= 32:
        mi.default_camera_zoom, mi.max_camera_zoom = r.i32(), r.i32()
    if v >= 33:
        mi.min_camera_zoom = r.i32()
    if v >= 39:
        mi.v39_after_zoom = [r.i32() for _ in range(10)]
    for _ in range(r.count(item_size=33)):
        p = Player(r.i32(), r.i32(), r.i32(), r.u32(), "", 0.0, 0.0, 0, 0)
        if v >= 39 and p.flags & PLAYER_FLAG_V39_EXTRA:
            p.v39_value = r.i32()
        p.name, p.start_x, p.start_y, p.ally_low, p.ally_high = r.cstr(), r.f32(), r.f32(), r.u32(), r.u32()
        if v >= 31:
            p.enemy_low, p.enemy_high = r.u32(), r.u32()
        mi.players.append(p)
    for _ in range(r.count(item_size=9)):
        mi.forces.append(Force(r.u32(), r.u32(), r.cstr()))
    if r.peek_u8() == 255:  # War3Net treats this as "skip the rest"
        r.u8()
        mi.truncated, mi.trailing = True, r.rest()
        return mi
    for _ in range(r.count(item_size=16)):
        mi.upgrades.append(UpgradeChange(r.u32(), r.raw(4), r.i32(), r.i32()))
    for _ in range(r.count(item_size=8)):
        mi.tech.append(TechChange(r.u32(), r.raw(4)))
    for _ in range(r.count(item_size=13)):
        tid, tname = r.i32(), r.cstr()
        positions = [r.i32() for _ in range(r.count(item_size=4))]
        lines = [(r.i32(), [r.raw(4) for _ in positions]) for _ in range(r.count(item_size=4 * (len(positions) + 1)))]
        mi.random_unit_tables.append(RandomUnitTable(tid, tname, positions, lines))
    for _ in range(r.count(item_size=9)):
        tid, tname = r.i32(), r.cstr()
        sets = [[(r.i32(), r.raw(4)) for _ in range(r.count(item_size=8))] for _ in range(r.count(item_size=4))]
        mi.random_item_tables.append(RandomItemTable(tid, tname, sets))
    if 26 <= v < 28:
        r.i32()  # always 0
    mi.trailing = r.rest()
    return mi


def _four(b: bytes, what: str) -> bytes:
    if len(b) != 4:
        raise FormatError(f"{what} must be exactly 4 bytes")
    return b


def serialize(mi: MapInfo) -> bytes:
    w, v = Writer(), mi.version
    w.i32(v)
    w.i32(mi.map_version)
    w.i32(mi.editor_version)
    if v >= 27:
        for x in mi.game_version:
            w.i32(x)
    for s in (mi.name, mi.author, mi.description, mi.players_recommended):
        w.cstr(s)
    for f in mi.camera_bounds:
        w.f32(f)
    for c in mi.camera_complements:
        w.i32(c)
    w.i32(mi.playable_width)
    w.i32(mi.playable_height)
    w.u32(mi.flags)
    w.u8(mi.tileset)
    w.i32(mi.loading_screen_background)
    if v >= 39:
        w.i32(mi.v39_after_loading_background)
    for s in (mi.loading_screen_model, mi.loading_screen_text, mi.loading_screen_title, mi.loading_screen_subtitle):
        w.cstr(s)
    w.i32(mi.game_data_set)
    for s in (mi.prologue_path, mi.prologue_text, mi.prologue_title, mi.prologue_subtitle):
        w.cstr(s)
    w.i32(mi.fog_style)
    w.f32(mi.fog_start_z)
    w.f32(mi.fog_end_z)
    w.f32(mi.fog_density)
    w.raw(_four(mi.fog_color, "fog color"))
    w.raw(_four(mi.global_weather, "global weather"))
    if v >= 39:
        for x in mi.v39_after_weather:
            w.u32(x)
    w.cstr(mi.sound_environment)
    w.u8(mi.light_environment)
    w.raw(_four(mi.water_tint, "water tint"))
    if v >= 28:
        w.i32(mi.script_language)
    if v >= 31:
        w.i32(mi.supported_modes)
        w.i32(mi.game_data_version)
    if v >= 32:
        w.i32(mi.default_camera_zoom)
        w.i32(mi.max_camera_zoom)
    if v >= 33:
        w.i32(mi.min_camera_zoom)
    if v >= 39:
        for x in mi.v39_after_zoom:
            w.i32(x)
    w.i32(len(mi.players))
    for p in mi.players:
        w.i32(p.id)
        w.i32(p.controller)
        w.i32(p.race)
        w.u32(p.flags)
        if v >= 39 and p.flags & PLAYER_FLAG_V39_EXTRA:
            w.i32(p.v39_value)
        w.cstr(p.name)
        w.f32(p.start_x)
        w.f32(p.start_y)
        w.u32(p.ally_low)
        w.u32(p.ally_high)
        if v >= 31:
            w.u32(p.enemy_low)
            w.u32(p.enemy_high)
    w.i32(len(mi.forces))
    for f in mi.forces:
        w.u32(f.flags)
        w.u32(f.players)
        w.cstr(f.name)
    if mi.truncated:
        w.u8(255)
        w.raw(mi.trailing)
        return w.getvalue()
    w.i32(len(mi.upgrades))
    for u in mi.upgrades:
        w.u32(u.players)
        w.raw(_four(u.id, "upgrade id"))
        w.i32(u.level)
        w.i32(u.availability)
    w.i32(len(mi.tech))
    for t in mi.tech:
        w.u32(t.players)
        w.raw(_four(t.id, "tech id"))
    w.i32(len(mi.random_unit_tables))
    for table in mi.random_unit_tables:
        w.i32(table.id)
        w.cstr(table.name)
        w.i32(len(table.positions))
        for pos in table.positions:
            w.i32(pos)
        w.i32(len(table.lines))
        for chance, ids in table.lines:
            if len(ids) != len(table.positions):
                raise FormatError(f"random unit table {table.id}: each line needs one id per position")
            w.i32(chance)
            for rawcode in ids:
                w.raw(_four(rawcode, "random unit id"))
    w.i32(len(mi.random_item_tables))
    for table in mi.random_item_tables:
        w.i32(table.id)
        w.cstr(table.name)
        w.i32(len(table.sets))
        for item_set in table.sets:
            w.i32(len(item_set))
            for chance, rawcode in item_set:
                w.i32(chance)
                w.raw(_four(rawcode, "random item id"))
    if 26 <= v < 28:
        w.i32(0)
    w.raw(mi.trailing)
    return w.getvalue()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `& $PY -m pytest tests/formats/test_w3i.py -q`
Expected: all passed (3 unit tests + one per sample map)

- [ ] **Step 5: Commit**

```bash
git add src/wc3mcp/formats/w3i.py tests/formats/test_w3i.py
git commit -m "feat(formats): map info codec for w3i v31/v33/v39" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

### Task 4: JSON batch edits

**Files:**
- Create: `src/wc3mcp/ops/__init__.py`, `src/wc3mcp/ops/edits.py`
- Test: `tests/ops/test_edits.py`

**Interfaces:**
- Consumes: Phase 1 `ToolError`.
- Produces: `edits.apply_ops(doc: dict, ops: list) -> dict` — returns an edited deep copy; ops are `{"op": "set", "path", "value"}` (existing list index or any dict key), `{"op": "append", "path", "value"}` (path must be a list), `{"op": "remove", "path"}` (list index or dict key). Paths look like `players[0].name`. Failures raise `ToolError("bad_op", ..., op_index=i)` and leave `doc` untouched.

- [ ] **Step 1: Write the failing test**

`tests/ops/test_edits.py`:
```python
import pytest

from wc3mcp.errors import ToolError
from wc3mcp.ops.edits import apply_ops


def test_set_append_remove_on_a_copy():
    doc = {"a": {"b": [1, 2]}, "c": "x"}
    out = apply_ops(doc, [{"op": "set", "path": "a.b[1]", "value": 5},
                          {"op": "append", "path": "a.b", "value": 7},
                          {"op": "set", "path": "a.new", "value": {"k": 1}},
                          {"op": "remove", "path": "c"}])
    assert out == {"a": {"b": [1, 5, 7], "new": {"k": 1}}}
    assert doc == {"a": {"b": [1, 2]}, "c": "x"}


def test_errors_carry_op_index():
    with pytest.raises(ToolError) as e:
        apply_ops({"a": [1]}, [{"op": "set", "path": "a[0]", "value": 2}, {"op": "set", "path": "a[5]", "value": 1}])
    assert e.value.code == "bad_op" and e.value.details["op_index"] == 1


@pytest.mark.parametrize("op", [
    {"op": "set", "path": "", "value": 1},
    {"op": "explode", "path": "a"},
    {"op": "append", "path": "c", "value": 1},
    {"op": "set", "path": "a..b", "value": 1},
    {"op": "set", "path": "missing.key", "value": 1},
    {"op": "remove", "path": "a[3]"},
    {"op": "set", "path": "a[0]"},
    "not an object",
])
def test_rejects_bad_ops(op):
    with pytest.raises(ToolError) as e:
        apply_ops({"a": [1], "c": "x"}, [op])
    assert e.value.code == "bad_op"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& $PY -m pytest tests/ops/test_edits.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'wc3mcp.ops'`

- [ ] **Step 3: Write minimal implementation**

`src/wc3mcp/ops/__init__.py`:
```python
"""High-level editing operations used by the MCP tools."""
```

`src/wc3mcp/ops/edits.py`:
```python
"""Batch edits on JSON documents: set / append / remove at paths like players[0].name."""
import copy
import re

from ..errors import ToolError

_TOKEN = re.compile(r"([A-Za-z0-9_]+)|\[(\d+)\]")
_HINT = 'ops look like {"op": "set", "path": "players[0].name", "value": "Red"}; also append and remove'


def _parse_path(path) -> list:
    if not isinstance(path, str) or not path:
        raise ValueError("path must be a non-empty string")
    tokens, pos = [], 0
    while pos < len(path):
        if path[pos] == "." and tokens and pos + 1 < len(path):
            pos += 1
        m = _TOKEN.match(path, pos)
        if not m:
            raise ValueError(f"bad path syntax at {path[pos:]!r}")
        tokens.append(m.group(1) if m.group(1) is not None else int(m.group(2)))
        pos = m.end()
    return tokens


def _child(node, token):
    if isinstance(token, int):
        if not isinstance(node, list) or token >= len(node):
            raise ValueError(f"index [{token}] does not exist")
    elif not isinstance(node, dict) or token not in node:
        raise ValueError(f"key {token!r} does not exist")
    return node[token]


def apply_ops(doc: dict, ops: list) -> dict:
    out = copy.deepcopy(doc)
    for i, op in enumerate(ops):
        try:
            if not isinstance(op, dict):
                raise ValueError("each op must be an object")
            tokens = _parse_path(op.get("path"))
            parent = out
            for token in tokens[:-1]:
                parent = _child(parent, token)
            last, kind = tokens[-1], op.get("op")
            if kind in ("set", "append") and "value" not in op:
                raise ValueError(f"{kind} needs a value")
            if kind == "set":
                if isinstance(last, int):
                    _child(parent, last)
                elif not isinstance(parent, dict):
                    raise ValueError(f"cannot set key {last!r} on a list")
                parent[last] = copy.deepcopy(op["value"])
            elif kind == "append":
                target = _child(parent, last)
                if not isinstance(target, list):
                    raise ValueError("append target is not a list")
                target.append(copy.deepcopy(op["value"]))
            elif kind == "remove":
                _child(parent, last)
                del parent[last]
            else:
                raise ValueError(f"unknown op {kind!r}")
        except ValueError as e:
            raise ToolError("bad_op", str(e), hint=_HINT, op_index=i) from e
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `& $PY -m pytest tests/ops/test_edits.py -q`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/wc3mcp/ops/__init__.py src/wc3mcp/ops/edits.py tests/ops/test_edits.py
git commit -m "feat(ops): JSON batch edit engine" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

### Task 5: Map info operations (`info_get` / `info_edit`)

**Files:**
- Create: `src/wc3mcp/ops/info.py`
- Test: `tests/ops/test_info.py`

**Interfaces:**
- Consumes: Task 1 `TriggerStrings`, `TRIGSTR`; Task 2 `FormatError`; Task 3 `w3i`; Task 4 `apply_ops`; Phase 1 `MapProject` (`read`, `write`, `list_files`), `ToolError`.
- Produces: `info.to_json(mi: w3i.MapInfo, strings: TriggerStrings) -> dict`; `info.from_json(doc: dict, strings: TriggerStrings, original: w3i.MapInfo) -> w3i.MapInfo` (updates `strings` in place for edited `TRIGSTR` texts); `info.info_get(project) -> dict`; `info.info_edit(project, ops: list) -> {"changed": bool, "warnings": list[str]}`; constants `MAP_FLAGS`, `PLAYER_FLAGS`, `FORCE_FLAGS`, `CONTROLLERS`, `RACES`, `AVAILABILITY`, `SCRIPT_LANGUAGES`, `POSITION_TYPES`, `SCRIPT_WARNING`.
- Document shape (keys in `info_get` output): `format_version` (read-only), `map_version`, `editor_version`, `game_version` [4], `name`/`author`/`description`/`players_recommended` (+ `*_ref` when backed by a TRIGSTR), `camera_bounds` [8], `camera_bounds_complements` [4], `playable_width`, `playable_height`, `flags` {name: bool}, `unknown_flag_bits`, `tileset` (1 char), `loading_screen` {background, model, text, title, subtitle}, `game_data_set`, `prologue` {path, text, title, subtitle}, `fog` {style, start_z, end_z, density, color {r,g,b,a}}, `global_weather` (4-char id or null), `sound_environment`, `light_environment` ("" or 1 char), `water_tint` {r,g,b,a}, `script_language` ("jass"/"lua"), `supported_modes`, `game_data_version`, `camera_zoom` {default, max, min}, `v39_unknown` {after_loading_background, after_weather [6 u32], after_zoom [10 i32]} (v39 only), `players` [{id, controller, race, flags {fixed_start_position, race_selectable}, unknown_flag_bits, v39_value (when bit 0x40 is set on v39), name(+_ref), start [x, y], ally_low_priorities, ally_high_priorities, enemy_low_priorities, enemy_high_priorities (player id lists)}], `forces` [{flags {allied, allied_victory, share_vision, share_unit_control, share_advanced_unit_control}, unknown_flag_bits, players [ids], name(+_ref)}], `upgrades` [{players, id, level, availability}], `tech` [{players, id}], `random_unit_tables` [{id, name, positions ["unit"|"building"|"item"], lines [{chance, ids [id|null]}]}], `random_item_tables` [{id, name, sets [[{chance, id}]]}].
- Error codes: `bad_value` (details `path`), `bad_file`, `unsupported_version`, plus `bad_op` from `apply_ops`.

- [ ] **Step 1: Write the failing test**

`tests/ops/test_info.py`:
```python
import pytest

from corpus import ladder_maps, open_sample, sample_map_ids
from wc3mcp.errors import ToolError
from wc3mcp.formats import w3i
from wc3mcp.formats.wts import TriggerStrings
from wc3mcp.ops.info import SCRIPT_WARNING, from_json, info_edit, info_get, to_json
from wc3mcp.project.workspace import MapProject


@pytest.fixture
def project(tmp_path):
    maps = ladder_maps()
    if not maps:
        pytest.skip("no ladder maps in Documents")
    src = tmp_path / maps[0].name
    src.write_bytes(maps[0].read_bytes())
    return MapProject.open(src)


def test_info_get_resolves_trigger_strings(project):
    info = info_get(project)
    assert info["format_version"] in w3i.WRITABLE_VERSIONS
    assert info["name_ref"].startswith("TRIGSTR_") and not info["name"].startswith("TRIGSTR_")
    assert info["players"][0]["controller"] in ("user", "computer")


def test_edit_text_updates_wts_and_keeps_reference(project):
    before = info_get(project)
    result = info_edit(project, [{"op": "set", "path": "name", "value": "Arena of Tests"}])
    assert result["changed"] and SCRIPT_WARNING not in result["warnings"]
    after = info_get(project)
    assert after["name"] == "Arena of Tests" and after["name_ref"] == before["name_ref"]
    assert w3i.parse(project.read("war3map.w3i")).name == before["name_ref"]


def test_structural_edit_warns_about_script(project):
    result = info_edit(project, [{"op": "set", "path": "flags.use_custom_forces", "value": True},
                                 {"op": "set", "path": "players[0].race", "value": "orc"}])
    assert SCRIPT_WARNING in result["warnings"]
    info = info_get(project)
    assert info["flags"]["use_custom_forces"] is True and info["players"][0]["race"] == "orc"


def test_invalid_value_changes_nothing(project):
    before = (project.read("war3map.w3i"), project.read("war3map.wts"))
    with pytest.raises(ToolError) as e:
        info_edit(project, [{"op": "set", "path": "name", "value": "x"},
                            {"op": "set", "path": "players[0].controller", "value": "alien"}])
    assert e.value.code == "bad_value" and e.value.details["path"] == "players[0].controller"
    assert (project.read("war3map.w3i"), project.read("war3map.wts")) == before


def test_format_version_is_read_only_and_empty_batch_is_a_no_op(project):
    with pytest.raises(ToolError) as e:
        info_edit(project, [{"op": "set", "path": "format_version", "value": 1}])
    assert e.value.details["path"] == "format_version"
    assert info_edit(project, []) == {"changed": False, "warnings": []}


@pytest.mark.parametrize("map_id", sample_map_ids())
def test_json_roundtrip_is_byte_exact(map_id):
    arc = open_sample(map_id)
    data = arc.read("war3map.w3i")
    wts_data = arc.read("war3map.wts") or b""
    mi, strings = w3i.parse(data), TriggerStrings.parse(wts_data)
    assert w3i.serialize(from_json(to_json(mi, strings), strings, mi)) == data
    assert strings.serialize() == wts_data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& $PY -m pytest tests/ops/test_info.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'wc3mcp.ops.info'`

- [ ] **Step 3: Write minimal implementation**

`src/wc3mcp/ops/info.py`:
```python
"""Map info as editable JSON: war3map.w3i with friendly names; TRIGSTR text resolved through war3map.wts."""
import struct

from ..errors import ToolError
from ..formats import w3i
from ..formats.binary import FormatError
from ..formats.wts import TRIGSTR, TriggerStrings
from .edits import apply_ops

MAP_FLAGS = {
    "hide_minimap_in_preview": 1 << 0, "modify_ally_priorities": 1 << 1, "melee_map": 1 << 2,
    "playable_map_size_was_large": 1 << 3, "masked_areas_partially_visible": 1 << 4,
    "fixed_player_settings_for_custom_forces": 1 << 5, "use_custom_forces": 1 << 6, "use_custom_techtree": 1 << 7,
    "use_custom_abilities": 1 << 8, "use_custom_upgrades": 1 << 9, "map_properties_menu_opened": 1 << 10,
    "water_waves_on_cliff_shores": 1 << 11, "water_waves_on_rolling_shores": 1 << 12, "use_terrain_fog": 1 << 13,
    "requires_expansion": 1 << 14, "use_item_classification_system": 1 << 15, "use_water_tinting": 1 << 16,
    "accurate_probability_for_calculations": 1 << 17, "custom_ability_skin": 1 << 18,
    "disable_deny_icon": 1 << 19, "force_default_camera_zoom": 1 << 20, "force_max_camera_zoom": 1 << 21,
    "force_min_camera_zoom": 1 << 22,
}
PLAYER_FLAGS = {"fixed_start_position": 1 << 0, "race_selectable": 1 << 1}
FORCE_FLAGS = {"allied": 1 << 0, "allied_victory": 1 << 1, "share_vision": 1 << 2, "share_unit_control": 1 << 4,
               "share_advanced_unit_control": 1 << 5}
CONTROLLERS = {0: "none", 1: "user", 2: "computer", 3: "neutral", 4: "rescuable"}
RACES = {0: "none", 1: "human", 2: "orc", 3: "undead", 4: "night_elf"}
AVAILABILITY = {0: "unavailable", 1: "available", 2: "researched"}
SCRIPT_LANGUAGES = {0: "jass", 1: "lua"}
POSITION_TYPES = {0: "unit", 1: "building", 2: "item"}
SCRIPT_KEYS = ("players", "forces", "upgrades", "tech", "random_unit_tables", "random_item_tables", "camera_bounds",
               "camera_bounds_complements", "playable_width", "playable_height", "script_language")
SCRIPT_FLAGS = ("modify_ally_priorities", "melee_map", "fixed_player_settings_for_custom_forces", "use_custom_forces",
                "use_custom_techtree", "use_custom_abilities", "use_custom_upgrades")
SCRIPT_WARNING = ("war3map.j/lua was not regenerated: save the map in the World Editor so player, force, tech and "
                  "camera setup in the script match the new map info")


# ---- validation helpers -------------------------------------------------------------------------------------
def _p(path: str, key) -> str:
    if isinstance(key, int):
        return f"{path}[{key}]"
    return f"{path}.{key}" if path else key


def _bad(path: str, message: str) -> ToolError:
    return ToolError("bad_value", f"{path or 'document'}: {message}", hint="info_get shows the document shape",
                     path=path)


def _get(doc, key: str, path: str):
    if not isinstance(doc, dict):
        raise _bad(path, "expected an object")
    if key not in doc:
        raise _bad(_p(path, key), "missing")
    return doc[key]


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _int(doc, key: str, path: str) -> int:
    v = _get(doc, key, path)
    if not _is_int(v):
        raise _bad(_p(path, key), "expected an integer")
    return v


def _num(doc, key: str, path: str) -> float:
    v = _get(doc, key, path)
    if not (_is_int(v) or isinstance(v, float)):
        raise _bad(_p(path, key), "expected a number")
    return float(v)


def _str(doc, key: str, path: str) -> str:
    v = _get(doc, key, path)
    if not isinstance(v, str):
        raise _bad(_p(path, key), "expected a string")
    return v


def _list(doc, key: str, path: str) -> list:
    v = _get(doc, key, path)
    if not isinstance(v, list):
        raise _bad(_p(path, key), "expected a list")
    return v


def _int_list(doc, key: str, path: str, n: int) -> list[int]:
    v = _list(doc, key, path)
    if len(v) != n or not all(_is_int(x) for x in v):
        raise _bad(_p(path, key), f"expected {n} integers")
    return list(v)


def _num_list(doc, key: str, path: str, n: int) -> list[float]:
    v = _list(doc, key, path)
    if len(v) != n or not all(_is_int(x) or isinstance(x, float) for x in v):
        raise _bad(_p(path, key), f"expected {n} numbers")
    return [float(x) for x in v]


def _enum_value(v, path: str, names: dict) -> int:
    if _is_int(v):
        return v
    reverse = {name: code for code, name in names.items()}
    if v in reverse:
        return reverse[v]
    raise _bad(path, f"expected one of {sorted(reverse)} or an integer")


def _enum(doc, key: str, path: str, names: dict) -> int:
    return _enum_value(_get(doc, key, path), _p(path, key), names)


def _flags_out(value: int, names: dict) -> tuple[dict, int]:
    known = 0
    for bit in names.values():
        known |= bit
    return {name: bool(value & bit) for name, bit in names.items()}, value & ~known


def _flags_in(doc, path: str, names: dict) -> int:
    flags = _get(doc, "flags", path)
    if not isinstance(flags, dict):
        raise _bad(_p(path, "flags"), "expected an object of booleans")
    value = _int(doc, "unknown_flag_bits", path)
    for name, on in flags.items():
        if name not in names:
            raise _bad(_p(_p(path, "flags"), name), f"unknown flag; known flags: {sorted(names)}")
        if not isinstance(on, bool):
            raise _bad(_p(_p(path, "flags"), name), "expected true or false")
        if on:
            value |= names[name]
    return value


def _mask_out(mask: int) -> list[int]:
    return [i for i in range(32) if mask >> i & 1]


def _mask_in(doc, key: str, path: str) -> int:
    mask = 0
    for i, pid in enumerate(_list(doc, key, path)):
        if not _is_int(pid) or not 0 <= pid < 32:
            raise _bad(_p(_p(path, key), i), "expected a player number 0-31")
        mask |= 1 << pid
    return mask


def _raw_out(b: bytes):
    return None if b == b"\0\0\0\0" else b.decode("latin-1")


def _raw_in(v, path: str) -> bytes:
    if v is None:
        return b"\0\0\0\0"
    if isinstance(v, str) and len(v) == 4 and all(ord(c) < 256 for c in v):
        return v.encode("latin-1")
    raise _bad(path, "expected a 4-character id such as 'hfoo', or null")


def _color_out(b: bytes) -> dict:
    return {"r": b[2], "g": b[1], "b": b[0], "a": b[3]}


def _color_in(doc, key: str, path: str) -> bytes:
    color, cpath = _get(doc, key, path), _p(path, key)
    values = [_int(color, k, cpath) for k in ("b", "g", "r", "a")]
    if not all(0 <= x <= 255 for x in values):
        raise _bad(cpath, "color components must be 0-255")
    return bytes(values)


def _char_in(doc, key: str, path: str, allow_empty: bool) -> int:
    v = _str(doc, key, path)
    if v == "" and allow_empty:
        return 0
    if len(v) != 1 or ord(v) > 255:
        raise _bad(_p(path, key), "expected a single character")
    return ord(v)


def _text_out(doc: dict, key: str, value: str, strings: TriggerStrings) -> None:
    if TRIGSTR.match(value):
        doc[key] = strings.resolve(value)
        doc[key + "_ref"] = value
    else:
        doc[key] = value


def _text_in(doc, key: str, path: str, strings: TriggerStrings) -> str:
    value = _str(doc, key, path)
    ref = doc.get(key + "_ref")
    if ref is None:
        return value
    m = TRIGSTR.match(ref) if isinstance(ref, str) else None
    if not m:
        raise _bad(_p(path, key + "_ref"), "expected TRIGSTR_<number>")
    if value != ref and strings.get(int(m.group(1))) != value:
        strings.set(int(m.group(1)), value)
    return ref


# ---- conversion -----------------------------------------------------------------------------------------------
def to_json(mi: w3i.MapInfo, strings: TriggerStrings) -> dict:
    doc = {"format_version": mi.version, "map_version": mi.map_version, "editor_version": mi.editor_version,
           "game_version": list(mi.game_version)}
    for key in ("name", "author", "description", "players_recommended"):
        _text_out(doc, key, getattr(mi, key), strings)
    flags, unknown = _flags_out(mi.flags, MAP_FLAGS)
    doc.update({"camera_bounds": list(mi.camera_bounds), "camera_bounds_complements": list(mi.camera_complements),
                "playable_width": mi.playable_width, "playable_height": mi.playable_height,
                "flags": flags, "unknown_flag_bits": unknown, "tileset": chr(mi.tileset),
                "loading_screen": {"background": mi.loading_screen_background, "model": mi.loading_screen_model},
                "game_data_set": mi.game_data_set, "prologue": {"path": mi.prologue_path}})
    for key in ("text", "title", "subtitle"):
        _text_out(doc["loading_screen"], key, getattr(mi, f"loading_screen_{key}"), strings)
        _text_out(doc["prologue"], key, getattr(mi, f"prologue_{key}"), strings)
    doc.update({
        "fog": {"style": mi.fog_style, "start_z": mi.fog_start_z, "end_z": mi.fog_end_z, "density": mi.fog_density,
                "color": _color_out(mi.fog_color)},
        "global_weather": _raw_out(mi.global_weather),
        "sound_environment": mi.sound_environment,
        "light_environment": chr(mi.light_environment) if mi.light_environment else "",
        "water_tint": _color_out(mi.water_tint),
        "script_language": SCRIPT_LANGUAGES.get(mi.script_language, mi.script_language),
        "supported_modes": mi.supported_modes,
        "game_data_version": mi.game_data_version,
        "camera_zoom": {"default": mi.default_camera_zoom, "max": mi.max_camera_zoom, "min": mi.min_camera_zoom},
    })
    if mi.version >= 39:
        doc["v39_unknown"] = {"after_loading_background": mi.v39_after_loading_background,
                              "after_weather": list(mi.v39_after_weather), "after_zoom": list(mi.v39_after_zoom)}
    doc["players"] = []
    for p in mi.players:
        pflags, punknown = _flags_out(p.flags, PLAYER_FLAGS)
        entry = {"id": p.id, "controller": CONTROLLERS.get(p.controller, p.controller),
                 "race": RACES.get(p.race, p.race), "flags": pflags, "unknown_flag_bits": punknown}
        if mi.version >= 39 and p.flags & w3i.PLAYER_FLAG_V39_EXTRA:
            entry["v39_value"] = p.v39_value
        _text_out(entry, "name", p.name, strings)
        entry.update({"start": [p.start_x, p.start_y],
                      "ally_low_priorities": _mask_out(p.ally_low), "ally_high_priorities": _mask_out(p.ally_high),
                      "enemy_low_priorities": _mask_out(p.enemy_low),
                      "enemy_high_priorities": _mask_out(p.enemy_high)})
        doc["players"].append(entry)
    doc["forces"] = []
    for f in mi.forces:
        fflags, funknown = _flags_out(f.flags, FORCE_FLAGS)
        entry = {"flags": fflags, "unknown_flag_bits": funknown, "players": _mask_out(f.players)}
        _text_out(entry, "name", f.name, strings)
        doc["forces"].append(entry)
    doc["upgrades"] = [{"players": _mask_out(u.players), "id": _raw_out(u.id), "level": u.level,
                        "availability": AVAILABILITY.get(u.availability, u.availability)} for u in mi.upgrades]
    doc["tech"] = [{"players": _mask_out(t.players), "id": _raw_out(t.id)} for t in mi.tech]
    doc["random_unit_tables"] = [
        {"id": t.id, "name": t.name, "positions": [POSITION_TYPES.get(x, x) for x in t.positions],
         "lines": [{"chance": chance, "ids": [_raw_out(i) for i in ids]} for chance, ids in t.lines]}
        for t in mi.random_unit_tables]
    doc["random_item_tables"] = [
        {"id": t.id, "name": t.name,
         "sets": [[{"chance": chance, "id": _raw_out(i)} for chance, i in item_set] for item_set in t.sets]}
        for t in mi.random_item_tables]
    return doc


def from_json(doc: dict, strings: TriggerStrings, original: w3i.MapInfo) -> w3i.MapInfo:
    v = original.version
    if _int(doc, "format_version", "") != v:
        raise _bad("format_version", f"read-only (this map uses version {v})")
    mi = w3i.MapInfo(v, map_version=_int(doc, "map_version", ""), editor_version=_int(doc, "editor_version", ""),
                     truncated=original.truncated, trailing=original.trailing)
    mi.game_version = _int_list(doc, "game_version", "", 4)
    for key in ("name", "author", "description", "players_recommended"):
        setattr(mi, key, _text_in(doc, key, "", strings))
    mi.camera_bounds = _num_list(doc, "camera_bounds", "", 8)
    mi.camera_complements = _int_list(doc, "camera_bounds_complements", "", 4)
    mi.playable_width, mi.playable_height = _int(doc, "playable_width", ""), _int(doc, "playable_height", "")
    mi.flags = _flags_in(doc, "", MAP_FLAGS)
    mi.tileset = _char_in(doc, "tileset", "", allow_empty=False)
    ls = _get(doc, "loading_screen", "")
    mi.loading_screen_background = _int(ls, "background", "loading_screen")
    mi.loading_screen_model = _str(ls, "model", "loading_screen")
    pro = _get(doc, "prologue", "")
    mi.prologue_path = _str(pro, "path", "prologue")
    for key in ("text", "title", "subtitle"):
        setattr(mi, f"loading_screen_{key}", _text_in(ls, key, "loading_screen", strings))
        setattr(mi, f"prologue_{key}", _text_in(pro, key, "prologue", strings))
    mi.game_data_set = _int(doc, "game_data_set", "")
    fog = _get(doc, "fog", "")
    mi.fog_style = _int(fog, "style", "fog")
    mi.fog_start_z, mi.fog_end_z = _num(fog, "start_z", "fog"), _num(fog, "end_z", "fog")
    mi.fog_density = _num(fog, "density", "fog")
    mi.fog_color = _color_in(fog, "color", "fog")
    mi.global_weather = _raw_in(_get(doc, "global_weather", ""), "global_weather")
    mi.sound_environment = _str(doc, "sound_environment", "")
    mi.light_environment = _char_in(doc, "light_environment", "", allow_empty=True)
    mi.water_tint = _color_in(doc, "water_tint", "")
    mi.script_language = _enum(doc, "script_language", "", SCRIPT_LANGUAGES)
    mi.supported_modes, mi.game_data_version = _int(doc, "supported_modes", ""), _int(doc, "game_data_version", "")
    zoom = _get(doc, "camera_zoom", "")
    mi.default_camera_zoom = _int(zoom, "default", "camera_zoom")
    mi.max_camera_zoom, mi.min_camera_zoom = _int(zoom, "max", "camera_zoom"), _int(zoom, "min", "camera_zoom")
    if v >= 39:
        unknown = _get(doc, "v39_unknown", "")
        mi.v39_after_loading_background = _int(unknown, "after_loading_background", "v39_unknown")
        mi.v39_after_weather = _int_list(unknown, "after_weather", "v39_unknown", 6)
        mi.v39_after_zoom = _int_list(unknown, "after_zoom", "v39_unknown", 10)
    for i, entry in enumerate(_list(doc, "players", "")):
        path = f"players[{i}]"
        flags = _flags_in(entry, path, PLAYER_FLAGS)
        start = _num_list(entry, "start", path, 2)
        player = w3i.Player(_int(entry, "id", path), _enum(entry, "controller", path, CONTROLLERS),
                            _enum(entry, "race", path, RACES), flags, _text_in(entry, "name", path, strings),
                            start[0], start[1], _mask_in(entry, "ally_low_priorities", path),
                            _mask_in(entry, "ally_high_priorities", path), _mask_in(entry, "enemy_low_priorities", path),
                            _mask_in(entry, "enemy_high_priorities", path))
        if v >= 39 and flags & w3i.PLAYER_FLAG_V39_EXTRA and "v39_value" in entry:
            player.v39_value = _int(entry, "v39_value", path)
        mi.players.append(player)
    for i, entry in enumerate(_list(doc, "forces", "")):
        path = f"forces[{i}]"
        mi.forces.append(w3i.Force(_flags_in(entry, path, FORCE_FLAGS), _mask_in(entry, "players", path),
                                   _text_in(entry, "name", path, strings)))
    for i, entry in enumerate(_list(doc, "upgrades", "")):
        path = f"upgrades[{i}]"
        mi.upgrades.append(w3i.UpgradeChange(_mask_in(entry, "players", path),
                                             _raw_in(_get(entry, "id", path), _p(path, "id")),
                                             _int(entry, "level", path), _enum(entry, "availability", path, AVAILABILITY)))
    for i, entry in enumerate(_list(doc, "tech", "")):
        path = f"tech[{i}]"
        mi.tech.append(w3i.TechChange(_mask_in(entry, "players", path), _raw_in(_get(entry, "id", path), _p(path, "id"))))
    for i, entry in enumerate(_list(doc, "random_unit_tables", "")):
        path = f"random_unit_tables[{i}]"
        positions = [_enum_value(x, f"{path}.positions[{j}]", POSITION_TYPES)
                     for j, x in enumerate(_list(entry, "positions", path))]
        lines = []
        for j, line in enumerate(_list(entry, "lines", path)):
            lpath = f"{path}.lines[{j}]"
            ids = _list(line, "ids", lpath)
            if len(ids) != len(positions):
                raise _bad(f"{lpath}.ids", "needs one id (or null) per position")
            lines.append((_int(line, "chance", lpath), [_raw_in(x, f"{lpath}.ids[{k}]") for k, x in enumerate(ids)]))
        mi.random_unit_tables.append(w3i.RandomUnitTable(_int(entry, "id", path), _str(entry, "name", path),
                                                         positions, lines))
    for i, entry in enumerate(_list(doc, "random_item_tables", "")):
        path = f"random_item_tables[{i}]"
        sets = []
        for j, item_set in enumerate(_list(entry, "sets", path)):
            spath = f"{path}.sets[{j}]"
            if not isinstance(item_set, list):
                raise _bad(spath, "expected a list of {chance, id}")
            sets.append([(_int(item, "chance", f"{spath}[{k}]"), _raw_in(_get(item, "id", f"{spath}[{k}]"),
                                                                         f"{spath}[{k}].id"))
                         for k, item in enumerate(item_set)])
        mi.random_item_tables.append(w3i.RandomItemTable(_int(entry, "id", path), _str(entry, "name", path), sets))
    return mi


# ---- project operations ---------------------------------------------------------------------------------------
def _load(project) -> tuple[w3i.MapInfo, TriggerStrings]:
    try:
        mi = w3i.parse(project.read("war3map.w3i"))
    except FormatError as e:
        raise ToolError("bad_file", f"war3map.w3i: {e}") from e
    try:
        strings = TriggerStrings.parse(project.read("war3map.wts"))
    except ToolError as e:
        if e.code != "no_such_file":
            raise
        strings = TriggerStrings()
    return mi, strings


def info_get(project) -> dict:
    mi, strings = _load(project)
    return to_json(mi, strings)


def info_edit(project, ops: list) -> dict:
    mi, strings = _load(project)
    if mi.version not in w3i.WRITABLE_VERSIONS:
        raise ToolError("unsupported_version", f"war3map.w3i format version {mi.version} is read-only here",
                        hint="edit it in the World Editor, or replace the raw file with map_file_write")
    before = to_json(mi, strings)
    after = apply_ops(before, ops)
    wts_before = strings.serialize()
    new_mi = from_json(after, strings, mi)
    try:
        data = w3i.serialize(new_mi)
    except (FormatError, struct.error) as e:
        raise ToolError("bad_value", f"cannot encode map info: {e}", path="") from e
    wts_after = strings.serialize()
    old = project.read("war3map.w3i")
    warnings = []
    if any(after[k] != before[k] for k in SCRIPT_KEYS) or any(after["flags"].get(f) != before["flags"][f]
                                                             for f in SCRIPT_FLAGS):
        warnings.append(SCRIPT_WARNING)
    if wts_after != wts_before and any(f["name"].lower().startswith("_locales\\") for f in project.list_files()):
        warnings.append("localized string tables under _Locales were not updated")
    if data != old:
        project.write("war3map.w3i", data)
    if wts_after != wts_before:
        project.write("war3map.wts", wts_after)
    return {"changed": data != old or wts_after != wts_before, "warnings": warnings}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `& $PY -m pytest tests/ops/test_info.py -q`
Expected: all passed (5 project tests + one JSON round-trip per sample map)

- [ ] **Step 5: Commit**

```bash
git add src/wc3mcp/ops/info.py tests/ops/test_info.py
git commit -m "feat(ops): map info as editable JSON with TRIGSTR-aware edits" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

### Task 6: Import operations

**Files:**
- Create: `src/wc3mcp/ops/imports.py`
- Test: `tests/ops/test_imports.py`

**Interfaces:**
- Consumes: Task 2 `imp`, `FormatError`; Phase 1 `MapProject` (`read`, `write`, `delete`, `list_files`, `status`), `check_name`, `write_archive`, `ToolError`.
- Produces: `imports.imports_list(project) -> list[dict]` (`{"path", "flag", "size"}`, `size` None when the file is missing); `imports.imports_edit(project, ops: list) -> {"imports": [...]}` with ops `{"op": "add", "path", "source" | "content_base64"}` (replaces data and keeps the flag when already imported; new entries get `imp.DEFAULT_FLAG`) and `{"op": "remove", "path"}` (drops the entry and deletes the file). Error codes: `bad_op`, `bad_name`, `bad_content`, `not_found`, `no_such_import`, `bad_file`; every error from an op carries `op_index`.

- [ ] **Step 1: Write the failing test**

`tests/ops/test_imports.py`:
```python
import base64

import pytest

from wc3mcp.errors import ToolError
from wc3mcp.formats import imp
from wc3mcp.mpq.writer import write_archive
from wc3mcp.ops.imports import imports_edit, imports_list
from wc3mcp.project.workspace import MapProject


def make_project(tmp_path, files) -> MapProject:
    src = tmp_path / "m.w3x"
    src.write_bytes(write_archive(files))
    return MapProject.open(src)


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def test_add_from_source_and_base64(tmp_path):
    p = make_project(tmp_path, {"war3map.w3i": b"i"})
    icon = tmp_path / "icon.blp"
    icon.write_bytes(b"BLP1data")
    result = imports_edit(p, [{"op": "add", "path": "war3mapImported\\icon.blp", "source": str(icon)},
                              {"op": "add", "path": "war3mapImported/sound.mp3", "content_base64": b64(b"ID3")}])
    assert result["imports"] == [{"path": "war3mapImported/icon.blp", "flag": 29, "size": 8},
                                 {"path": "war3mapImported/sound.mp3", "flag": 29, "size": 3}]
    assert p.read("war3mapImported\\sound.mp3") == b"ID3"
    assert imp.parse(p.read("war3map.imp")).entries[0].path == "war3mapImported/icon.blp"


def test_replace_keeps_flag_and_remove_deletes_file(tmp_path):
    existing = imp.serialize(imp.ImportList(1, [imp.ImportEntry(13, "war3mapImported/a.txt")]))
    p = make_project(tmp_path, {"war3map.imp": existing, "war3mapImported\\a.txt": b"old"})
    imports_edit(p, [{"op": "add", "path": "war3mapImported/a.txt", "content_base64": b64(b"new")}])
    assert imports_list(p) == [{"path": "war3mapImported/a.txt", "flag": 13, "size": 3}]
    imports_edit(p, [{"op": "remove", "path": "war3mapImported/a.txt"}])
    assert imports_list(p) == []
    assert "war3mapImported\\a.txt" not in {f["name"] for f in p.list_files()}


def test_batch_is_atomic(tmp_path):
    p = make_project(tmp_path, {"war3map.w3i": b"i"})
    with pytest.raises(ToolError) as e:
        imports_edit(p, [{"op": "add", "path": "war3mapImported/x.txt", "content_base64": b64(b"x")},
                         {"op": "remove", "path": "war3mapImported/missing.txt"}])
    assert e.value.code == "no_such_import" and e.value.details["op_index"] == 1
    assert p.status()["dirty"] == []


@pytest.mark.parametrize("op, code", [
    ({"op": "add", "path": "..\\evil.txt", "content_base64": "eA=="}, "bad_name"),
    ({"op": "add", "path": "a.txt"}, "bad_op"),
    ({"op": "add", "path": "a.txt", "content_base64": "not base64!"}, "bad_content"),
    ({"op": "add", "path": "a.txt", "source": "C:/definitely/missing/file.bin"}, "not_found"),
    ({"op": "rename", "path": "a.txt"}, "bad_op"),
    ({"op": "add"}, "bad_op"),
])
def test_rejects_bad_ops(tmp_path, op, code):
    p = make_project(tmp_path, {"war3map.w3i": b"i"})
    with pytest.raises(ToolError) as e:
        imports_edit(p, [op])
    assert e.value.code == code and e.value.details["op_index"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& $PY -m pytest tests/ops/test_imports.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'wc3mcp.ops.imports'`

- [ ] **Step 3: Write minimal implementation**

`src/wc3mcp/ops/imports.py`:
```python
"""Imported files: war3map.imp entries kept in step with the files inside the map."""
import base64
from pathlib import Path

from ..errors import ToolError
from ..formats import imp
from ..formats.binary import FormatError
from ..project.workspace import check_name


def _key(path: str) -> str:
    return path.replace("\\", "/").lower()


def _load(project) -> imp.ImportList:
    try:
        return imp.parse(project.read("war3map.imp"))
    except ToolError as e:
        if e.code == "no_such_file":
            return imp.ImportList()
        raise
    except FormatError as e:
        raise ToolError("bad_file", f"war3map.imp: {e}") from e


def _content(op: dict) -> bytes:
    if "source" in op:
        src = Path(str(op["source"]))
        if not src.is_file():
            raise ToolError("not_found", f"source file not found: {src}")
        return src.read_bytes()
    if "content_base64" in op:
        try:
            return base64.b64decode(op["content_base64"], validate=True)
        except (ValueError, TypeError) as e:
            raise ToolError("bad_content", f"content_base64 is not valid base64: {e}") from e
    raise ToolError("bad_op", "add needs source (a local file path) or content_base64")


def imports_list(project) -> list[dict]:
    sizes = {_key(f["name"]): f["size"] for f in project.list_files()}
    return [{"path": e.path, "flag": e.flag, "size": sizes.get(_key(e.path))} for e in _load(project).entries]


def imports_edit(project, ops: list) -> dict:
    imports = _load(project)
    existing = {_key(f["name"]) for f in project.list_files()}
    writes: dict[str, tuple[str, bytes]] = {}  # lower-case key -> (name as given, data)
    deletes: set[str] = set()
    for i, op in enumerate(ops):
        try:
            if not isinstance(op, dict) or not isinstance(op.get("path"), str):
                raise ToolError("bad_op", "each op needs an op name and a path string",
                                hint='{"op": "add", "path": "war3mapImported/icon.blp", "source": "C:/icon.blp"}')
            name = check_name(op["path"])
            key = _key(name)
            entry = next((e for e in imports.entries if _key(e.path) == key), None)
            if op.get("op") == "add":
                data = _content(op)
                if entry is None:
                    imports.entries.append(imp.ImportEntry(imp.DEFAULT_FLAG, name.replace("\\", "/")))
                writes[key] = (name, data)
                deletes.discard(key)
            elif op.get("op") == "remove":
                if entry is None and key not in existing and key not in writes:
                    raise ToolError("no_such_import", f"{op['path']} is neither imported nor in the map")
                if entry is not None:
                    imports.entries.remove(entry)
                writes.pop(key, None)
                deletes.add(key)
            else:
                raise ToolError("bad_op", f"unknown op {op.get('op')!r}", hint="use add or remove")
        except ToolError as e:
            e.details.setdefault("op_index", i)
            raise
    for name, data in writes.values():
        project.write(name, data)
    for f in project.list_files():
        if _key(f["name"]) in deletes:
            project.delete(f["name"])
    if ops:
        project.write("war3map.imp", imp.serialize(imports))
    return {"imports": imports_list(project)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `& $PY -m pytest tests/ops/test_imports.py -q`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/wc3mcp/ops/imports.py tests/ops/test_imports.py
git commit -m "feat(ops): import list edits kept in step with map files" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

### Task 7: Server tools and full verification

**Files:**
- Modify: `src/wc3mcp/server.py` (imports + three tools), `tests/test_server.py` (imports, `EXPECTED`, new test)

**Interfaces:**
- Consumes: Task 5 `info_get`, `info_edit`; Task 6 `imports_edit`; Phase 1 `_tool`, `_project`.
- Produces: MCP tools `info_get(path)`, `info_edit(path, ops)`, `imports_edit(path, ops=None)`.

- [ ] **Step 1: Write the failing test**

In `tests/test_server.py`, replace the import block and `EXPECTED` with:
```python
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.memory import create_connected_server_and_client_session

from corpus import ladder_maps, needs_install
from wc3mcp import server
from wc3mcp.mpq.reader import Archive
from wc3mcp.mpq.writer import write_archive

EXPECTED = {"map_open", "map_close", "map_save", "map_status", "map_file_read", "map_file_write", "map_snapshot",
            "data_search", "data_get", "data_file", "info_get", "info_edit", "imports_edit"}
```

Append to `tests/test_server.py`:
```python
def test_info_and_import_tools(tmp_path):
    maps = ladder_maps()
    if not maps:
        pytest.skip("no ladder maps in Documents")
    src = tmp_path / maps[0].name
    src.write_bytes(maps[0].read_bytes())
    path = str(src)
    payload(call("map_open", {"path": path}))
    payload(call("info_edit", {"path": path, "ops": [{"op": "set", "path": "name", "value": "Server Test"}]}))
    assert payload(call("info_get", {"path": path}))["name"] == "Server Test"
    listed = payload(call("imports_edit", {"path": path, "ops": [
        {"op": "add", "path": "war3mapImported/t.txt", "content_base64": "aGk="}]}))
    assert {"path": "war3mapImported/t.txt", "flag": 29, "size": 2} in listed["imports"]
    err = call("info_edit", {"path": path, "ops": [{"op": "set", "path": "players[99].name", "value": "x"}]})
    assert err.isError and json.loads(err.content[0].text.split(": ", 1)[1])["code"] == "bad_op"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& $PY -m pytest tests/test_server.py -q`
Expected: FAIL in `test_tools_are_registered` (missing tool names) and `test_info_and_import_tools` (unknown tool `info_edit`)

- [ ] **Step 3: Write minimal implementation**

In `src/wc3mcp/server.py`, extend the local imports:
```python
from . import config
from .casc.storage import open_storage
from .errors import ToolError
from .gamedata.catalog import Catalog
from .ops import imports as imports_ops
from .ops import info as info_ops
from .project.workspace import MapProject
```

Add these tools after `data_file`:
```python
@_tool
def info_get(path: str) -> dict:
    """Map info (war3map.w3i) of an open map as JSON: name, author, description, loading screen, fog, weather,
    script language, camera zoom, map flags, players, forces, tech/upgrade availability and random tables. Text backed
    by the string table is shown resolved, with its TRIGSTR reference in a matching *_ref key."""
    return info_ops.info_get(_project(path))


@_tool
def info_edit(path: str, ops: list[dict]) -> dict:
    """Edit map info with a batch of ops applied all-or-nothing to the info_get document, e.g.
    {"op": "set", "path": "players[0].race", "value": "orc"}, {"op": "append", "path": "forces", "value": {...}},
    {"op": "remove", "path": "tech[2]"}. Editing *_ref-backed text updates war3map.wts. Returns warnings, e.g. when the
    map script needs regenerating in the World Editor."""
    return info_ops.info_edit(_project(path), ops)


@_tool
def imports_edit(path: str, ops: list[dict] | None = None) -> dict:
    """List or change imported files of an open map (war3map.imp plus the files themselves). ops:
    {"op": "add", "path": "war3mapImported/icon.blp", "source": "C:/local/icon.blp"} (or "content_base64"),
    {"op": "remove", "path": "war3mapImported/icon.blp"}. Without ops it only lists. Batches apply all-or-nothing."""
    return imports_ops.imports_edit(_project(path), ops or [])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& $PY -m pytest tests/test_server.py -q`
Expected: 6 passed

Run: `& $PY -m pytest -q`
Expected: every test passes (Phase 1's 172 plus the new Phase 2a tests)

- [ ] **Step 5: Commit**

```bash
git add src/wc3mcp/server.py tests/test_server.py
git commit -m "feat(server): info_get, info_edit and imports_edit tools" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

- [ ] **Step 6: Tell the user**

Report: the three new tools load in a new Claude Code session started in `D:\Warcraft III` (the registered command already points at `src/`). Edits to players, forces, tech or camera setup leave `war3map.j`/`war3map.lua` stale until the map is saved in the World Editor; script regeneration arrives in Phase 2d.