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
from .ops import imports as imports_ops
from .ops import info as info_ops
from .ops import objdata as objdata_ops
from .ops import triggers as triggers_ops
from .project.workspace import MapProject

log = logging.getLogger("wc3mcp")
mcp = FastMCP("wc3", instructions=(
    "Warcraft III map making. map_open copies a map into a private working copy; change files there; map_save "
    "backs up the original and replaces it atomically. The game install is read-only. Look up units, abilities, "
    "items, buffs, upgrades, doodads, destructibles, terrain, sounds and assets with data_search / data_get."))

Kind = Literal["unit", "item", "ability", "buff", "upgrade", "destructible", "doodad", "tile", "cliff", "water",
               "sound", "model", "icon", "file", "trigger_function", "trigger_type", "trigger_preset"]
ObjectKind = Literal["unit", "item", "destructible", "doodad", "ability", "buff", "upgrade"]
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
    glob (model, icon, file); trigger_function / trigger_type / trigger_preset search GUI trigger functions, variable
    types and preset values. balance selects the gameplay data set: Custom_V1 (current), Custom_V0, Melee_V0, or
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


def setup_logging() -> Path:
    """Tool-call log file. FastMCP() already installed a root handler, so logging.basicConfig would be a no-op."""
    path = config.home() / "logs" / "wc3mcp.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not any(isinstance(h, logging.FileHandler) and Path(h.baseFilename) == path for h in log.handlers):
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(handler)
    log.setLevel(logging.INFO)
    return path


def main() -> None:
    setup_logging()
    mcp.run()


if __name__ == "__main__":
    main()
