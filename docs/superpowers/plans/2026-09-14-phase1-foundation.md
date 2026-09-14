# Phase 1 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A running `wc3` MCP server that opens/edits/saves Warcraft III maps (MPQ or folder) safely and answers game-data queries from the local CASC storage.

**Architecture:** Pure-Python MPQ reader/writer and CASC reader (ported from verified throwaway probes), SLK/profile parsers and an object catalog on top of CASC, a `MapProject` working-copy layer with backups and snapshots, and a thin FastMCP tool layer.

**Tech Stack:** Python 3.13.14 (Microsoft Store interpreter), stdlib, `mcp 1.27.0` (FastMCP), `pytest 9.0.3`.

**Spec:** `docs/superpowers/specs/2026-09-14-wc3-mcp-design.md` (Phase 1 = build-order item 1).

## Global Constraints

- Interpreter, always by full path (bare `python` on PATH is a package-less 3.12): `%LOCALAPPDATA%\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\python.exe`. Below it is written `$PY`; in PowerShell first run `$PY = "%LOCALAPPDATA%\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\python.exe"`.
- Run tests from `D:\Warcraft III\wc3-mcp`: `& $PY -m pytest <args>`.
- No new dependencies. Phase 1 code uses stdlib + `mcp` only; tests use `pytest`.
- Never write under the game install (`D:\Warcraft III`, override `WC3MCP_INSTALL`). Runtime data lives in `%LOCALAPPDATA%\wc3mcp` (override `WC3MCP_HOME`; tests always override it).
- Corpus tests read local Blizzard data at runtime and skip when it is missing; never copy that data into the repo.
- Game build on this machine: 3.0.0.24268.
- Commit messages end with the line `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Out of this phase (later plans): `map_new` (needs Phase 4 terrain/info writers), `data_search` kinds `trigger_function`/`trigger_type`/`native` (Phase 2), catalog disk cache (in-memory per process for now), editor/game tools (Phase 3).

## Verified facts this plan relies on (probed 2026-09-14)

- MPQ constants: `HashString("(hash table)", 3) = 0xC3AF3770`, `HashString("(block table)", 3) = 0xEC83B3A3`.
- 135 local maps (ladder + Blizzard): header at offset 0, format v0, sector size 4096; normal files flag `0x80000200`; `(listfile)`/`(attributes)` flag `0x80030200` (compressed + encrypted + FIX_KEY); `(attributes)` = u32 version 100, u32 flags 1, then one CRC32 per block. CRC32 of the uncompressed data matched for all 3,590 files; the `(listfile)` entry has its CRC, the `(attributes)` entry stores 0. Hash table size = next power of two ≥ block count.
- `war3map.imp` v1: u32 version, u32 count, entries of (u8 flag, NUL-terminated path); paths use `/`, MPQ names use `\`; flags seen 13, 21, 29.
- SLK: records `ID`, `B`, `C`, `E`; data only in `C;X<col>;[Y<row>;]K<value>`; Y persists across lines; strings quoted.
- Metadata SLK columns include `ID, field, slk, index` (+ abilities `repeat, data, useSpecific, notSpecific`; upgrades `repeat, appendIndex, effectType, effectIndex`). `slk` names a data SLK or `Profile` (merged txt). `uhpm` → `UnitBalance.HP`; `unam` → `Profile.Name` index 0; `Hbz1` → `AbilityData.DataA<level>` for `AHbz` = 6, 8, 10 (base data); `atp1` → `Profile.Tip` index 0 repeat 3 → per-level comma list.
- Profile txt: `[ID]` sections, `key=value`, `//` comment lines, quoted comma lists, trailing tab after `]` possible, skin keys like `modelScale:hd`.
- `WorldEditStrings.txt` / `WorldEditGameStrings.txt` live under `_Locales/<loc>.w3mod:UI/` in section `[WorldEditStrings]`; `WESTRING_UEVAL_UHPM=Hit Points Maximum (Base)`.
- FastMCP 1.27: a tool returning `dict` yields one `TextContent` with JSON; raising `mcp.server.fastmcp.exceptions.ToolError(msg)` yields `isError=True` with text `Error executing tool <name>: <msg>`; `functools.wraps` wrappers keep the argument schema; `create_connected_server_and_client_session(mcp._mcp_server)` works.

## File Structure

```
wc3-mcp/
  pyproject.toml                 project metadata + pytest config
  .gitignore
  src/wc3mcp/__init__.py
  src/wc3mcp/config.py           install root, runtime home, documents dir
  src/wc3mcp/errors.py           ToolError (code, message, hint, details)
  src/wc3mcp/pathguard.py        ensure_writable(path)
  src/wc3mcp/mpq/__init__.py
  src/wc3mcp/mpq/crypto.py       crypt table, hash_string, encrypt/decrypt, file_key, detect_sector_key
  src/wc3mcp/mpq/names.py        KNOWN_NAMES, recover_names(archive)
  src/wc3mcp/mpq/reader.py       Archive (tolerant reader), MpqError, flag constants
  src/wc3mcp/mpq/writer.py       write_archive, RawEntry, capture_unnamed
  src/wc3mcp/casc/__init__.py
  src/wc3mcp/casc/blte.py        lz4_block, blte_decode
  src/wc3mcp/casc/storage.py     Storage, open_storage
  src/wc3mcp/gamedata/__init__.py
  src/wc3mcp/gamedata/slk.py     Table, parse_slk
  src/wc3mcp/gamedata/profile.py parse_profile, split_list, unquote
  src/wc3mcp/gamedata/kinds.py   object/row/path kind definitions
  src/wc3mcp/gamedata/catalog.py Catalog (search/get/fields/westring)
  src/wc3mcp/project/__init__.py
  src/wc3mcp/project/workspace.py MapProject
  src/wc3mcp/server.py           FastMCP app + tools + main()
  tests/corpus.py                locating local install/maps for corpus tests
  tests/conftest.py              isolated WC3MCP_HOME for every test
  tests/test_pathguard.py
  tests/mpq/test_crypto.py  tests/mpq/test_reader.py  tests/mpq/test_writer.py  tests/mpq/test_names.py
  tests/casc/test_blte.py   tests/casc/test_storage.py
  tests/gamedata/test_slk.py  tests/gamedata/test_profile.py  tests/gamedata/test_catalog.py
  tests/project/test_workspace.py
  tests/test_server.py
D:\Warcraft III\.mcp.json       (outside the repo) server registration
```

---

### Task 1: Project scaffold, config, errors, path guard

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `src/wc3mcp/__init__.py`, `src/wc3mcp/config.py`, `src/wc3mcp/errors.py`, `src/wc3mcp/pathguard.py`, `tests/corpus.py`, `tests/conftest.py`
- Test: `tests/test_pathguard.py`

**Interfaces:**
- Produces: `config.install_root() -> Path`, `config.home() -> Path`, `config.documents() -> Path`; `errors.ToolError(code: str, message: str, hint: str | None = None, **details)` with `.code .message .hint .details .to_dict()`; `pathguard.ensure_writable(path) -> Path` (raises `ToolError("install_read_only")`); `tests/corpus.py`: `INSTALL`, `HAVE_INSTALL`, `needs_install`, `ladder_maps() -> list[Path]`.

- [ ] **Step 1: Create scaffold files**

`pyproject.toml`:
```toml
[project]
name = "wc3mcp"
version = "0.1.0"
description = "MCP server for operating the Warcraft III World Editor"
requires-python = ">=3.13"
dependencies = ["mcp>=1.27,<2"]

[tool.pytest.ini_options]
pythonpath = ["src", "tests"]
testpaths = ["tests"]
markers = [
  "editor: drives the World Editor (run on demand)",
  "game: launches Warcraft III (run on demand)",
]
addopts = "-m 'not editor and not game'"
```

`.gitignore`:
```
__pycache__/
.pytest_cache/
*.pyc
```

`src/wc3mcp/__init__.py`:
```python
"""wc3-mcp: operate the Warcraft III World Editor and build maps."""
```

`tests/conftest.py`:
```python
import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("WC3MCP_HOME", str(tmp_path / "wc3mcp-home"))
```

`tests/corpus.py`:
```python
"""Locate local Warcraft III data for corpus tests (read at runtime, never committed)."""
import os
from pathlib import Path

import pytest

INSTALL = Path(os.environ.get("WC3MCP_INSTALL", r"D:\Warcraft III"))
HAVE_INSTALL = (INSTALL / ".build.info").is_file()
needs_install = pytest.mark.skipif(not HAVE_INSTALL, reason="Warcraft III install not found")


def ladder_maps() -> list[Path]:
    from wc3mcp import config

    root = config.documents() / "Maps" / "Download"
    seen, out = set(), []
    for p in sorted(root.rglob("*.w3x")) if root.is_dir() else []:
        if p.name.lower() not in seen:
            seen.add(p.name.lower())
            out.append(p)
    return out
```

- [ ] **Step 2: Write the failing test**

`tests/test_pathguard.py`:
```python
import pytest

from wc3mcp import pathguard
from wc3mcp.errors import ToolError


def test_refuses_paths_inside_install(monkeypatch, tmp_path):
    root = tmp_path / "Warcraft III"
    monkeypatch.setenv("WC3MCP_INSTALL", str(root))
    for p in (root, root / "_retail_" / "x.w3x", root / "sub" / ".." / "Data" / "y"):
        with pytest.raises(ToolError) as e:
            pathguard.ensure_writable(p)
        assert e.value.code == "install_read_only"


def test_install_check_ignores_case(monkeypatch, tmp_path):
    root = tmp_path / "Warcraft III"
    monkeypatch.setenv("WC3MCP_INSTALL", str(root))
    with pytest.raises(ToolError):
        pathguard.ensure_writable(str(root).upper() + "\\Maps\\a.w3x")


def test_allows_paths_outside_install(monkeypatch, tmp_path):
    monkeypatch.setenv("WC3MCP_INSTALL", str(tmp_path / "Warcraft III"))
    assert pathguard.ensure_writable(tmp_path / "Warcraft III2" / "a.w3x").name == "a.w3x"


def test_tool_error_to_dict():
    e = ToolError("bad", "msg", hint="h", op_index=2)
    assert e.to_dict() == {"code": "bad", "message": "msg", "hint": "h", "details": {"op_index": 2}}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `& $PY -m pytest tests/test_pathguard.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wc3mcp.pathguard'`

- [ ] **Step 4: Write minimal implementation**

`src/wc3mcp/config.py`:
```python
"""Filesystem locations. Environment overrides keep tests away from real user data."""
import ctypes
import os
from pathlib import Path


def install_root() -> Path:
    return Path(os.environ.get("WC3MCP_INSTALL", r"D:\Warcraft III"))


def home() -> Path:
    return Path(os.environ.get("WC3MCP_HOME") or Path(os.environ["LOCALAPPDATA"]) / "wc3mcp")


def documents() -> Path:
    if env := os.environ.get("WC3MCP_DOCUMENTS"):
        return Path(env)
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)  # CSIDL_PERSONAL (follows OneDrive redirection)
    return Path(buf.value) / "Warcraft III"
```

`src/wc3mcp/errors.py`:
```python
class ToolError(Exception):
    """An expected, user-facing failure with a stable code and an optional hint."""

    def __init__(self, code: str, message: str, hint: str | None = None, **details):
        super().__init__(message)
        self.code, self.message, self.hint, self.details = code, message, hint, details

    def to_dict(self) -> dict:
        d = {"code": self.code, "message": self.message}
        if self.hint:
            d["hint"] = self.hint
        if self.details:
            d["details"] = self.details
        return d
```

`src/wc3mcp/pathguard.py`:
```python
from pathlib import Path

from . import config
from .errors import ToolError


def ensure_writable(path) -> Path:
    """Resolve `path` and refuse it if it lies inside the game install (read-only by design)."""
    p = Path(path).resolve()
    root = config.install_root().resolve()
    if p == root or root in p.parents:  # WindowsPath comparisons are case-insensitive
        raise ToolError("install_read_only", f"refusing to write inside the game install: {p}",
                        hint="save under Documents\\Warcraft III\\Maps or another folder")
    return p
```

- [ ] **Step 5: Run test to verify it passes**

Run: `& $PY -m pytest tests/test_pathguard.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore src tests
git commit -m "feat: project scaffold, config, errors, install path guard" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

### Task 2: MPQ crypto

**Files:**
- Create: `src/wc3mcp/mpq/__init__.py` (empty docstring module), `src/wc3mcp/mpq/crypto.py`
- Test: `tests/mpq/test_crypto.py`

**Interfaces:**
- Produces: `M = 0xFFFFFFFF`; `CRYPT: tuple[int, ...]`; `HASH_OFFSET, HASH_A, HASH_B, HASH_KEY = 0, 1, 2, 3`; `hash_string(name: str | bytes, htype: int) -> int`; `decrypt(data: bytes, key: int) -> bytes`; `encrypt(data: bytes, key: int) -> bytes`; `file_key(name: str, block_pos: int, fsize: int, fix_key: bool) -> int`; `detect_sector_key(enc: bytes, sector_size: int, first_offset: int) -> int | None`.

- [ ] **Step 1: Write the failing test**

`src/wc3mcp/mpq/__init__.py`:
```python
"""MPQ archives (Warcraft III maps and campaigns)."""
```

`tests/mpq/test_crypto.py`:
```python
import struct

from wc3mcp.mpq.crypto import (HASH_A, HASH_B, HASH_KEY, M, decrypt, detect_sector_key, encrypt,
                               file_key, hash_string)


def test_known_table_keys():
    assert hash_string("(hash table)", HASH_KEY) == 0xC3AF3770
    assert hash_string("(block table)", HASH_KEY) == 0xEC83B3A3


def test_hash_ignores_case_and_slash_style():
    assert hash_string("war3map.J", HASH_A) == hash_string("WAR3MAP.j", HASH_A)
    assert hash_string("a/b.txt", HASH_B) == hash_string("A\\B.TXT", HASH_B)


def test_encrypt_decrypt_roundtrip_keeps_tail_bytes():
    data = bytes(range(256)) * 3 + b"xyz"
    enc = encrypt(data, 0x12345678)
    assert enc != data and enc[-3:] == b"xyz"
    assert decrypt(enc, 0x12345678) == data


def test_file_key_uses_basename_and_fix_key():
    plain = file_key("dir\\war3map.j", 100, 50, fix_key=False)
    assert plain == hash_string("war3map.j", HASH_KEY)
    assert file_key("war3map.j", 100, 50, fix_key=True) == ((plain + 100) ^ 50) & M


def test_detect_sector_key_recovers_file_key():
    key = file_key("war3mapImported\\x.blp", 0x1234, 10000, fix_key=True)
    table = struct.pack("<4I", 16, 900, 1800, 2400)  # 3 sectors: first offset = (3 + 1) * 4
    enc = encrypt(table, (key - 1) & M)
    assert detect_sector_key(enc, 4096, 16) == key
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& $PY -m pytest tests/mpq/test_crypto.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wc3mcp.mpq.crypto'`

- [ ] **Step 3: Write minimal implementation**

`src/wc3mcp/mpq/crypto.py`:
```python
"""Storm hashing and encryption used by MPQ archives."""
import struct

M = 0xFFFFFFFF
HASH_OFFSET, HASH_A, HASH_B, HASH_KEY = 0, 1, 2, 3


def _crypt_table() -> tuple[int, ...]:
    t = [0] * 0x500
    seed = 0x00100001
    for i in range(0x100):
        idx = i
        for _ in range(5):
            seed = (seed * 125 + 3) % 0x2AAAAB
            hi = (seed & 0xFFFF) << 16
            seed = (seed * 125 + 3) % 0x2AAAAB
            t[idx] = hi | (seed & 0xFFFF)
            idx += 0x100
    return tuple(t)


CRYPT = _crypt_table()


def hash_string(name: str | bytes, htype: int) -> int:
    """Storm HashString: ASCII-uppercased, '/' treated as '\\'."""
    raw = name.encode("utf-8") if isinstance(name, str) else name
    s1, s2 = 0x7FED7FED, 0xEEEEEEEE
    for ch in raw.replace(b"/", b"\\").upper():
        s1 = CRYPT[(htype << 8) + ch] ^ ((s1 + s2) & M)
        s2 = (ch + s1 + s2 + (s2 << 5) + 3) & M
    return s1


def _next_key(key: int) -> int:
    return ((((~key) << 0x15) + 0x11111111) & M) | (key >> 0x0B)


def decrypt(data: bytes, key: int) -> bytes:
    n = len(data) // 4
    out, seed = [], 0xEEEEEEEE
    for w in struct.unpack_from(f"<{n}I", data):
        seed = (seed + CRYPT[0x400 + (key & 0xFF)]) & M
        c = w ^ ((key + seed) & M)
        out.append(c)
        key = _next_key(key)
        seed = (c + seed + (seed << 5) + 3) & M
    return struct.pack(f"<{n}I", *out) + bytes(data[n * 4:])


def encrypt(data: bytes, key: int) -> bytes:
    n = len(data) // 4
    out, seed = [], 0xEEEEEEEE
    for c in struct.unpack_from(f"<{n}I", data):
        seed = (seed + CRYPT[0x400 + (key & 0xFF)]) & M
        out.append(c ^ ((key + seed) & M))
        key = _next_key(key)
        seed = (c + seed + (seed << 5) + 3) & M
    return struct.pack(f"<{n}I", *out) + bytes(data[n * 4:])


def file_key(name: str, block_pos: int, fsize: int, fix_key: bool) -> int:
    key = hash_string(name.replace("/", "\\").rsplit("\\", 1)[-1], HASH_KEY)
    return ((key + block_pos) ^ fsize) & M if fix_key else key


def detect_sector_key(enc: bytes, sector_size: int, first_offset: int) -> int | None:
    """Recover the file key of an encrypted sector offset table whose first entry is known
    (StormLib DetectFileKeyBySectorSize). The table is encrypted with key - 1."""
    e0, e1 = struct.unpack_from("<2I", enc)
    k1k2 = ((e0 ^ first_offset) - 0xEEEEEEEE) & M
    for i in range(0x100):
        key = (k1k2 - CRYPT[0x400 + i]) & M
        seed = (0xEEEEEEEE + CRYPT[0x400 + (key & 0xFF)]) & M
        if e0 ^ ((key + seed) & M) != first_offset:
            continue
        nkey = _next_key(key)
        seed = (first_offset + seed + (seed << 5) + 3) & M
        seed = (seed + CRYPT[0x400 + (nkey & 0xFF)]) & M
        if e1 ^ ((nkey + seed) & M) <= first_offset + sector_size:
            return (key + 1) & M
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `& $PY -m pytest tests/mpq/test_crypto.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/wc3mcp/mpq tests/mpq/test_crypto.py
git commit -m "feat(mpq): storm hashing, encryption, sector key detection" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

### Task 3: MPQ reader and name recovery

**Files:**
- Create: `src/wc3mcp/mpq/names.py`, `src/wc3mcp/mpq/reader.py`
- Test: `tests/mpq/test_reader.py`

**Interfaces:**
- Consumes: Task 2 `crypto` functions.
- Produces:
  - `names.LOCALES: tuple[str, ...]`, `names.KNOWN_NAMES: tuple[str, ...]`, `names.recover_names(archive) -> list[str]` (duck-typed archive with `listfile_names()`, `read(name)`, `find(name)`; returns existing names with `\` separators).
  - `reader` constants `F_IMPLODE F_COMPRESS F_ENCRYPTED F_FIX_KEY F_SINGLE_UNIT F_SECTOR_CRC F_EXISTS HASH_EMPTY HASH_DELETED MAX_FILE_SIZE`; `MpqError`; `HashEntry(index, name_a, name_b, locale, platform, block)`; `Block(pos, csize, fsize, flags)`; `Archive(data: bytes, path=None)` / `Archive.open(path)` with `.offset .prefix .sector_size .format_version .hashes .blocks .problems`, `.find(name) -> HashEntry | None`, `.read(name) -> bytes | None`, `.read_block(index, key: int | None) -> bytes`, `.listfile_names() -> list[str]`, `.list() -> list[str]`, `.unnamed_entries(names) -> list[HashEntry]`.

- [ ] **Step 1: Write the failing test**

`tests/mpq/test_reader.py`:
```python
import struct
import zlib

import pytest

from corpus import ladder_maps
from wc3mcp.mpq.reader import Archive, MpqError

MAPS = ladder_maps()


def test_rejects_data_without_header():
    with pytest.raises(MpqError):
        Archive(b"not an mpq" * 100)


@pytest.mark.skipif(not MAPS, reason="no ladder maps in Documents")
@pytest.mark.parametrize("path", MAPS, ids=lambda p: p.name)
def test_ladder_map_files_match_attribute_crcs(path):
    arc = Archive.open(path)
    attrs = arc.read("(attributes)")
    version, flags = struct.unpack_from("<2I", attrs)
    assert (version, flags & 1) == (100, 1)
    crcs = struct.unpack_from(f"<{len(arc.blocks)}I", attrs, 8)
    names = arc.list()
    assert "war3map.w3i" in names and not arc.unnamed_entries(names)
    for name in names:
        entry = arc.find(name)
        data = arc.read(name)
        assert len(data) == arc.blocks[entry.block].fsize
        if name != "(attributes)":
            assert zlib.crc32(data) == crcs[entry.block], name
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& $PY -m pytest tests/mpq/test_reader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wc3mcp.mpq.reader'`

- [ ] **Step 3: Write minimal implementation**

`src/wc3mcp/mpq/names.py`:
```python
"""Known Warcraft III archive names and name recovery for maps without a complete (listfile)."""
import re

LOCALES = ("deDE", "enUS", "esES", "esMX", "frFR", "itIT", "jaJP", "koKR", "plPL", "ptBR", "ruRU", "thTH",
           "zhCN", "zhTW")

_BASE = """(listfile) (attributes) (signature) (user data)
war3map.j scripts\\war3map.j war3map.lua scripts\\war3map.lua war3map.w3e war3map.w3i war3map.wtg war3map.wct
war3map.wts war3map.shd war3map.wpm war3map.doo war3mapUnits.doo war3map.w3r war3map.w3c war3map.w3s
war3map.w3u war3map.w3t war3map.w3b war3map.w3d war3map.w3a war3map.w3h war3map.w3q war3map.w3o
war3mapSkin.w3u war3mapSkin.w3t war3mapSkin.w3b war3mapSkin.w3d war3mapSkin.w3a war3mapSkin.w3h war3mapSkin.w3q
war3map.imp war3map.mmp war3mapMap.blp war3mapMap.b00 war3mapMap.tga war3mapPreview.tga war3mapPreview.blp
war3mapPath.tga war3mapMisc.txt war3mapSkin.txt war3mapExtra.txt war3map.wai conversation.json
war3campaign.w3u war3campaign.w3t war3campaign.w3a war3campaign.w3b war3campaign.w3d war3campaign.w3q
war3campaign.w3h war3campaign.w3f war3campaign.imp war3campaign.wts war3campaignSkin.txt war3campaignMisc.txt"""

KNOWN_NAMES = tuple(_BASE.split()) + tuple(f"_Locales\\{loc}.w3mod\\war3map.wts" for loc in LOCALES)

_ASSET = re.compile(rb"[A-Za-z0-9_\-. \\/]{1,200}\.(?:mdx|mdl|blp|dds|tga|jpg|png|wav|mp3|flac|ogg|txt|slk|fdf"
                    rb"|toc|ai|j|lua|json)", re.I)


def _try_read(archive, name: str) -> bytes | None:
    try:
        return archive.read(name)
    except Exception:  # corrupt helper files must not block recovery
        return None


def _import_paths(imp: bytes) -> list[str]:
    count = int.from_bytes(imp[4:8], "little")
    pos, out = 8, []
    for _ in range(min(count, 100_000)):
        end = imp.find(b"\0", pos + 1)
        if pos >= len(imp) or end < 0:
            break
        path = imp[pos + 1:end].decode("utf-8", "replace").replace("/", "\\")
        out += [path, "war3mapImported\\" + path]
        pos = end + 1
    return out


def recover_names(archive) -> list[str]:
    """Names that exist in `archive`, from (listfile), known names, the import list and script string literals."""
    candidates = list(archive.listfile_names()) + list(KNOWN_NAMES)
    imp = _try_read(archive, "war3map.imp")
    if imp and len(imp) >= 8:
        candidates += _import_paths(imp)
    for script in ("war3map.j", "scripts\\war3map.j", "war3map.lua", "scripts\\war3map.lua"):
        for m in _ASSET.finditer(_try_read(archive, script) or b""):
            candidates.append(m.group().decode("latin-1").strip().replace("\\\\", "\\"))
    seen, out = set(), []
    for name in (c.replace("/", "\\") for c in candidates):
        key = name.upper()
        if key not in seen and archive.find(name) is not None:
            seen.add(key)
            out.append(name)
    return out
```

`src/wc3mcp/mpq/reader.py`:
```python
"""Tolerant read-only MPQ access (protected Warcraft III maps included)."""
import bz2
import struct
import zlib
from dataclasses import dataclass

from .crypto import HASH_A, HASH_B, HASH_KEY, HASH_OFFSET, M, decrypt, file_key, hash_string
from .names import recover_names

F_IMPLODE = 0x00000100
F_COMPRESS = 0x00000200
F_ENCRYPTED = 0x00010000
F_FIX_KEY = 0x00020000
F_SINGLE_UNIT = 0x01000000
F_SECTOR_CRC = 0x04000000
F_EXISTS = 0x80000000
HASH_EMPTY, HASH_DELETED = 0xFFFFFFFF, 0xFFFFFFFE
MAX_FILE_SIZE = 512 * 1024 * 1024


class MpqError(Exception):
    pass


@dataclass(frozen=True)
class HashEntry:
    index: int
    name_a: int
    name_b: int
    locale: int
    platform: int
    block: int


@dataclass(frozen=True)
class Block:
    pos: int
    csize: int
    fsize: int
    flags: int


class Archive:
    def __init__(self, data: bytes, path: str | None = None):
        self.data, self.path, self.problems = data, path, []
        self.offset = self._find_header()
        (_, self.archive_size, self.format_version, shift, hash_pos, block_pos, hash_n,
         block_n) = struct.unpack_from("<IIHHIIII", data, self.offset + 4)
        self.sector_size = 512 << (shift & 0x1F)
        self.hashes = [HashEntry(i, a, b, c & 0xFFFF, c >> 16, blk)
                       for i, (a, b, c, blk) in enumerate(self._table(hash_pos, hash_n, "(hash table)"))]
        self.blocks = [Block(*e) for e in self._table(block_pos, block_n, "(block table)")]

    @classmethod
    def open(cls, path) -> "Archive":
        with open(path, "rb") as f:
            return cls(f.read(), str(path))

    @property
    def prefix(self) -> bytes:
        """Bytes before the MPQ header (e.g. a 512-byte HM3W map header)."""
        return self.data[:self.offset]

    def _find_header(self) -> int:
        d = self.data
        for off in range(0, len(d) - 31, 0x200):
            magic = d[off:off + 4]
            if magic == b"MPQ\x1b":  # user-data header points at the real one
                real = off + struct.unpack_from("<I", d, off + 8)[0]
                if d[real:real + 4] == b"MPQ\x1a":
                    return real
            if magic == b"MPQ\x1a":
                return off
        raise MpqError("no MPQ header found")

    def _table(self, pos: int, count: int, key_name: str) -> list[tuple[int, int, int, int]]:
        start = (self.offset + pos) & M
        n = max(0, min(count, (len(self.data) - start) // 16))
        if n < count:
            self.problems.append(f"{key_name}: {count} entries declared, {n} present")
        raw = decrypt(self.data[start:start + n * 16], hash_string(key_name, HASH_KEY))
        return [struct.unpack_from("<4I", raw, i * 16) for i in range(n)]

    def _live(self, e: HashEntry) -> bool:
        return e.block < len(self.blocks) and bool(self.blocks[e.block].flags & F_EXISTS)

    def find(self, name: str) -> HashEntry | None:
        n = len(self.hashes)
        if not n:
            return None
        a, b = hash_string(name, HASH_A), hash_string(name, HASH_B)
        if n & (n - 1) == 0:  # regular table: probe like the game does
            i = start = hash_string(name, HASH_OFFSET) & (n - 1)
            while self.hashes[i].block != HASH_EMPTY:
                e = self.hashes[i]
                if e.name_a == a and e.name_b == b and self._live(e):
                    return e
                i = (i + 1) & (n - 1)
                if i == start:
                    break
        # ponytail: full scan for tables broken by map protectors; O(n) per miss, map tables are small
        return next((e for e in self.hashes if e.name_a == a and e.name_b == b and self._live(e)), None)

    def read(self, name: str) -> bytes | None:
        e = self.find(name)
        if e is None:
            return None
        blk = self.blocks[e.block]
        key = file_key(name, blk.pos, blk.fsize, bool(blk.flags & F_FIX_KEY)) if blk.flags & F_ENCRYPTED else None
        return self.read_block(e.block, key)

    def read_block(self, index: int, key: int | None) -> bytes:
        blk = self.blocks[index]
        if blk.fsize > MAX_FILE_SIZE:
            raise MpqError(f"block {index}: size {blk.fsize} exceeds {MAX_FILE_SIZE}")
        if blk.fsize == 0:
            return b""
        if blk.flags & F_ENCRYPTED and key is None:
            raise MpqError(f"block {index}: encrypted and its key is unknown")
        start = (self.offset + blk.pos) & M
        compressed = bool(blk.flags & (F_COMPRESS | F_IMPLODE))
        if blk.flags & F_SINGLE_UNIT:
            raw = self.data[start:start + blk.csize]
            if key is not None:
                raw = decrypt(raw, key)
            if compressed and blk.csize < blk.fsize:
                raw = self._decompress(raw, blk.fsize, blk.flags)
            return bytes(raw[:blk.fsize])
        ss = self.sector_size
        n = (blk.fsize + ss - 1) // ss
        if compressed:
            tbl = self.data[start:start + (n + 1) * 4]
            if len(tbl) < (n + 1) * 4:
                raise MpqError(f"block {index}: sector table past end of file")
            if key is not None:
                tbl = decrypt(tbl, (key - 1) & M)
            offs = struct.unpack(f"<{n + 1}I", tbl)
        else:
            offs = [i * ss for i in range(n)] + [blk.fsize]
        out = []
        for i in range(n):
            expect = min(ss, blk.fsize - i * ss)
            lo, hi = offs[i], offs[i + 1]
            chunk = self.data[start + lo:start + hi] if hi >= lo else b""
            if key is not None:
                chunk = decrypt(chunk, (key + i) & M)
            if compressed and len(chunk) < expect:
                chunk = self._decompress(chunk, expect, blk.flags)
            if len(chunk) < expect:
                self.problems.append(f"block {index} sector {i}: short by {expect - len(chunk)} bytes, zero-filled")
            out.append(bytes(chunk[:expect]).ljust(expect, b"\0"))
        return b"".join(out)

    def _decompress(self, buf: bytes, expect: int, flags: int) -> bytes:
        if not buf:
            self.problems.append("zero-length compressed unit, zero-filled")
            return bytes(expect)
        if flags & F_IMPLODE and not flags & F_COMPRESS:
            raise MpqError("PKWARE implode compression is not supported")
        mask, data = buf[0], buf[1:]
        if mask & ~0x12:
            raise MpqError(f"unsupported compression mask {mask:#04x}")
        if mask & 0x10:
            data = bz2.BZ2Decompressor().decompress(data, max_length=expect)
        if mask & 0x02:
            data = zlib.decompressobj().decompress(data, expect)  # bounded: no decompression bombs
        return data

    def listfile_names(self) -> list[str]:
        raw = self.read("(listfile)") or b""
        return [n.strip() for n in raw.decode("utf-8", "replace").replace(";", "\n").splitlines() if n.strip()]

    def list(self) -> list[str]:
        return recover_names(self)

    def unnamed_entries(self, names) -> list[HashEntry]:
        named = {e.index for e in map(self.find, names) if e is not None}
        return [e for e in self.hashes if self._live(e) and e.index not in named]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `& $PY -m pytest tests/mpq/test_reader.py -v`
Expected: all passed (1 unit test + one per distinct ladder map, ~130), or the corpus test skipped if Documents has no maps.

- [ ] **Step 5: Commit**

```bash
git add src/wc3mcp/mpq tests/mpq/test_reader.py
git commit -m "feat(mpq): tolerant archive reader with name recovery" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

### Task 4: MPQ writer (editor-style output, unnamed-entry preservation)

**Files:**
- Create: `src/wc3mcp/mpq/writer.py`
- Test: `tests/mpq/test_writer.py`, `tests/mpq/test_names.py`

**Interfaces:**
- Consumes: Task 2 `crypto`; Task 3 `reader` (`Archive`, `HashEntry`, flags, `HASH_EMPTY`, `HASH_DELETED`, `MpqError`), `names.recover_names`.
- Produces: `SPECIAL = ("(listfile)", "(attributes)")`; `RawEntry(hash_index, name_a, name_b, locale, platform, data, fsize, flags, src_pos, key)`; `capture_unnamed(archive: Archive, entry: HashEntry) -> RawEntry`; `write_archive(files: dict[str, bytes], *, preserved: tuple[RawEntry, ...] = (), prefix: bytes = b"", hash_size: int | None = None, reserved_slots: frozenset[int] = frozenset(), sector_size: int = 4096, encrypt_names: frozenset[str] = frozenset(), listfile: bool = True) -> bytes`.
- Rules: when `preserved` is non-empty the caller must pass the source `hash_size`, `reserved_slots` (indices of every non-empty source hash slot) and source `sector_size`.

- [ ] **Step 1: Write the failing tests**

`tests/mpq/test_writer.py`:
```python
import os
import struct
import zlib

import pytest

from corpus import ladder_maps
from wc3mcp.mpq.reader import HASH_EMPTY, Archive, MpqError
from wc3mcp.mpq.writer import SPECIAL, capture_unnamed, write_archive


def test_roundtrip_edge_sizes():
    files = {"war3map.j": b"function main takes nothing returns nothing\nendfunction\n" * 200,
             "empty.txt": b"", "exact.bin": bytes(range(256)) * 16, "over.bin": b"\x01" * 4097,
             "war3mapImported\\noise.bin": os.urandom(10_000)}
    arc = Archive(write_archive(files))
    assert (arc.offset, arc.format_version, arc.sector_size) == (0, 0, 4096)
    for name, data in files.items():
        assert arc.read(name) == data
    assert sorted(arc.listfile_names()) == sorted(files)


def test_flags_and_attributes_match_editor_saves():
    data = b"hello" * 1000
    arc = Archive(write_archive({"a.txt": data}))
    assert arc.blocks[arc.find("a.txt").block].flags == 0x80000200
    for name in SPECIAL:
        assert arc.blocks[arc.find(name).block].flags == 0x80030200
    attrs = arc.read("(attributes)")
    crcs = struct.unpack_from(f"<{len(arc.blocks)}I", attrs, 8)
    assert struct.unpack_from("<2I", attrs) == (100, 1) and len(attrs) == 8 + 4 * len(arc.blocks)
    assert crcs[arc.find("a.txt").block] == zlib.crc32(data)
    assert crcs[arc.find("(listfile)").block] == zlib.crc32(arc.read("(listfile)"))
    assert crcs[arc.find("(attributes)").block] == 0


@pytest.mark.parametrize("count", [1, 30, 31, 100])
def test_hash_table_is_power_of_two_and_large_enough(count):
    arc = Archive(write_archive({f"f{i}.txt": b"x" for i in range(count)}))
    size = len(arc.hashes)
    assert size & (size - 1) == 0 and size >= count + 2


def test_prefix_is_kept():
    prefix = b"HM3W" + bytes(508)
    data = write_archive({"a": b"1"}, prefix=prefix)
    assert data[:512] == prefix and Archive(data).offset == 512 and Archive(data).read("a") == b"1"


def test_encrypt_names_and_no_listfile():
    arc = Archive(write_archive({"secret.txt": b"s" * 5000}, encrypt_names=frozenset({"secret.txt"}),
                                listfile=False))
    assert arc.read("secret.txt") == b"s" * 5000
    assert arc.find("(listfile)") is None
    assert arc.blocks[arc.find("secret.txt").block].flags == 0x80030200


def test_unnamed_entries_survive_repacking():
    files = {f"known{i}.txt": f"k{i}".encode() * 2000 for i in range(4)}
    hidden = {"hidden\\plain.txt": b"plain" * 900, "hidden\\secret.txt": b"secret" * 900}
    src = Archive(write_archive(files | hidden, encrypt_names=frozenset({"hidden\\secret.txt"}), listfile=False))
    unnamed = src.unnamed_entries(list(files) + ["(attributes)"])
    assert len(unnamed) == 2
    out = Archive(write_archive(
        {"new\\big.bin": os.urandom(50_000)},
        preserved=tuple(capture_unnamed(src, e) for e in unnamed),
        hash_size=len(src.hashes),
        reserved_slots=frozenset(e.index for e in src.hashes if e.block != HASH_EMPTY),
        sector_size=src.sector_size))
    for name, data in hidden.items():
        assert out.read(name) == data


def test_rejects_overfull_fixed_table():
    with pytest.raises(MpqError):
        write_archive({f"f{i}": b"x" for i in range(10)}, hash_size=8)


MAPS = ladder_maps()


@pytest.mark.skipif(not MAPS, reason="no ladder maps in Documents")
@pytest.mark.parametrize("path", MAPS[:25], ids=lambda p: p.name)  # ponytail: 25 keeps the suite fast; reader test covers all
def test_ladder_maps_repack_losslessly(path):
    src = Archive.open(path)
    files = {n: src.read(n) for n in src.list() if n not in SPECIAL}
    out = Archive(write_archive(files, prefix=src.prefix, sector_size=src.sector_size))
    assert {n: out.read(n) for n in files} == files
```

`tests/mpq/test_names.py`:
```python
import struct

from wc3mcp.mpq.names import recover_names
from wc3mcp.mpq.reader import Archive
from wc3mcp.mpq.writer import write_archive


def test_recovers_names_without_listfile():
    files = {
        "war3map.w3i": b"info",
        "_Locales\\deDE.w3mod\\war3map.wts": b"STRING 1",
        "war3map.j": b'call AddSpecialEffect("war3mapImported\\\\fx.mdx", 0, 0)\n',
        "war3mapImported\\fx.mdx": b"MDLX",
        "war3mapImported\\icon.blp": b"BLP1",
        "war3map.imp": struct.pack("<II", 1, 1) + b"\x0dicon.blp\x00",
        "unreferenced\\x.txt": b"lost",
    }
    arc = Archive(write_archive(files, listfile=False))
    names = set(recover_names(arc))
    assert set(files) - {"unreferenced\\x.txt"} <= names
    assert "unreferenced\\x.txt" not in names
    assert len(arc.unnamed_entries(names)) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& $PY -m pytest tests/mpq/test_writer.py tests/mpq/test_names.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wc3mcp.mpq.writer'`

- [ ] **Step 3: Write minimal implementation**

`src/wc3mcp/mpq/writer.py`:
```python
"""Write MPQ archives the way the World Editor saves maps: v0 header at the start, zlib sectors,
encrypted (listfile)/(attributes), CRC32 attributes table."""
import struct
import zlib
from dataclasses import dataclass

from .crypto import HASH_A, HASH_B, HASH_KEY, HASH_OFFSET, M, decrypt, detect_sector_key, encrypt, file_key, hash_string
from .reader import (F_COMPRESS, F_ENCRYPTED, F_EXISTS, F_FIX_KEY, F_SECTOR_CRC, F_SINGLE_UNIT, HASH_DELETED,
                     HASH_EMPTY, Archive, HashEntry, MpqError)

SPECIAL = ("(listfile)", "(attributes)")
_EMPTY_SLOT = struct.pack("<IIHHI", M, M, 0xFFFF, 0xFFFF, HASH_EMPTY)
_DELETED_SLOT = struct.pack("<IIHHI", M, M, 0xFFFF, 0xFFFF, HASH_DELETED)


@dataclass(frozen=True)
class RawEntry:
    """A file whose name is unknown, carried over from a source archive without decoding."""
    hash_index: int
    name_a: int
    name_b: int
    locale: int
    platform: int
    data: bytes       # stored bytes exactly as in the source
    fsize: int
    flags: int
    src_pos: int
    key: int | None   # file key at src_pos when encrypted and recoverable


def capture_unnamed(archive: Archive, entry: HashEntry) -> RawEntry:
    blk = archive.blocks[entry.block]
    start = (archive.offset + blk.pos) & M
    key = None
    if blk.flags & F_ENCRYPTED and blk.flags & F_COMPRESS and not blk.flags & F_SINGLE_UNIT and blk.fsize:
        n = (blk.fsize + archive.sector_size - 1) // archive.sector_size
        first = (n + 1 + (1 if blk.flags & F_SECTOR_CRC else 0)) * 4
        key = detect_sector_key(archive.data[start:start + 8], archive.sector_size, first)
    return RawEntry(entry.index, entry.name_a, entry.name_b, entry.locale, entry.platform,
                    archive.data[start:start + blk.csize], blk.fsize, blk.flags, blk.pos, key)


def _relocate(e: RawEntry, new_pos: int, sector_size: int) -> bytes:
    """Stored bytes of `e` valid at `new_pos` (FIX_KEY encryption depends on the block position)."""
    if not (e.flags & F_ENCRYPTED and e.flags & F_FIX_KEY) or e.fsize == 0 or new_pos == e.src_pos:
        return e.data
    if e.key is None or e.flags & (F_SINGLE_UNIT | F_SECTOR_CRC) or not e.flags & F_COMPRESS:
        raise MpqError(f"cannot move encrypted unnamed file in hash slot {e.hash_index}: key not recoverable")
    new_key = ((((e.key ^ e.fsize) - e.src_pos) + new_pos) & M) ^ e.fsize
    n = (e.fsize + sector_size - 1) // sector_size
    table = struct.unpack(f"<{n + 1}I", decrypt(e.data[:(n + 1) * 4], (e.key - 1) & M))
    out = bytearray(e.data)
    out[:(n + 1) * 4] = encrypt(struct.pack(f"<{n + 1}I", *table), (new_key - 1) & M)
    for i in range(n):
        lo, hi = table[i], table[i + 1]
        if not lo <= hi <= len(e.data):
            raise MpqError(f"unnamed file in hash slot {e.hash_index}: bad sector table")
        out[lo:hi] = encrypt(decrypt(e.data[lo:hi], (e.key + i) & M), (new_key + i) & M)
    return bytes(out)


def _store(data: bytes, pos: int, sector_size: int, key_name: str | None) -> tuple[bytes, int]:
    if not data:
        return b"", F_EXISTS
    n = (len(data) + sector_size - 1) // sector_size
    sectors = []
    for i in range(n):
        raw = data[i * sector_size:(i + 1) * sector_size]
        z = zlib.compress(raw, 9)
        sectors.append(b"\x02" + z if len(z) + 1 < len(raw) else raw)
    offsets = [(n + 1) * 4]
    for s in sectors:
        offsets.append(offsets[-1] + len(s))
    table = struct.pack(f"<{n + 1}I", *offsets)
    flags = F_EXISTS | F_COMPRESS
    if key_name is not None:
        key = file_key(key_name, pos, len(data), fix_key=True)
        table = encrypt(table, (key - 1) & M)
        sectors = [encrypt(s, (key + i) & M) for i, s in enumerate(sectors)]
        flags |= F_ENCRYPTED | F_FIX_KEY
    return table + b"".join(sectors), flags


def write_archive(files: dict[str, bytes], *, preserved: tuple[RawEntry, ...] = (), prefix: bytes = b"",
                  hash_size: int | None = None, reserved_slots: frozenset[int] = frozenset(),
                  sector_size: int = 4096, encrypt_names: frozenset[str] = frozenset(),
                  listfile: bool = True) -> bytes:
    if len(prefix) % 0x200:
        raise MpqError("prefix length must be a multiple of 512")
    if sector_size < 512 or sector_size & (sector_size - 1):
        raise MpqError("sector size must be a power of two >= 512")
    names = [n for n in files if n not in SPECIAL]
    count = len(names) + len(preserved) + (2 if listfile else 1)
    if hash_size is None:
        hash_size = max(4, 1 << (count - 1).bit_length())
    if hash_size & (hash_size - 1) or hash_size < count:
        raise MpqError(f"hash table of {hash_size} slots cannot hold {count} files")

    body = bytearray(32)  # header written last
    blocks: list[tuple[int, int, int, int]] = []
    crcs: list[int] = []
    slots: list[bytes | None] = [None] * hash_size

    for e in preserved:  # original slots first so their probe chains stay valid
        if e.hash_index >= hash_size or slots[e.hash_index] is not None:
            raise MpqError(f"hash slot {e.hash_index} unusable for a preserved file")
        pos = len(body)
        body.extend(_relocate(e, pos, sector_size))
        slots[e.hash_index] = struct.pack("<IIHHI", e.name_a, e.name_b, e.locale, e.platform, len(blocks))
        blocks.append((pos, len(body) - pos, e.fsize, e.flags))
        crcs.append(0)

    def add(name: str, data: bytes, encrypted: bool) -> None:
        pos = len(body)
        stored, flags = _store(data, pos, sector_size, name if encrypted else None)
        body.extend(stored)
        i = hash_string(name, HASH_OFFSET) & (hash_size - 1)
        while slots[i] is not None:
            i = (i + 1) & (hash_size - 1)
        slots[i] = struct.pack("<IIHHI", hash_string(name, HASH_A), hash_string(name, HASH_B), 0, 0, len(blocks))
        blocks.append((pos, len(stored), len(data), flags))
        crcs.append(zlib.crc32(data))

    for name in names:
        add(name, files[name], name in encrypt_names)
    if listfile:
        add("(listfile)", "".join(n + "\r\n" for n in names).encode("utf-8"), True)
    attributes = struct.pack(f"<II{len(crcs) + 1}I", 100, 1, *crcs, 0)  # the attributes entry itself stores 0
    add("(attributes)", attributes, True)

    hash_pos = len(body)
    table = b"".join(s if s is not None else (_DELETED_SLOT if i in reserved_slots else _EMPTY_SLOT)
                     for i, s in enumerate(slots))
    body.extend(encrypt(table, hash_string("(hash table)", HASH_KEY)))
    block_pos = len(body)
    body.extend(encrypt(b"".join(struct.pack("<4I", *b) for b in blocks), hash_string("(block table)", HASH_KEY)))
    shift = sector_size.bit_length() - 10  # sector size = 512 << shift
    struct.pack_into("<4sIIHHIIII", body, 0, b"MPQ\x1a", 32, len(body), 0, shift, hash_pos, block_pos,
                     hash_size, len(blocks))
    return prefix + bytes(body)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& $PY -m pytest tests/mpq -v`
Expected: all passed (crypto 5, reader 1 + per map, writer 9 + up to 25 maps, names 1).

- [ ] **Step 5: Commit**

```bash
git add src/wc3mcp/mpq/writer.py tests/mpq/test_writer.py tests/mpq/test_names.py
git commit -m "feat(mpq): editor-style archive writer preserving unnamed files" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

### Task 5: CASC reader (game data)

Port of the throwaway reader verified against build 3.0.0.24268 (MD5 of extracted files matched the root content keys).

**Files:**
- Create: `src/wc3mcp/casc/__init__.py`, `src/wc3mcp/casc/blte.py`, `src/wc3mcp/casc/storage.py`
- Test: `tests/casc/test_blte.py`, `tests/casc/test_storage.py`

**Interfaces:**
- Produces: `blte.lz4_block(src: bytes, dst: bytearray | None = None) -> bytearray`; `blte.blte_decode(data: bytes, stats: dict | None = None) -> bytes`; `blte.EncryptedChunk`; `storage.open_storage(root) -> Storage`; `Storage.build_name: str`, `.names() -> dict[str, tuple[str, list]]`, `.list(pattern: str = "") -> list[str]` (substring or glob, case-insensitive), `.read(path) -> bytes | None`, `.is_local(path) -> bool`, `.layers(hd=False, teen=False, locale="enUS", tileset=None, balance=None) -> list[str]`, `.resolve(relpath, **layer_kwargs) -> str | None`, `.norm(path) -> str`, `.root_info: dict[str, list[str]]`.

- [ ] **Step 1: Write the failing tests**

`src/wc3mcp/casc/__init__.py`:
```python
"""Read-only access to the local Warcraft III CASC storage."""
```

`tests/casc/test_blte.py`:
```python
import struct
import zlib

from wc3mcp.casc.blte import blte_decode, lz4_block


def frame(chunks: list[bytes]) -> bytes:
    table = b"".join(struct.pack(">II", len(c), 0) + bytes(16) for c in chunks)
    return (b"BLTE" + struct.pack(">I", 12 + 24 * len(chunks)) + b"\x0f" + len(chunks).to_bytes(3, "big")
            + table + b"".join(chunks))


def test_single_raw_chunk():
    assert blte_decode(b"BLTE\0\0\0\0Nhello") == b"hello"


def test_framed_raw_and_zlib_chunks():
    assert blte_decode(frame([b"Nabc", b"Z" + zlib.compress(b"def")])) == b"abcdef"


def test_lz4_block_with_overlapping_match():
    assert lz4_block(bytes([0x32]) + b"abc" + b"\x03\x00") == b"abcabcabc"
```

`tests/casc/test_storage.py`:
```python
import hashlib

import pytest

from corpus import INSTALL, needs_install
from wc3mcp.casc.storage import open_storage

pytestmark = needs_install


@pytest.fixture(scope="module")
def storage():
    return open_storage(INSTALL)


def test_reads_match_root_content_keys(storage):
    for path in ("War3.w3mod:Scripts/common.j", "war3.w3mod:units\\unitdata.slk",
                 "War3.w3mod:_Locales/enUS.w3mod:UI/TriggerStrings.txt"):
        data = storage.read(path)
        assert data and hashlib.md5(data).hexdigest() == storage.root_info[storage.norm(path)][1]


def test_list_glob_and_missing(storage):
    assert storage.list("*/common.j")
    assert storage.read("no/such/file") is None


def test_resolve_applies_locale_and_balance_layers(storage):
    assert storage.resolve("Units/UnitData.slk") == "War3.w3mod:Units/UnitData.slk"
    assert (storage.resolve("Units/UnitData.slk", balance="Custom_V1")
            == "War3.w3mod:_Balance/Custom_V1.w3mod:Units/UnitData.slk")
    assert (storage.resolve("Units/HumanUnitStrings.txt", locale="enUS")
            == "War3.w3mod:_Locales/enUS.w3mod:Units/HumanUnitStrings.txt")


def test_build_name(storage):
    assert storage.build_name.split(".")[0].isdigit()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& $PY -m pytest tests/casc -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wc3mcp.casc.blte'`

- [ ] **Step 3: Write minimal implementation**

`src/wc3mcp/casc/blte.py`:
```python
"""BLTE containers (Blizzard's chunked, optionally compressed file encoding)."""
import struct
import zlib


class EncryptedChunk(Exception):
    pass


def lz4_block(src: bytes, dst: bytearray | None = None) -> bytearray:
    """Decode one raw LZ4 block (no frame header)."""
    dst = bytearray() if dst is None else dst
    i, n = 0, len(src)
    while i < n:
        tok = src[i]
        i += 1
        lit = tok >> 4
        if lit == 15:
            while True:
                b = src[i]
                i += 1
                lit += b
                if b != 255:
                    break
        dst += src[i:i + lit]
        i += lit
        if i >= n:
            break
        off = src[i] | (src[i + 1] << 8)
        i += 2
        ml = tok & 15
        if ml == 15:
            while True:
                b = src[i]
                i += 1
                ml += b
                if b != 255:
                    break
        ml += 4
        start = len(dst) - off
        if off >= ml:
            dst += dst[start:start + ml]
        else:  # overlapping copy
            for k in range(ml):
                dst.append(dst[start + k])
    return dst


def blte_decode(data: bytes, stats: dict | None = None) -> bytes:
    if data[:4] != b"BLTE":
        raise ValueError("not BLTE")
    header_size = int.from_bytes(data[4:8], "big")
    if header_size == 0:  # single chunk, no frame table
        return _chunk(memoryview(data)[8:], stats)
    if data[8] != 0x0F:
        raise ValueError(f"bad BLTE flags {data[8]:#x}")
    count = int.from_bytes(data[9:12], "big")
    out, pos = [], header_size
    for k in range(count):
        encoded_size, _decoded_size = struct.unpack_from(">II", data, 12 + 24 * k)  # followed by a 16-byte MD5
        out.append(_chunk(memoryview(data)[pos:pos + encoded_size], stats))
        pos += encoded_size
    return b"".join(out)


def _chunk(mv: memoryview, stats: dict | None) -> bytes:
    mode = chr(mv[0])
    if stats is not None:
        stats[mode] = stats.get(mode, 0) + 1
    body = mv[1:]
    if mode == "N":
        return bytes(body)
    if mode == "Z":
        return zlib.decompress(body)
    if mode == "F":
        return blte_decode(bytes(body), stats)
    if mode == "4":
        # wowdev.wiki/BLTE: u8 version, u64be decoded size, u8 block shift, then u32be-sized LZ4 blocks.
        # ponytail: no local '4' chunk seen in 3.0.0.24268; covered only by the lz4_block unit test.
        decoded_size = int.from_bytes(body[1:9], "big")
        p, dst = 10, bytearray()
        while len(dst) < decoded_size and p < len(body):
            n = int.from_bytes(body[p:p + 4], "big")
            p += 4
            lz4_block(bytes(body[p:p + n]), dst)
            p += n
        return bytes(dst)
    if mode == "E":
        raise EncryptedChunk("encrypted BLTE chunk")
    raise ValueError(f"unknown BLTE mode {mode!r}")
```

`src/wc3mcp/casc/storage.py`:
```python
"""Local (installed) CASC storage reader. Layouts follow CascLib (CascIndexFiles.cpp, CascReadFile.cpp,
CascRootFile_TVFS.cpp) and wowdev.wiki TACT; verified against Warcraft III 3.0.0.24268.

Paths are returned as stored: '/' between folders, ':' when entering a nested VFS
(e.g. "War3.w3mod:_HD.w3mod:Units/Human/Footman/Footman.mdx"). Lookup is case-insensitive; '\\' == '/'."""
import bisect
import fnmatch
import os
import re
import struct

from .blte import blte_decode

ENTRY_HEADER = 30  # before "BLTE" in data.###: reversed EKey (16), u32 size, u16 flags, 2x u32 checksums


def _config(path) -> dict[str, list[str]]:
    d = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                d[k.strip()] = v.split()
    return d


class Storage:
    def __init__(self, root):
        self.root = os.fspath(root)
        self.data_dir = os.path.join(self.root, "Data", "data")
        self.build = _config(self._config_path(self._active_build_key()))
        self._buckets: dict[int, dict[bytes, tuple[int, int, int]]] = {}
        self._files = {}
        self._encoding = None
        self._names = None
        self.root_info: dict[str, list[str]] = {}
        self.vfs_dirs: set[str] = set()
        self.blte_stats: dict[str, int] = {}

    @property
    def build_name(self) -> str:
        return self.build.get("build-name", ["unknown"])[0]

    def _active_build_key(self) -> str:
        with open(os.path.join(self.root, ".build.info"), encoding="utf-8") as f:
            rows = [line.rstrip("\r\n").split("|") for line in f if line.strip()]
        cols = [c.split("!")[0] for c in rows[0]]
        records = [dict(zip(cols, r)) for r in rows[1:]]
        return next((r for r in records if r.get("Active") == "1"), records[0])["Build Key"]

    def _config_path(self, key: str) -> str:
        return os.path.join(self.root, "Data", "config", key[:2], key[2:4], key)

    # local index (.idx v7)
    @staticmethod
    def bucket_of(ekey: bytes) -> int:
        x = 0
        for b in ekey[:9]:
            x ^= b
        return (x & 0xF) ^ (x >> 4)

    def _bucket(self, b: int) -> dict[bytes, tuple[int, int, int]]:
        if b in self._buckets:
            return self._buckets[b]
        best = max((f for f in os.listdir(self.data_dir) if re.fullmatch("%02x[0-9a-f]{8}\\.idx" % b, f)),
                   key=lambda f: int(f[2:10], 16))
        with open(os.path.join(self.data_dir, best), "rb") as f:
            data = f.read()
        rev, bucket, _flags, size_bytes, offset_bytes, key_bytes, seg_bits, _max = struct.unpack_from("<HBBBBBBQ", data, 8)
        if (rev, bucket, size_bytes, offset_bytes, key_bytes) != (7, b, 4, 5, 9):
            raise ValueError(f"unsupported index file {best}")
        entries_size = struct.unpack_from("<I", data, 0x20)[0]
        d, mask, width = {}, (1 << seg_bits) - 1, key_bytes + offset_bytes + size_bytes
        for p in range(0x28, 0x28 + entries_size - entries_size % width, width):
            k = data[p:p + 9]
            packed = int.from_bytes(data[p + 9:p + 14], "big")
            size = int.from_bytes(data[p + 14:p + 18], "little")
            if k not in d or d[k][2] <= ENTRY_HEADER:  # prefer a real entry over a header-only placeholder
                d[k] = (packed >> seg_bits, packed & mask, size)
        self._buckets[b] = d
        return d

    def locate(self, ekey: bytes):
        return self._bucket(self.bucket_of(ekey)).get(bytes(ekey[:9]))

    def read_ekey(self, ekey: bytes) -> bytes | None:
        loc = self.locate(ekey)
        if loc is None or loc[2] <= ENTRY_HEADER:
            return None
        archive, offset, size = loc
        f = self._files.get(archive)
        if f is None:
            f = self._files[archive] = open(os.path.join(self.data_dir, "data.%03d" % archive), "rb")
        f.seek(offset)
        return blte_decode(f.read(size)[ENTRY_HEADER:], self.blte_stats)

    # encoding (CKey -> EKey)
    def ckey_to_ekey(self, ckey: bytes) -> bytes | None:
        if self._encoding is None:
            e = self._encoding = self.read_ekey(bytes.fromhex(self.build["encoding"][1]))
            if e[:2] != b"EN" or e[2] != 1:
                raise ValueError("unsupported encoding file")
            self._ckey_len, self._ekey_len = e[3], e[4]
            self._page_size = int.from_bytes(e[5:7], "big") * 1024
            self._page_count = int.from_bytes(e[9:13], "big")
            self._pages_at = 22 + int.from_bytes(e[18:22], "big")
            step = self._ckey_len + 16  # first key + page MD5
            self._first_keys = [e[self._pages_at + i * step:self._pages_at + i * step + self._ckey_len]
                                for i in range(self._page_count)]
        e, ckey = self._encoding, bytes(ckey)
        i = bisect.bisect_right(self._first_keys, ckey) - 1
        if i < 0:
            return None
        p = self._pages_at + self._page_count * (self._ckey_len + 16) + i * self._page_size
        end = p + self._page_size
        while p + 6 + self._ckey_len <= end:
            key_count = e[p]  # u8 key count, u40be content size, ckey, ekey * key_count
            if key_count == 0:
                break
            if e[p + 6:p + 6 + self._ckey_len] == ckey:
                return e[p + 6 + self._ckey_len:p + 6 + self._ckey_len + self._ekey_len]
            p += 6 + self._ckey_len + self._ekey_len * key_count
        return None

    def read_ckey(self, ckey: bytes) -> bytes | None:
        ekey = self.ckey_to_ekey(ckey)
        return None if ekey is None else self.read_ekey(ekey)

    # names (TVFS manifest + legacy text root for original casing)
    def _load_names(self) -> None:
        vfs_ekeys = {bytes.fromhex(v[1])[:9] for k, v in self.build.items() if re.fullmatch(r"vfs-(root|\d+)", k)}
        self._names = {}
        self._parse_tvfs(self.read_ekey(bytes.fromhex(self.build["vfs-root"][1])), "", vfs_ekeys)
        text = self.read_ckey(bytes.fromhex(self.build["root"][0]))  # "War3.w3mod:Units/UnitData.slk|<ckey>|..."
        for line in (text or b"").decode("utf-8", "replace").splitlines():
            parts = line.split("|")
            if len(parts) >= 2:
                k = self.norm(parts[0])
                self.root_info[k] = parts
                if k in self._names:
                    self._names[k] = (parts[0], self._names[k][1])

    def _parse_tvfs(self, data: bytes, prefix: str, vfs_ekeys: set[bytes]) -> None:
        if data[:4] != b"TVFS" or data[4] != 1:
            raise ValueError("not TVFS v1")
        ekey_size = data[6]
        path_off, path_size, vfs_off, _vfs_size, cft_off, cft_size = struct.unpack_from(">6I", data, 12)
        cft_width = 4 if cft_size > 0xFFFFFF else 3 if cft_size > 0xFFFF else 2 if cft_size > 0xFF else 1

        def spans_at(val):
            p = vfs_off + val
            n = data[p]
            p += 1
            if not 1 <= n <= 224:
                return None
            out = []
            for _ in range(n):
                _file_off, span_size = struct.unpack_from(">II", data, p)
                c = cft_off + int.from_bytes(data[p + 8:p + 8 + cft_width], "big")
                out.append((bytes(data[c:c + ekey_size]), span_size))
                p += 8 + cft_width
            return out

        # Path table is a prefix tree: [0x00 sep before] [u8 len + name] [0x00 sep after] [0xFF + u32be value];
        # value & 0x80000000 -> folder (low 31 bits = folder byte length incl. value), else VFS table offset.
        def walk(p, end, base):
            cur = base
            while p < end:
                if data[p] == 0:
                    cur += "/"
                    p += 1
                if p < end and data[p] != 0xFF:
                    n = data[p]
                    cur += data[p + 1:p + 1 + n].decode("utf-8", "replace")
                    p += 1 + n
                post = False
                if p < end and data[p] == 0:
                    post = True
                    p += 1
                if p < end and data[p] != 0xFF:
                    post = True
                if post:
                    cur += "/"
                if p < end and data[p] == 0xFF:
                    val = int.from_bytes(data[p + 1:p + 5], "big")
                    p += 5
                    if val & 0x80000000:
                        folder_end = p + (val & 0x7FFFFFFF) - 4
                        walk(p, folder_end, cur)
                        p = folder_end
                    else:
                        spans = spans_at(val)
                        if spans is not None:
                            self._names[self.norm(cur)] = (cur, spans)
                            if len(spans) == 1 and spans[0][0][:9] in vfs_ekeys:  # nested VFS, e.g. "war3.w3mod:_hd.w3mod"
                                self.vfs_dirs.add(self.norm(cur))
                                self._parse_tvfs(self.read_ekey(spans[0][0]), cur + ":", vfs_ekeys)
                    cur = base

        p, end = path_off, path_off + path_size
        if data[p] == 0xFF:
            val = int.from_bytes(data[p + 1:p + 5], "big")
            end, p = p + 1 + (val & 0x7FFFFFFF), p + 5
        walk(p, end, prefix)

    @staticmethod
    def norm(path: str) -> str:
        return path.replace("\\", "/").lower()

    # public API
    def names(self) -> dict[str, tuple[str, list]]:
        if self._names is None:
            self._load_names()
        return self._names

    def list(self, pattern: str = "") -> list[str]:
        names, pat = self.names(), self.norm(pattern)
        if any(c in pat for c in "*?["):
            return sorted(v[0] for k, v in names.items() if fnmatch.fnmatchcase(k, pat))
        return sorted(v[0] for k, v in names.items() if pat in k)

    def read(self, path: str) -> bytes | None:
        hit = self.names().get(self.norm(path))
        if hit is None:
            return None
        parts = []
        for ekey, _size in hit[1]:
            b = self.read_ekey(ekey)
            if b is None:
                return None  # in the manifest but not downloaded locally
            parts.append(b)
        return b"".join(parts)

    def is_local(self, path: str) -> bool:
        hit = self.names().get(self.norm(path))
        return hit is not None and all((self.locate(e) or (0, 0, 0))[2] > ENTRY_HEADER for e, _ in hit[1])

    def layers(self, hd: bool = False, teen: bool = False, locale: str = "enUS", tileset: str | None = None,
               balance: str | None = None) -> list[str]:
        """Mod prefixes, highest priority first. Order per HiveWE hierarchy; balance mods ("Custom_V0",
        "Custom_V1", "Melee_V0") sit above the base layer. ponytail: _DE.w3mod not layered yet."""
        out = []
        for pre in (["War3.w3mod:_HD.w3mod:"] if hd else []) + ["War3.w3mod:"]:
            if tileset:
                out.append(pre + f"_Tilesets/{tileset}.w3mod:")
            out.append(pre + f"_Locales/{locale}.w3mod:")
            if teen:
                out.append(pre + "_Teen.w3mod:")
            if pre == "War3.w3mod:" and balance:
                out.append(pre + f"_Balance/{balance}.w3mod:")
            out.append(pre)
        out.append("War3.w3mod:_Deprecated.w3mod:")
        return out

    def resolve(self, relpath: str, **layer_kwargs) -> str | None:
        """First existing full path for a mod-relative path like "Units/UnitData.slk"."""
        names = self.names()
        for pre in self.layers(**layer_kwargs):
            hit = names.get(self.norm(pre + relpath))
            if hit is not None:
                return hit[0]
        return None


def open_storage(root) -> Storage:
    return Storage(root)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& $PY -m pytest tests/casc -v`
Expected: 7 passed (storage tests skip without an install)

- [ ] **Step 5: Commit**

```bash
git add src/wc3mcp/casc tests/casc
git commit -m "feat(casc): local CASC storage reader with TVFS names and mod layers" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

### Task 6: SLK and profile text parsers

**Files:**
- Create: `src/wc3mcp/gamedata/__init__.py`, `src/wc3mcp/gamedata/slk.py`, `src/wc3mcp/gamedata/profile.py`
- Test: `tests/gamedata/test_slk.py`, `tests/gamedata/test_profile.py`

**Interfaces:**
- Produces: `slk.Table(columns: list[str], rows: dict[str, dict[str, str]])` (rows keyed by first-column value, values unquoted strings); `slk.parse_slk(data: bytes) -> Table`; `profile.parse_profile(data: bytes, into: dict | None = None) -> dict[str, dict[str, str]]` (section names keep case, keys lower-cased, later files override); `profile.split_list(value: str) -> list[str]`; `profile.unquote(value: str) -> str`.

- [ ] **Step 1: Write the failing tests**

`src/wc3mcp/gamedata/__init__.py`:
```python
"""Game data catalog built from the local CASC storage."""
```

`tests/gamedata/test_slk.py`:
```python
from corpus import INSTALL, needs_install
from wc3mcp.gamedata.slk import parse_slk

SAMPLE = (b'ID;PWXL;N;E\r\nB;X3;Y3;D0\r\nC;X1;Y1;K"unitID"\r\nC;X2;K"HP"\r\nC;X3;K"name"\r\n'
          b'C;X1;Y2;K"hfoo"\r\nC;X2;K420\r\nC;X3;K"Foot;man"\r\nC;X1;Y3;K"hkni"\r\nC;X3;K"Knight"\r\nE\r\n')


def test_parse_slk_rows_and_quoting():
    t = parse_slk(SAMPLE)
    assert t.columns == ["unitID", "HP", "name"]
    assert t.rows["hfoo"] == {"unitID": "hfoo", "HP": "420", "name": "Foot;man"}
    assert t.rows["hkni"] == {"unitID": "hkni", "name": "Knight"}


def test_empty_input():
    t = parse_slk(b"ID;PWXL\r\nE\r\n")
    assert t.columns == [] and t.rows == {}


@needs_install
def test_real_ability_data():
    from wc3mcp.casc.storage import open_storage

    t = parse_slk(open_storage(INSTALL).read("War3.w3mod:Units/AbilityData.slk"))
    assert t.columns[0] == "alias"
    assert [t.rows["AHbz"][f"DataA{i}"] for i in (1, 2, 3)] == ["6", "8", "10"]
```

`tests/gamedata/test_profile.py`:
```python
from wc3mcp.gamedata.profile import parse_profile, split_list, unquote

TEXT = ('﻿// comment\r\n[AHbz]\t\r\nName=Blizzard\r\nTip=Blizzard - [Level 1],Blizzard - [Level 2]\r\n'
        'Ubertip="Calls down <AHbz,DataA1> waves.","Calls down <AHbz,DataA2> waves."\r\n'
        'modelScale:hd=1\r\n\r\n[hfoo]\r\nName=Footman\r\n').encode("utf-8")


def test_parse_sections_keys_and_comments():
    p = parse_profile(TEXT)
    assert set(p) == {"AHbz", "hfoo"}
    assert p["AHbz"]["name"] == "Blizzard"
    assert p["AHbz"]["modelscale:hd"] == "1"


def test_later_files_override_and_merge():
    p = parse_profile(TEXT)
    parse_profile(b"[hfoo]\nName=Footman2\nHotkey=F\n", into=p)
    assert p["hfoo"] == {"name": "Footman2", "hotkey": "F"}
    assert p["AHbz"]["name"] == "Blizzard"


def test_split_list_honors_quotes():
    p = parse_profile(TEXT)
    assert split_list(p["AHbz"]["tip"]) == ["Blizzard - [Level 1]", "Blizzard - [Level 2]"]
    assert split_list(p["AHbz"]["ubertip"]) == ["Calls down <AHbz,DataA1> waves.", "Calls down <AHbz,DataA2> waves."]
    assert split_list("") == [""]


def test_unquote():
    assert unquote('"a,b"') == "a,b" and unquote("plain") == "plain" and unquote('"') == '"'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& $PY -m pytest tests/gamedata -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wc3mcp.gamedata.slk'`

- [ ] **Step 3: Write minimal implementation**

`src/wc3mcp/gamedata/slk.py`:
```python
"""SYLK tables as shipped with Warcraft III (only C records carry data)."""
from dataclasses import dataclass


@dataclass
class Table:
    columns: list[str]
    rows: dict[str, dict[str, str]]


def _unquote(tok: str) -> str:
    return tok[1:-1] if len(tok) >= 2 and tok[0] == tok[-1] == '"' else tok


def parse_slk(data: bytes) -> Table:
    cells: dict[int, dict[int, str]] = {}
    x = y = 0
    for line in data.decode("utf-8", "replace").splitlines():
        if not line.startswith("C;"):
            continue
        parts = line.split(";")
        value = None
        for j in range(1, len(parts)):
            tag = parts[j][:1]
            if tag == "X":
                x = int(parts[j][1:])
            elif tag == "Y":
                y = int(parts[j][1:])
            elif tag == "K":  # value runs to the end of the line and may contain ';'
                value = _unquote(";".join(parts[j:])[1:])
                break
        if value is not None:
            cells.setdefault(y, {})[x] = value
    if not cells:
        return Table([], {})
    header = cells.pop(min(cells))
    width = max(header)
    columns = [header.get(i, "") for i in range(1, width + 1)]
    rows = {}
    for yy in sorted(cells):
        r = cells[yy]
        if 1 in r:
            rows[r[1]] = {columns[i - 1]: v for i, v in r.items() if 1 <= i <= width}
    return Table(columns, rows)
```

`src/wc3mcp/gamedata/profile.py`:
```python
"""INI-like 'profile' text files: *Func.txt, *Strings.txt, *Skin.txt, WorldEditStrings.txt."""


def parse_profile(data: bytes, into: dict | None = None) -> dict[str, dict[str, str]]:
    out = {} if into is None else into
    section = None
    for line in data.decode("utf-8-sig", "replace").splitlines():
        s = line.strip()
        if not s or s.startswith("//"):
            continue
        if s.startswith("[") and "]" in s:
            section = out.setdefault(s[1:s.index("]")], {})
        elif section is not None and "=" in s:
            key, value = s.split("=", 1)
            section[key.strip().lower()] = value.strip()
    return out


def split_list(value: str) -> list[str]:
    """Split a comma list, honoring double-quoted items (quotes removed)."""
    items, cur, quoted = [], [], False
    for ch in value:
        if ch == '"':
            quoted = not quoted
        elif ch == "," and not quoted:
            items.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    items.append("".join(cur))
    return items


def unquote(value: str) -> str:
    return value[1:-1] if len(value) >= 2 and value[0] == value[-1] == '"' else value
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& $PY -m pytest tests/gamedata -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/wc3mcp/gamedata tests/gamedata
git commit -m "feat(gamedata): SLK and profile text parsers" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

### Task 7: Game data catalog

**Files:**
- Create: `src/wc3mcp/gamedata/kinds.py`, `src/wc3mcp/gamedata/catalog.py`
- Test: `tests/gamedata/test_catalog.py`

**Interfaces:**
- Consumes: Task 5 `Storage` (`resolve`, `read`, `list`, `names`, `norm`, `is_local`); Task 6 `parse_slk`, `Table`, `parse_profile`, `split_list`, `unquote`; Task 1 `ToolError`.
- Produces: `kinds.OBJECT_KINDS: dict[str, ObjectKind]`, `kinds.ROW_KINDS: dict[str, RowKind]`, `kinds.PATH_KINDS: dict[str, tuple[tuple[str, ...], str]]`; `catalog.KINDS: tuple[str, ...]` = `unit item ability buff upgrade destructible doodad tile cliff water sound model icon file`; `catalog.FieldMeta`; `Catalog(storage, locale="enUS", balance: str | None = "Custom_V1", hd=True)` with `.search(kind, query="", limit=50, offset=0) -> list[dict]` (`{"id","name","suffix"}` or `{"id"}` for path kinds), `.get(kind, obj_id, fields: list[str] | None = None) -> dict`, `.name(kind, obj_id) -> str`, `.fields(kind) -> list[FieldMeta]`, `.levels(kind, obj_id) -> int`, `.westring(value) -> str`.
- `get()` for object kinds returns `{"kind","id","name","levels","fields": {rawcode: {"field","name","category","type", "value" | "values"}}}`; `fields` filters by rawcode, field name or display-name substring (case-insensitive).
- Error codes: `bad_kind`, `not_found`.

- [ ] **Step 1: Write the failing test**

`tests/gamedata/test_catalog.py`:
```python
import pytest

from corpus import INSTALL, needs_install
from wc3mcp.casc.storage import open_storage
from wc3mcp.errors import ToolError
from wc3mcp.gamedata.catalog import Catalog

pytestmark = needs_install


@pytest.fixture(scope="module")
def cat():
    return Catalog(open_storage(INSTALL), locale="enUS", balance=None, hd=True)  # base data: stable values


def test_unit_fields(cat):
    g = cat.get("unit", "hfoo")
    assert g["name"] == "Footman"
    assert g["fields"]["uhpm"]["name"] == "Hit Points Maximum (Base)"
    assert g["fields"]["uhpm"]["value"] == "420"
    assert g["fields"]["umdl"]["value"].lower().endswith("footman")


def test_ability_levels_and_specific_fields(cat):
    g = cat.get("ability", "AHbz", fields=["Hbz1", "atp1", "hem1"])
    assert g["levels"] == 3
    assert g["fields"]["Hbz1"]["values"] == ["6", "8", "10"]
    assert g["fields"]["atp1"]["values"][0] == "Blizzard - [|cffffcc00Level 1|r]"
    assert "hem1" not in g["fields"]  # a Data field that only applies to Ahem


def test_names_for_other_kinds(cat):
    assert cat.name("item", "ratf") == "Claws of Attack +15"
    assert cat.name("buff", "BHbd") == "Blizzard"
    assert cat.name("upgrade", "Rhme") == "Iron Forged Swords"
    assert cat.name("destructible", "LTlt") == "Summer Tree Wall"
    assert cat.name("doodad", "APms") == "Mushrooms"
    assert cat.name("tile", "Ldrt") == "Dirt"
    assert cat.name("cliff", "CLdi") == "Dirt Cliff"


def test_upgrade_level_names(cat):
    g = cat.get("upgrade", "Rhme", fields=["gnam"])
    assert g["levels"] == 3
    assert g["fields"]["gnam"]["values"] == ["Iron Forged Swords", "Steel Forged Swords", "Mithril Forged Swords"]


def test_search(cat):
    assert "Hamg" in [r["id"] for r in cat.search("unit", "archmage")]
    models = cat.search("model", "footman")
    assert models and all(m["id"].lower().endswith((".mdx", ".mdl")) for m in models)


def test_unknown_kind_and_id(cat):
    with pytest.raises(ToolError) as e:
        cat.get("spaceship", "x")
    assert e.value.code == "bad_kind"
    with pytest.raises(ToolError) as e:
        cat.get("unit", "zzzz")
    assert e.value.code == "not_found"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& $PY -m pytest tests/gamedata/test_catalog.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wc3mcp.gamedata.catalog'`

- [ ] **Step 3: Write minimal implementation**

`src/wc3mcp/gamedata/kinds.py`:
```python
"""Where each kind of game data lives in CASC (paths relative to a mod layer)."""
from dataclasses import dataclass

RACES = ("Campaign", "Human", "Neutral", "NightElf", "Orc", "Undead")
ABILITY_GROUPS = ("Campaign", "Common", "Human", "Item", "Neutral", "NightElf", "Orc", "Undead")
_ABILITY_PROFILES = (tuple(f"Units/{g}AbilityFunc.txt" for g in ABILITY_GROUPS)
                     + tuple(f"Units/{g}AbilityStrings.txt" for g in ABILITY_GROUPS)
                     + ("Units/AbilitySkin.txt", "Units/AbilitySkinStrings.txt"))


@dataclass(frozen=True)
class ObjectKind:
    meta: str                   # metadata SLK
    slks: dict[str, str]        # metadata 'slk' value -> data SLK path
    id_slk: str                 # the 'slk' value whose table lists object ids
    profiles: tuple[str, ...]   # merged txt files; later files override earlier ones
    use_flags: tuple[str, ...]  # metadata columns of which at least one must be "1"; () = every row applies
    name_keys: tuple[str, ...]  # "profile:<key>" or "slk:<column>", first non-empty wins
    suffix_keys: tuple[str, ...]
    level_column: str | None    # data SLK column holding the level count


OBJECT_KINDS = {
    "unit": ObjectKind(
        "Units/UnitMetaData.slk",
        {"UnitData": "Units/UnitData.slk", "UnitBalance": "Units/UnitBalance.slk", "UnitUI": "Units/unitUI.slk",
         "UnitWeapons": "Units/UnitWeapons.slk", "UnitAbilities": "Units/UnitAbilities.slk"},
        "UnitData",
        tuple(f"Units/{r}UnitFunc.txt" for r in RACES) + tuple(f"Units/{r}UnitStrings.txt" for r in RACES)
        + ("Units/UnitSkin.txt", "Units/UnitSkinStrings.txt", "Units/UnitWeaponsFunc.txt", "Units/UnitWeaponsSkin.txt"),
        ("useUnit", "useHero", "useBuilding"), ("profile:name",), ("profile:editorsuffix",), None),
    "item": ObjectKind(
        "Units/UnitMetaData.slk", {"ItemData": "Units/ItemData.slk"}, "ItemData",
        ("Units/ItemFunc.txt", "Units/ItemStrings.txt", "Units/ItemSkin.txt", "Units/ItemSkinStrings.txt"),
        ("useItem",), ("profile:name",), ("profile:editorsuffix",), None),
    "ability": ObjectKind(
        "Units/AbilityMetaData.slk", {"AbilityData": "Units/AbilityData.slk"}, "AbilityData", _ABILITY_PROFILES,
        (), ("profile:name",), ("profile:editorsuffix",), "levels"),
    "buff": ObjectKind(
        "Units/AbilityBuffMetaData.slk", {"AbilityBuffData": "Units/AbilityBuffData.slk"}, "AbilityBuffData",
        _ABILITY_PROFILES, (), ("profile:editorname", "profile:bufftip"), ("profile:editorsuffix",), None),
    "upgrade": ObjectKind(
        "Units/UpgradeMetaData.slk", {"UpgradeData": "Units/UpgradeData.slk"}, "UpgradeData",
        tuple(f"Units/{r}UpgradeFunc.txt" for r in RACES) + tuple(f"Units/{r}UpgradeStrings.txt" for r in RACES)
        + ("Units/UpgradeSkin.txt", "Units/UpgradeSkinStrings.txt"),
        (), ("profile:name",), ("profile:editorsuffix",), "maxlevel"),
    "destructible": ObjectKind(
        "Units/DestructableMetaData.slk", {"DestructableData": "Units/DestructableData.slk"}, "DestructableData",
        ("Units/DestructableSkin.txt", "Units/DestructableSkinStrings.txt"), (), ("slk:Name",), ("slk:EditorSuffix",),
        None),
    "doodad": ObjectKind(
        "Doodads/DoodadMetaData.slk", {"DoodadData": "Doodads/Doodads.slk"}, "DoodadData",
        ("Doodads/DoodadSkins.txt",), (), ("slk:Name",), (), None),
}


@dataclass(frozen=True)
class RowKind:
    slks: tuple[str, ...]
    name_column: str | None


ROW_KINDS = {
    "tile": RowKind(("TerrainArt/Terrain.slk",), "name"),
    "cliff": RowKind(("TerrainArt/CliffTypes.slk",), "name"),
    "water": RowKind(("TerrainArt/Water.slk",), None),
    "sound": RowKind(tuple(f"UI/SoundInfo/{n}.slk" for n in (
        "AbilitySounds", "AmbienceSounds", "AmbientMusic", "AnimSounds", "CinematicSounds", "DialogSounds",
        "EnvironmentSounds", "Music", "UISounds", "UnitAckSounds", "UnitCombatSounds")), None),
}

# kind -> (allowed extensions, required lower-case path substring)
PATH_KINDS = {
    "model": ((".mdx", ".mdl"), ""),
    "icon": ((".blp", ".dds"), "buttons"),
    "file": ((), ""),
}
```

`src/wc3mcp/gamedata/catalog.py`:
```python
"""Game data lookups: base objects with their editor fields, terrain/sound rows, asset paths."""
from dataclasses import dataclass
from functools import cached_property

from ..errors import ToolError
from .kinds import OBJECT_KINDS, PATH_KINDS, ROW_KINDS
from .profile import parse_profile, split_list, unquote
from .slk import Table, parse_slk

KINDS = tuple(OBJECT_KINDS) + tuple(ROW_KINDS) + tuple(PATH_KINDS)


def _int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _codes(value: str | None) -> tuple[str, ...]:
    return tuple(c for c in (value or "").split(",") if c)


@dataclass(frozen=True)
class FieldMeta:
    id: str
    field: str
    slk: str
    index: int
    repeat: int
    data: int
    category: str
    display_name: str
    type: str
    min: str
    max: str
    use_specific: tuple[str, ...]
    not_specific: tuple[str, ...]

    def column(self, level: int) -> str:
        """Data column / profile key: Data + letter for ability data fields, + level for per-level SLK columns."""
        name = self.field + (chr(ord("A") + self.data - 1) if self.data > 0 else "")
        return name + str(level) if self.repeat > 0 and self.slk != "Profile" else name


class Catalog:
    """ponytail: parsed tables are cached in memory per process; add a per-build disk cache if startup gets slow."""

    def __init__(self, storage, locale: str = "enUS", balance: str | None = "Custom_V1", hd: bool = True):
        self.storage = storage
        self.layer = {"locale": locale, "balance": balance, "hd": hd}
        self.variant = "hd" if hd else "sd"
        self._tables: dict[str, Table] = {}
        self._profiles: dict[str, dict] = {}
        self._fields: dict[str, list[FieldMeta]] = {}

    # raw data
    def _read(self, relpath: str) -> bytes | None:
        full = self.storage.resolve(relpath, **self.layer)
        return None if full is None else self.storage.read(full)

    def table(self, relpath: str) -> Table:
        if relpath not in self._tables:
            data = self._read(relpath)
            self._tables[relpath] = parse_slk(data) if data else Table([], {})
        return self._tables[relpath]

    def profile(self, kind: str) -> dict:
        if kind not in self._profiles:
            merged = {}
            for rel in OBJECT_KINDS[kind].profiles:
                data = self._read(rel)
                if data:
                    parse_profile(data, into=merged)
            self._profiles[kind] = merged
        return self._profiles[kind]

    @cached_property
    def _westrings(self) -> dict[str, str]:
        merged = {}
        for rel in ("UI/WorldEditStrings.txt", "UI/WorldEditGameStrings.txt"):
            data = self._read(rel)
            if data:
                parse_profile(data, into=merged)
        return {k: unquote(v) for section in merged.values() for k, v in section.items()}

    def westring(self, value: str) -> str:
        return self._westrings.get(value.lower(), value) if value.startswith("WESTRING_") else value

    # metadata
    def _check(self, kind: str) -> None:
        if kind not in KINDS:
            raise ToolError("bad_kind", f"unknown kind {kind!r}", hint="one of: " + ", ".join(KINDS))

    def fields(self, kind: str) -> list[FieldMeta]:
        self._check(kind)
        spec = OBJECT_KINDS[kind]
        if kind not in self._fields:
            out = []
            for r in self.table(spec.meta).rows.values():
                slk = r.get("slk", "")
                if slk != "Profile" and slk not in spec.slks:
                    continue
                if spec.use_flags and not any(r.get(flag) == "1" for flag in spec.use_flags):
                    continue
                out.append(FieldMeta(
                    id=r["ID"], field=r.get("field", ""), slk=slk, index=_int(r.get("index"), -1),
                    repeat=_int(r.get("repeat"), 0), data=_int(r.get("data"), 0), category=r.get("category", ""),
                    display_name=self.westring(r.get("displayName", "")), type=r.get("type", ""),
                    min=r.get("minVal", ""), max=r.get("maxVal", ""),
                    use_specific=_codes(r.get("useSpecific")), not_specific=_codes(r.get("notSpecific"))))
            self._fields[kind] = out
        return self._fields[kind]

    def ids(self, kind: str) -> list[str]:
        if kind in OBJECT_KINDS:
            spec = OBJECT_KINDS[kind]
            return list(self.table(spec.slks[spec.id_slk]).rows)
        return [k for rel in ROW_KINDS[kind].slks for k in self.table(rel).rows]

    def levels(self, kind: str, obj_id: str) -> int:
        spec = OBJECT_KINDS[kind]
        if spec.level_column is None:
            return 1
        row = self.table(spec.slks[spec.id_slk]).rows.get(obj_id, {})
        return max(1, _int(row.get(spec.level_column), 1))

    # values
    def _raw(self, kind: str, obj_id: str, source: str, key: str) -> str | None:
        if source == "Profile":
            section = self.profile(kind).get(obj_id, {})
            k = key.lower()
            return section.get(f"{k}:{self.variant}", section.get(k))
        row = self.table(OBJECT_KINDS[kind].slks[source]).rows.get(obj_id)
        return None if row is None else row.get(key)

    def value(self, kind: str, obj_id: str, meta: FieldMeta, level: int = 1) -> str | None:
        raw = self._raw(kind, obj_id, meta.slk, meta.column(level))
        if raw is None or meta.slk != "Profile":
            return raw
        if meta.repeat > 0:  # per-level comma list; missing levels reuse the last entry
            parts = split_list(raw)
            return parts[min(level, len(parts)) - 1]
        if meta.index >= 0:
            parts = split_list(raw)
            return parts[meta.index] if meta.index < len(parts) else None
        return unquote(raw)

    def _applies(self, kind: str, obj_id: str, meta: FieldMeta) -> bool:
        if kind != "ability" or not (meta.use_specific or meta.not_specific):
            return True
        code = self.table(OBJECT_KINDS["ability"].slks["AbilityData"]).rows.get(obj_id, {}).get("code", obj_id)
        return (not meta.use_specific or code in meta.use_specific) and code not in meta.not_specific

    def _lookup(self, kind: str, obj_id: str, keys: tuple[str, ...]) -> str:
        for spec_key in keys:
            source, key = spec_key.split(":", 1)
            raw = self._raw(kind, obj_id, "Profile" if source == "profile" else OBJECT_KINDS[kind].id_slk, key)
            if raw:
                return self.westring(split_list(raw)[0])
        return ""

    def _row(self, kind: str, obj_id: str) -> dict | None:
        for rel in ROW_KINDS[kind].slks:
            row = self.table(rel).rows.get(obj_id)
            if row is not None:
                return row
        return None

    # public queries
    def name(self, kind: str, obj_id: str) -> str:
        self._check(kind)
        if kind in OBJECT_KINDS:
            return self._lookup(kind, obj_id, OBJECT_KINDS[kind].name_keys)
        if kind in ROW_KINDS:
            row, col = self._row(kind, obj_id), ROW_KINDS[kind].name_column
            return self.westring(row[col]) if row and col and row.get(col) else obj_id
        return obj_id

    def search(self, kind: str, query: str = "", limit: int = 50, offset: int = 0) -> list[dict]:
        self._check(kind)
        if kind in PATH_KINDS:
            exts, needle = PATH_KINDS[kind]
            hits = [p for p in self.storage.list(query)
                    if (not exts or p.lower().endswith(exts)) and needle in p.lower()]
            return [{"id": p} for p in hits[offset:offset + limit]]
        q, out = query.casefold(), []
        for obj_id in self.ids(kind):
            name = self.name(kind, obj_id)
            suffix = self._lookup(kind, obj_id, OBJECT_KINDS[kind].suffix_keys) if kind in OBJECT_KINDS else ""
            if q in obj_id.casefold() or q in name.casefold() or q in suffix.casefold():
                out.append({"id": obj_id, "name": name, "suffix": suffix})
        return out[offset:offset + limit]

    def get(self, kind: str, obj_id: str, fields: list[str] | None = None) -> dict:
        self._check(kind)
        missing = ToolError("not_found", f"no {kind} with id {obj_id!r}", hint="data_search finds ids")
        if kind in PATH_KINDS:
            if self.storage.norm(obj_id) not in self.storage.names():
                raise missing
            return {"kind": kind, "id": obj_id, "local": self.storage.is_local(obj_id)}
        if kind in ROW_KINDS:
            row = self._row(kind, obj_id)
            if row is None:
                raise missing
            return {"kind": kind, "id": obj_id, "name": self.name(kind, obj_id),
                    "fields": {k: self.westring(v) for k, v in row.items()}}
        spec = OBJECT_KINDS[kind]
        if obj_id not in self.table(spec.slks[spec.id_slk]).rows:
            raise missing
        levels = self.levels(kind, obj_id)
        wanted = [f.lower() for f in fields] if fields else None
        out = {}
        for meta in self.fields(kind):
            if wanted is not None and not any(w in (meta.id.lower(), meta.field.lower()) or w in meta.display_name.lower()
                                              for w in wanted):
                continue
            if not self._applies(kind, obj_id, meta):
                continue
            entry = {"field": meta.field, "name": meta.display_name, "category": meta.category, "type": meta.type}
            if meta.repeat > 0:
                entry["values"] = [self.value(kind, obj_id, meta, lv) for lv in range(1, levels + 1)]
            else:
                entry["value"] = self.value(kind, obj_id, meta)
            out[meta.id] = entry
        return {"kind": kind, "id": obj_id, "name": self.name(kind, obj_id), "levels": levels, "fields": out}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `& $PY -m pytest tests/gamedata -v`
Expected: 13 passed (catalog tests skip without an install)

- [ ] **Step 5: Commit**

```bash
git add src/wc3mcp/gamedata tests/gamedata/test_catalog.py
git commit -m "feat(gamedata): object, terrain, sound and asset catalog with editor field metadata" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

### Task 8: Map working copy (`MapProject`)

**Files:**
- Create: `src/wc3mcp/project/__init__.py`, `src/wc3mcp/project/workspace.py`
- Test: `tests/project/test_workspace.py`

**Interfaces:**
- Consumes: Task 1 `config.home()`, `pathguard.ensure_writable`, `ToolError`; Task 3 `Archive`, `HASH_EMPTY`, `MpqError`; Task 4 `SPECIAL`, `RawEntry`, `capture_unnamed`, `write_archive`.
- Produces: `project_id(source) -> str`; `fingerprint(path: Path) -> dict`; `check_name(name: str) -> str`; `MapProject.open(source) -> MapProject`; methods `status() -> dict`, `list_files() -> list[dict]`, `read(name) -> bytes`, `write(name, data: bytes) -> None`, `delete(name) -> None`, `save(dest=None, format: str | None = None, force: bool = False) -> dict`, `snapshot(action: str, label: str | None = None) -> dict` (`create|restore|list|diff`), `close(discard: bool = False) -> dict`; attributes `.source: Path`, `.work: Path`.
- Error codes: `not_found`, `bad_archive`, `stale_work`, `no_such_file`, `bad_name`, `bad_format`, `format_change_in_place`, `source_changed`, `unnamed_files`, `write_failed`, `unsaved_changes`, `bad_label`, `no_such_snapshot`, `bad_action`, plus `install_read_only` from the path guard.
- Layout under `config.home()`: `work/<id>/{manifest.json, prefix.bin, files/…, unnamed/<i>.bin}`, `backups/<stem>-<id>/<timestamp><suffix>` (last 20 kept), `snapshots/<id>/<label>/`.

- [ ] **Step 1: Write the failing tests**

`src/wc3mcp/project/__init__.py`:
```python
"""Map and campaign working copies."""
```

`tests/project/test_workspace.py`:
```python
from pathlib import Path

import pytest

from corpus import ladder_maps
from wc3mcp.errors import ToolError
from wc3mcp.mpq.reader import Archive
from wc3mcp.mpq.writer import write_archive
from wc3mcp.project.workspace import MapProject


def make_map(path: Path, files: dict, **kw) -> Path:
    path.write_bytes(write_archive(files, **kw))
    return path


def test_open_edit_save_reopen(tmp_path):
    src = make_map(tmp_path / "m.w3x", {"war3map.w3i": b"info", "war3map.j": b"old"})
    original = src.read_bytes()
    p = MapProject.open(src)
    assert [f["name"] for f in p.list_files()] == ["war3map.j", "war3map.w3i"]
    p.write("war3map.j", b"new script")
    assert p.status()["dirty"] == ["war3map.j"]
    result = p.save()
    assert result["saved"] and Path(result["backup"]).read_bytes() == original
    p.close()
    assert Archive.open(src).read("war3map.j") == b"new script"


def test_reopen_resumes_unsaved_edits(tmp_path):
    src = make_map(tmp_path / "m.w3x", {"a.txt": b"1"})
    MapProject.open(src).write("a.txt", b"2")
    p = MapProject.open(src)
    assert p.read("a.txt") == b"2" and p.status()["dirty"] == ["a.txt"]


def test_save_refuses_when_source_changed(tmp_path):
    src = make_map(tmp_path / "m.w3x", {"a.txt": b"1"})
    p = MapProject.open(src)
    p.write("a.txt", b"mine")
    make_map(src, {"a.txt": b"theirs"})
    with pytest.raises(ToolError) as e:
        p.save()
    assert e.value.code == "source_changed"
    assert p.save(force=True)["saved"]
    assert Archive.open(src).read("a.txt") == b"mine"


def test_save_refuses_game_install(tmp_path, monkeypatch):
    install = tmp_path / "inst"
    install.mkdir()
    monkeypatch.setenv("WC3MCP_INSTALL", str(install))
    p = MapProject.open(make_map(install / "m.w3x", {"a.txt": b"1"}))
    p.write("a.txt", b"2")
    with pytest.raises(ToolError) as e:
        p.save()
    assert e.value.code == "install_read_only"


def test_close_requires_discard_for_unsaved(tmp_path):
    p = MapProject.open(make_map(tmp_path / "m.w3x", {"a.txt": b"1"}))
    p.delete("a.txt")
    with pytest.raises(ToolError) as e:
        p.close()
    assert e.value.code == "unsaved_changes"
    p.close(discard=True)


def test_bad_names_rejected(tmp_path):
    p = MapProject.open(make_map(tmp_path / "m.w3x", {"a.txt": b"1"}))
    for bad in ("..\\evil.txt", "C:\\x.txt", "\\abs.txt", "(listfile)", ""):
        with pytest.raises(ToolError):
            p.write(bad, b"x")


def test_snapshot_create_diff_restore(tmp_path):
    p = MapProject.open(make_map(tmp_path / "m.w3x", {"a.txt": b"1", "b.txt": b"2"}))
    p.snapshot("create", "before")
    p.write("a.txt", b"changed")
    p.write("c.txt", b"new")
    p.delete("b.txt")
    assert p.snapshot("diff", "before") == {"added": ["c.txt"], "removed": ["b.txt"], "changed": ["a.txt"]}
    p.snapshot("restore", "before")
    assert p.read("a.txt") == b"1" and p.read("b.txt") == b"2"
    assert p.snapshot("list")["snapshots"] == ["before"]


def test_folder_save_and_open(tmp_path):
    p = MapProject.open(make_map(tmp_path / "m.w3x", {"war3map.w3i": b"i", "war3mapImported\\x.blp": b"b"}))
    folder = tmp_path / "m_folder.w3x"
    assert p.save(dest=folder, format="folder")["saved"]
    q = MapProject.open(folder)
    assert q.status()["format"] == "folder" and q.read("war3mapImported\\x.blp") == b"b"


def test_protected_map_keeps_unnamed_files(tmp_path):
    src = make_map(tmp_path / "p.w3x", {"war3map.w3i": b"info", "secret\\x.txt": b"hidden" * 500}, listfile=False)
    p = MapProject.open(src)
    assert p.status()["protected"] and p.status()["unnamed_files"] == 1
    p.write("war3map.w3i", b"info2")
    p.save()
    arc = Archive.open(src)
    assert arc.read("secret\\x.txt") == b"hidden" * 500 and arc.read("war3map.w3i") == b"info2"
    with pytest.raises(ToolError) as e:
        p.save(dest=tmp_path / "p_folder", format="folder")
    assert e.value.code == "unnamed_files"


MAPS = ladder_maps()


@pytest.mark.skipif(not MAPS, reason="no ladder maps in Documents")
def test_ladder_map_edit_keeps_other_files(tmp_path):
    src = tmp_path / MAPS[0].name
    src.write_bytes(MAPS[0].read_bytes())
    before = Archive.open(src)
    originals = {n: before.read(n) for n in before.list() if not n.startswith("(")}
    p = MapProject.open(src)
    p.write("war3mapImported\\note.txt", b"hello")
    p.save()
    after = Archive.open(src)
    assert after.read("war3mapImported\\note.txt") == b"hello"
    assert {n: after.read(n) for n in originals} == originals
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& $PY -m pytest tests/project -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wc3mcp.project.workspace'`

- [ ] **Step 3: Write minimal implementation**

`src/wc3mcp/project/workspace.py`:
```python
"""Map working copies: unpack, edit files, save with backup + atomic replace, snapshots."""
import hashlib
import json
import os
import shutil
import time
from pathlib import Path, PureWindowsPath

from .. import config, pathguard
from ..errors import ToolError
from ..mpq.reader import HASH_EMPTY, Archive, MpqError
from ..mpq.writer import SPECIAL, RawEntry, capture_unnamed, write_archive

BACKUPS_KEPT = 20
_IGNORED = {n.upper() for n in SPECIAL + ("(signature)",)}
_RAW_FIELDS = ("hash_index", "name_a", "name_b", "locale", "platform", "fsize", "flags", "src_pos", "key")


def project_id(source) -> str:
    return hashlib.sha1(os.path.normcase(os.path.abspath(source)).encode("utf-8")).hexdigest()[:12]


def fingerprint(path: Path) -> dict:
    if path.is_dir():
        h, size = hashlib.sha256(), 0
        for f in sorted(p for p in path.rglob("*") if p.is_file()):
            data = f.read_bytes()
            h.update(f.relative_to(path).as_posix().lower().encode("utf-8") + b"\0" + hashlib.sha256(data).digest())
            size += len(data)
        return {"size": size, "sha256": h.hexdigest()}
    if not path.is_file():
        return {"missing": True}
    data = path.read_bytes()
    return {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def check_name(name: str) -> str:
    n = name.replace("/", "\\")
    if (not n or n.startswith("\\") or ":" in n or n.upper() in _IGNORED
            or any(part in ("", ".", "..") for part in n.split("\\"))):
        raise ToolError("bad_name", f"invalid map file name: {name!r}",
                        hint="use a relative name such as war3mapImported\\icon.blp")
    return n


class MapProject:
    def __init__(self, source: Path, work: Path, manifest: dict):
        self.source, self.work, self.m = source, work, manifest

    # opening
    @classmethod
    def open(cls, source) -> "MapProject":
        source = Path(source).resolve()
        if not source.exists():
            raise ToolError("not_found", f"map not found: {source}")
        work = config.home() / "work" / project_id(source)
        manifest = work / "manifest.json"
        if manifest.is_file():
            p = cls(source, work, json.loads(manifest.read_text("utf-8")))
            if not p.source_changed():
                return p  # resume, keeping unsaved edits
            if p.m["dirty"] or p.m["deleted"]:
                raise ToolError("stale_work", "the map changed on disk while the working copy has unsaved edits",
                                hint="map_close with discard=true, then map_open again")
            shutil.rmtree(work)
        return cls._extract(source, work)

    @classmethod
    def _extract(cls, source: Path, work: Path) -> "MapProject":
        (work / "files").mkdir(parents=True)
        m = {"source": str(source), "fingerprint": fingerprint(source), "files": {}, "dirty": [], "deleted": [],
             "unnamed": [], "protected": False, "problems": []}
        p = cls(source, work, m)
        if source.is_dir():
            m.update(format="folder", sector_size=4096, hash_size=None, reserved_slots=[])
            for f in sorted(x for x in source.rglob("*") if x.is_file()):
                p._put(str(PureWindowsPath(f.relative_to(source))), f.read_bytes())
        else:
            try:
                arc = Archive.open(source)
                names = arc.list()
                unnamed = arc.unnamed_entries(names)
                m.update(format="mpq", sector_size=arc.sector_size, hash_size=len(arc.hashes),
                         reserved_slots=[e.index for e in arc.hashes if e.block != HASH_EMPTY],
                         protected=not arc.listfile_names() or bool(unnamed))
                (work / "prefix.bin").write_bytes(arc.prefix)
                for name in names:
                    if name.upper() not in _IGNORED:
                        p._put(name, arc.read(name))
                (work / "unnamed").mkdir()
                for i, entry in enumerate(unnamed):
                    raw = capture_unnamed(arc, entry)
                    (work / "unnamed" / f"{i}.bin").write_bytes(raw.data)
                    m["unnamed"].append({k: getattr(raw, k) for k in _RAW_FIELDS})
                m["problems"] = arc.problems
            except MpqError as e:
                shutil.rmtree(work, ignore_errors=True)
                raise ToolError("bad_archive", f"cannot read map: {e}") from e
        p._flush()
        return p

    # files
    def _put(self, name: str, data: bytes) -> None:
        entry = self.m["files"].get(name.upper())
        if entry is None:
            try:
                rel = check_name(name).replace("\\", "/")
            except ToolError:  # hostile names from protected maps stay addressable but never touch real paths
                rel = "_unsafe/" + hashlib.sha1(name.encode("utf-8", "surrogatepass")).hexdigest()
            entry = self.m["files"][name.upper()] = {"name": name, "path": rel}
        target = self.work / "files" / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def _entry(self, name: str) -> dict:
        entry = self.m["files"].get(name.replace("/", "\\").upper())
        if entry is None:
            raise ToolError("no_such_file", f"{name} is not in the map", hint="map_status lists the files")
        return entry

    def _mark(self, name: str, dirty: bool) -> None:
        key = name.upper()
        self.m["dirty"] = [n for n in self.m["dirty"] if n.upper() != key]
        self.m["deleted"] = [n for n in self.m["deleted"] if n.upper() != key]
        (self.m["dirty"] if dirty else self.m["deleted"]).append(name)
        self._flush()

    def _flush(self) -> None:
        (self.work / "manifest.json").write_text(json.dumps(self.m, indent=1), "utf-8")

    def source_changed(self) -> bool:
        return fingerprint(self.source).get("sha256") != self.m["fingerprint"].get("sha256")

    def list_files(self) -> list[dict]:
        files = [{"name": e["name"], "size": (self.work / "files" / e["path"]).stat().st_size}
                 for e in self.m["files"].values()]
        return sorted(files, key=lambda f: f["name"].lower())

    def read(self, name: str) -> bytes:
        return (self.work / "files" / self._entry(name)["path"]).read_bytes()

    def write(self, name: str, data: bytes) -> None:
        name = check_name(name)
        self._put(name, data)
        self._mark(self.m["files"][name.upper()]["name"], dirty=True)

    def delete(self, name: str) -> None:
        entry = self._entry(name)
        del self.m["files"][entry["name"].upper()]
        (self.work / "files" / entry["path"]).unlink()
        self._mark(entry["name"], dirty=False)

    def status(self) -> dict:
        return {"source": str(self.source), "format": self.m["format"], "protected": self.m["protected"],
                "file_count": len(self.m["files"]), "dirty": sorted(self.m["dirty"]),
                "deleted": sorted(self.m["deleted"]), "unnamed_files": len(self.m["unnamed"]),
                "source_changed": self.source_changed(), "problems": self.m["problems"]}

    # saving
    def save(self, dest=None, format: str | None = None, force: bool = False) -> dict:
        dest = Path(dest).resolve() if dest else self.source
        fmt = format or self.m["format"]
        in_place = dest == self.source
        if fmt not in ("mpq", "folder"):
            raise ToolError("bad_format", f"unknown format {fmt!r}", hint="use 'mpq' or 'folder'")
        if in_place and fmt != self.m["format"]:
            raise ToolError("format_change_in_place", "changing the format needs a different destination",
                            hint="pass dest")
        if fmt == "folder" and self.m["unnamed"]:
            raise ToolError("unnamed_files", "this map has files with unknown names that a folder cannot hold",
                            hint="save with format='mpq'")
        if in_place and not force and self.source_changed():
            raise ToolError("source_changed", "the map was modified outside this working copy since it was opened",
                            hint="map_close(discard=true) and reopen to pick up those changes, or force=true to overwrite them")
        if in_place and not (self.m["dirty"] or self.m["deleted"]) and not force:
            return {"saved": False, "reason": "no changes", "path": str(dest)}
        pathguard.ensure_writable(dest)
        files = {e["name"]: (self.work / "files" / e["path"]).read_bytes() for e in self.m["files"].values()}
        backup = self._backup(dest)
        if fmt == "mpq":
            self._write_mpq(dest, files)
        else:
            self._write_folder(dest, files)
        if in_place:
            self.m["fingerprint"] = fingerprint(dest)
            self.m["dirty"], self.m["deleted"] = [], []
            self._flush()
        return {"saved": True, "path": str(dest), "format": fmt, "backup": backup}

    def _write_mpq(self, dest: Path, files: dict[str, bytes]) -> None:
        preserved = tuple(RawEntry(data=(self.work / "unnamed" / f"{i}.bin").read_bytes(), **u)
                          for i, u in enumerate(self.m["unnamed"]))
        prefix = self.work / "prefix.bin"
        kwargs = {"prefix": prefix.read_bytes() if prefix.is_file() else b"", "sector_size": self.m["sector_size"]}
        if preserved:
            kwargs.update(preserved=preserved, hash_size=self.m["hash_size"],
                          reserved_slots=frozenset(self.m["reserved_slots"]))
        try:
            data = write_archive(files, **kwargs)
        except MpqError as e:
            raise ToolError("write_failed", str(e)) from e
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".wc3mcp-tmp")
        tmp.write_bytes(data)
        os.replace(tmp, dest)

    def _write_folder(self, dest: Path, files: dict[str, bytes]) -> None:
        tmp = dest.with_name(dest.name + ".wc3mcp-tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        for name, data in files.items():
            target = tmp / check_name(name).replace("\\", "/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        old = dest.with_name(dest.name + ".wc3mcp-old")
        if dest.exists():
            os.replace(dest, old)
        os.replace(tmp, dest)
        if old.is_dir():
            shutil.rmtree(old)
        elif old.exists():
            old.unlink()

    def _backup(self, dest: Path) -> str | None:
        if not dest.exists():
            return None
        folder = config.home() / "backups" / f"{dest.stem}-{project_id(dest)}"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / (time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1_000_000:06d}{dest.suffix}")
        if dest.is_dir():
            shutil.copytree(dest, target)
        else:
            shutil.copy2(dest, target)
        for old in sorted(folder.iterdir())[:-BACKUPS_KEPT]:
            shutil.rmtree(old) if old.is_dir() else old.unlink()
        return str(target)

    # snapshots
    def snapshot(self, action: str, label: str | None = None) -> dict:
        root = config.home() / "snapshots" / self.work.name
        if action == "list":
            return {"snapshots": sorted(p.name for p in root.iterdir()) if root.is_dir() else []}
        if not label or not all(c.isalnum() or c in "-_." for c in label) or label in (".", ".."):
            raise ToolError("bad_label", "snapshot labels use letters, digits, '-', '_' and '.'")
        snap = root / label
        if action == "create":
            shutil.rmtree(snap, ignore_errors=True)
            shutil.copytree(self.work, snap)
            return {"created": label}
        if action not in ("restore", "diff"):
            raise ToolError("bad_action", f"unknown snapshot action {action!r}", hint="create, restore, list or diff")
        if not snap.is_dir():
            raise ToolError("no_such_snapshot", f"snapshot {label!r} does not exist", hint="map_snapshot action=list")
        snap_files = json.loads((snap / "manifest.json").read_text("utf-8"))["files"]
        if action == "diff":
            cur = self.m["files"]

            def digest(base: Path, e: dict) -> str:
                return hashlib.sha256((base / "files" / e["path"]).read_bytes()).hexdigest()

            return {"added": sorted(cur[k]["name"] for k in cur.keys() - snap_files.keys()),
                    "removed": sorted(snap_files[k]["name"] for k in snap_files.keys() - cur.keys()),
                    "changed": sorted(cur[k]["name"] for k in cur.keys() & snap_files.keys()
                                      if digest(self.work, cur[k]) != digest(snap, snap_files[k]))}
        shutil.rmtree(self.work / "files")
        shutil.copytree(snap / "files", self.work / "files")
        self.m["files"] = snap_files
        self.m["dirty"], self.m["deleted"] = sorted(e["name"] for e in snap_files.values()), []
        self._flush()
        return {"restored": label}

    def close(self, discard: bool = False) -> dict:
        if (self.m["dirty"] or self.m["deleted"]) and not discard:
            raise ToolError("unsaved_changes", "the working copy has unsaved edits",
                            hint="map_save first, or map_close with discard=true",
                            dirty=self.m["dirty"], deleted=self.m["deleted"])
        shutil.rmtree(self.work, ignore_errors=True)
        return {"closed": str(self.source)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& $PY -m pytest tests/project -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/wc3mcp/project tests/project
git commit -m "feat(project): map working copies with backups, snapshots, folder maps" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

### Task 9: MCP server (`map_*`, `data_*` tools)

**Files:**
- Create: `src/wc3mcp/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: Task 1 `config`, `ToolError`; Task 5 `open_storage`; Task 7 `Catalog`; Task 8 `MapProject`.
- Produces: module-level `mcp: FastMCP` named `wc3`; tools `map_open(path)`, `map_close(path, discard=False)`, `map_save(path, dest=None, format=None, force=False)`, `map_status(path, include_files=True)`, `map_file_read(path, name, encoding="text", offset=0, length=65536)`, `map_file_write(path, name, content="", encoding="text", delete=False)`, `map_snapshot(path, action, label=None)`, `data_search(kind, query="", limit=50, offset=0, locale="enUS", balance="Custom_V1", hd=True)`, `data_get(kind, id, fields=None, locale="enUS", balance="Custom_V1", hd=True)`, `data_file(path, encoding="text", offset=0, length=65536)`; `main()` (file logging to `config.home()/logs/wc3mcp.log`, stdio transport).
- Error contract: a `ToolError` becomes an MCP error result whose text is `Error executing tool <name>: <json of ToolError.to_dict()>`. New error codes: `not_open`, `no_install`, `bad_content`.

- [ ] **Step 1: Write the failing test**

`tests/test_server.py`:
```python
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.memory import create_connected_server_and_client_session

from corpus import needs_install
from wc3mcp import server
from wc3mcp.mpq.reader import Archive
from wc3mcp.mpq.writer import write_archive

EXPECTED = {"map_open", "map_close", "map_save", "map_status", "map_file_read", "map_file_write", "map_snapshot",
            "data_search", "data_get", "data_file"}


def call(name: str, args: dict):
    async def run():
        async with create_connected_server_and_client_session(server.mcp._mcp_server) as client:
            return await client.call_tool(name, args)
    return asyncio.run(run())


def payload(result) -> dict:
    assert not result.isError, result.content[0].text
    return json.loads(result.content[0].text)


def test_tools_are_registered():
    assert EXPECTED <= {t.name for t in asyncio.run(server.mcp.list_tools())}


def test_map_tools_end_to_end(tmp_path):
    src = tmp_path / "m.w3x"
    src.write_bytes(write_archive({"war3map.j": b"old"}))
    path = str(src)
    assert payload(call("map_open", {"path": path}))["file_count"] == 1
    payload(call("map_file_write", {"path": path, "name": "war3map.j", "content": "new"}))
    assert payload(call("map_save", {"path": path}))["saved"]
    assert payload(call("map_file_read", {"path": path, "name": "war3map.j"}))["content"] == "new"
    assert Archive.open(src).read("war3map.j") == b"new"
    payload(call("map_close", {"path": path}))
    err = call("map_status", {"path": path})
    assert err.isError and json.loads(err.content[0].text.split(": ", 1)[1])["code"] == "not_open"


@needs_install
def test_data_tools():
    hits = payload(call("data_search", {"kind": "unit", "query": "archmage", "balance": None}))["results"]
    assert "Hamg" in [h["id"] for h in hits]
    got = payload(call("data_get", {"kind": "ability", "id": "AHbz", "fields": ["Hbz1"], "balance": None}))
    assert got["fields"]["Hbz1"]["values"] == ["6", "8", "10"]
    common = payload(call("data_file", {"path": "Scripts/common.j", "length": 200}))
    assert common["path"] == "War3.w3mod:Scripts/common.j" and common["truncated"]


def test_stdio_server_starts(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(Path(server.__file__).parents[1]), "WC3MCP_HOME": str(tmp_path / "home")}
    params = StdioServerParameters(command=sys.executable, args=["-m", "wc3mcp.server"], env=env)

    async def run():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return {t.name for t in (await session.list_tools()).tools}

    assert EXPECTED <= asyncio.run(run())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& $PY -m pytest tests/test_server.py -v`
Expected: FAIL with `ImportError: cannot import name 'server' from 'wc3mcp'`

- [ ] **Step 3: Write minimal implementation**

`src/wc3mcp/server.py`:
```python
"""wc3-mcp MCP server. Phase 1: map working copies and game data."""
import base64
import functools
import json
import logging
import time
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError as McpToolError

from . import config
from .casc.storage import open_storage
from .errors import ToolError
from .gamedata.catalog import Catalog
from .project.workspace import MapProject

log = logging.getLogger("wc3mcp")
mcp = FastMCP("wc3", instructions=(
    "Warcraft III map making. map_open copies a map into a private working copy; change files there; map_save "
    "backs up the original and replaces it atomically. The game install is read-only. Look up units, abilities, "
    "items, buffs, upgrades, doodads, destructibles, terrain, sounds and assets with data_search / data_get."))

Kind = Literal["unit", "item", "ability", "buff", "upgrade", "destructible", "doodad", "tile", "cliff", "water",
               "sound", "model", "icon", "file"]
MAX_READ = 1024 * 1024
_projects: dict[str, MapProject] = {}
_catalogs: dict[tuple, Catalog] = {}
_storage = None


def _brief(kwargs: dict) -> str:
    return json.dumps({k: (v[:80] + "..." if isinstance(v, str) and len(v) > 80 else v) for k, v in kwargs.items()},
                      default=str)


def _tool(fn):
    """Register `fn` as a tool; log each call; expose ToolError as structured MCP error text."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            result = fn(*args, **kwargs)
        except ToolError as e:
            log.info("%s error %s %s", fn.__name__, e.code, _brief(kwargs))
            raise McpToolError(json.dumps(e.to_dict())) from e
        except Exception:
            log.exception("%s crashed %s", fn.__name__, _brief(kwargs))
            raise
        log.info("%s ok %.0fms %s", fn.__name__, (time.perf_counter() - start) * 1000, _brief(kwargs))
        return result
    return mcp.tool()(wrapper)


def _key(path: str) -> str:
    return str(Path(path).resolve()).lower()


def _project(path: str) -> MapProject:
    p = _projects.get(_key(path))
    if p is None:
        raise ToolError("not_open", f"map is not open: {path}", hint="call map_open first")
    return p


def _catalog(locale: str, balance: str | None, hd: bool) -> Catalog:
    global _storage
    if _storage is None:
        root = config.install_root()
        if not (root / ".build.info").is_file():
            raise ToolError("no_install", f"Warcraft III install not found at {root}", hint="set WC3MCP_INSTALL")
        _storage = open_storage(root)
    key = (locale, balance, hd)
    if key not in _catalogs:
        _catalogs[key] = Catalog(_storage, locale=locale, balance=balance, hd=hd)
    return _catalogs[key]


def _encode(data: bytes, encoding: str, offset: int, length: int) -> dict:
    chunk = data[max(offset, 0):max(offset, 0) + max(0, min(length, MAX_READ))]
    if encoding == "text":
        content = chunk.decode("utf-8", "replace")
    elif encoding == "base64":
        content = base64.b64encode(chunk).decode("ascii")
    else:
        content = chunk.hex()
    return {"size": len(data), "offset": offset, "length": len(chunk), "encoding": encoding, "content": content,
            "truncated": max(offset, 0) + len(chunk) < len(data)}


@_tool
def map_open(path: str) -> dict:
    """Open a Warcraft III map (.w3x/.w3m archive or map folder) into a private working copy.
    Re-opening resumes unsaved edits. Returns the map status."""
    p = MapProject.open(path)
    _projects[_key(path)] = p
    return p.status()


@_tool
def map_close(path: str, discard: bool = False) -> dict:
    """Close an open map. Refuses while there are unsaved edits unless discard=true."""
    result = _project(path).close(discard)
    del _projects[_key(path)]
    return result


@_tool
def map_save(path: str, dest: str | None = None, format: Literal["mpq", "folder"] | None = None,
             force: bool = False) -> dict:
    """Save the working copy. By default backs up the original and replaces it atomically. dest/format write a
    copy elsewhere (mpq archive or map folder). Refuses if the original changed on disk since opening unless
    force=true."""
    return _project(path).save(dest=dest, format=format, force=force)


@_tool
def map_status(path: str, include_files: bool = True) -> dict:
    """Status of an open map: format, protection, dirty/deleted files, whether the original changed on disk, and
    the file list."""
    p = _project(path)
    status = p.status()
    if include_files:
        status["files"] = p.list_files()
    return status


@_tool
def map_file_read(path: str, name: str, encoding: Literal["text", "base64", "hex"] = "text", offset: int = 0,
                  length: int = 65536) -> dict:
    """Read a file inside an open map (e.g. war3map.j, war3map.wts). Page large files with offset/length."""
    return {"name": name, **_encode(_project(path).read(name), encoding, offset, length)}


@_tool
def map_file_write(path: str, name: str, content: str = "", encoding: Literal["text", "base64"] = "text",
                   delete: bool = False) -> dict:
    """Create, replace or delete (delete=true) a file in an open map's working copy. Raw escape hatch: prefer typed
    tools when they exist. Changes reach the map file on map_save."""
    p = _project(path)
    if delete:
        p.delete(name)
        return {"deleted": name}
    try:
        data = content.encode("utf-8") if encoding == "text" else base64.b64decode(content, validate=True)
    except ValueError as e:
        raise ToolError("bad_content", f"content is not valid {encoding}: {e}") from e
    p.write(name, data)
    return {"written": name, "size": len(data)}


@_tool
def map_snapshot(path: str, action: Literal["create", "restore", "list", "diff"], label: str | None = None) -> dict:
    """Named checkpoints of an open map's working copy: create, restore, list, or diff against the current state."""
    return _project(path).snapshot(action, label)


@_tool
def data_search(kind: Kind, query: str = "", limit: int = 50, offset: int = 0, locale: str = "enUS",
                balance: str | None = "Custom_V1", hd: bool = True) -> dict:
    """Search base game data by id, name or editor suffix (object, terrain and sound kinds) or by path substring or
    glob (model, icon, file). balance selects the gameplay data set: Custom_V1 (current), Custom_V0, Melee_V0, or
    null for the base files."""
    results = _catalog(locale, balance, hd).search(kind, query, limit=min(limit, 500), offset=offset)
    return {"kind": kind, "query": query, "offset": offset, "count": len(results), "results": results}


@_tool
def data_get(kind: Kind, id: str, fields: list[str] | None = None, locale: str = "enUS",
             balance: str | None = "Custom_V1", hd: bool = True) -> dict:
    """Base data for one object with editor field raw codes, names, types and values (per level for leveled
    fields). fields filters by raw code (e.g. uhpm), field name, or display-name substring."""
    return _catalog(locale, balance, hd).get(kind, id, fields)


@_tool
def data_file(path: str, encoding: Literal["text", "base64", "hex"] = "text", offset: int = 0,
              length: int = 65536) -> dict:
    """Read a raw file from the game's CASC storage, e.g. War3.w3mod:Scripts/common.j or UI/TriggerData.txt. Paths
    without a 'War3.w3mod:' prefix resolve through the enUS locale and base layers."""
    storage = _catalog("enUS", None, False).storage
    full = path if ":" in path else storage.resolve(path)
    data = storage.read(full) if full else None
    if data is None:
        raise ToolError("not_found", f"no game data file {path!r}", hint="data_search kind=file finds paths")
    return {"path": full, **_encode(data, encoding, offset, length)}


def main() -> None:
    logs = config.home() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=logs / "wc3mcp.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    mcp.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `& $PY -m pytest tests/test_server.py -v`
Expected: 4 passed (`test_data_tools` skips without an install)

- [ ] **Step 5: Commit**

```bash
git add src/wc3mcp/server.py tests/test_server.py
git commit -m "feat(server): wc3 MCP server with map and game data tools" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

### Task 10: Registration and full verification

**Files:**
- Create or merge: `D:\Warcraft III\.mcp.json` (outside the repo; not committed)

**Interfaces:**
- Consumes: Task 9 `python -m wc3mcp.server`.
- Produces: Claude Code project-scoped MCP server `wc3` for sessions started in `D:\Warcraft III`.

- [ ] **Step 1: Check for an existing config**

Run: `Test-Path "D:\Warcraft III\.mcp.json"`
Expected: `False`. If `True`, read it and add only the `wc3` entry below under `mcpServers`, keeping every other entry unchanged.

- [ ] **Step 2: Write the registration**

`D:\Warcraft III\.mcp.json`:
```json
{
  "mcpServers": {
    "wc3": {
      "command": "%LOCALAPPDATA%\\Microsoft\\WindowsApps\\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\\python.exe",
      "args": ["-m", "wc3mcp.server"],
      "env": {"PYTHONPATH": "D:\\Warcraft III\\wc3-mcp\\src"}
    }
  }
}
```

- [ ] **Step 3: Verify the registered command starts and lists tools**

Run (from `D:\Warcraft III\wc3-mcp`):
```powershell
$env:PYTHONPATH = "D:\Warcraft III\wc3-mcp\src"; & $PY -c "import asyncio, json; from mcp import ClientSession, StdioServerParameters; from mcp.client.stdio import stdio_client; cfg = json.load(open(r'D:\Warcraft III\.mcp.json'))['mcpServers']['wc3']; import os; p = StdioServerParameters(command=cfg['command'], args=cfg['args'], env={**os.environ, **cfg['env']});
async def m():
    async with stdio_client(p) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize(); print(sorted(t.name for t in (await s.list_tools()).tools))
asyncio.run(m())"
```
Expected: `['data_file', 'data_get', 'data_search', 'map_close', 'map_file_read', 'map_file_write', 'map_open', 'map_save', 'map_snapshot', 'map_status']`

- [ ] **Step 4: Run the whole suite**

Run: `& $PY -m pytest -v`
Expected: all tests pass; corpus tests run (not skipped) on this machine.

- [ ] **Step 5: Tell the user**

Report: the `wc3` server is registered for `D:\Warcraft III`; start a new Claude Code session there and approve the project MCP server to load the 10 tools. Nothing to commit (the config lives outside the repo).
