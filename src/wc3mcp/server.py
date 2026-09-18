"""wc3-mcp MCP server. Phase 1: map working copies and game data."""
import base64
import functools
import json
import logging
import shutil
import time
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP, Image
from mcp.server.fastmcp.exceptions import ToolError as McpToolError

from . import config
from .casc.storage import open_storage
from .mpq.reader import Archive as MpqArchive
from .desktop import editor as desktop_editor
from .desktop import game as desktop_game
from .errors import ToolError
from . import help as help_pages
from .gamedata.catalog import COMPACT_NOTE, Catalog
from .gamedata.catalog import compact as catalog_compact
from .ops import ai as ai_ops
from .ops import assets as assets_ops
from .ops import campaign as campaign_ops
from .ops import elements as elements_ops
from .ops import imports as imports_ops
from .ops import heightmap as heightmap_ops
from .ops import info as info_ops
from .ops import layout as layout_ops
from .ops import newmap as newmap_ops
from .ops import objdata as objdata_ops
from .ops import placed as placed_ops
from .ops import probe as probe_ops
from .ops import script as script_ops
from .ops import terrain as terrain_ops
from .ops import triggers as triggers_ops
from .ops import ui as ui_ops
from .project.workspace import MapProject, project_id

log = logging.getLogger("wc3mcp")
mcp = FastMCP("wc3", instructions=(
    "Warcraft III map making. map_open copies a map into a private working copy; change files there; map_save "
    "backs up the original and replaces it atomically. The game install is read-only. Look up units, abilities, "
    "items, buffs, upgrades, doodads, destructibles, terrain, sounds and assets with data_search / data_get."))

Kind = Literal["unit", "item", "ability", "buff", "upgrade", "destructible", "doodad", "tile", "cliff", "water",
               "weather", "sound", "model", "icon", "file", "trigger_function", "trigger_type", "trigger_preset",
               "native"]
ObjectKind = Literal["unit", "item", "destructible", "doodad", "ability", "buff", "upgrade"]
MAX_READ = 1024 * 1024
MAX_BATCH = 20
# tools that answer with a picture, which a batch result cannot carry
IMAGE_TOOLS = ("terrain_render", "editor_screenshot", "asset_preview")
TOOLS: dict[str, object] = {}       # tool name -> the plain function behind it, for wc3_batch
_projects: dict[str, MapProject] = {}
_catalogs: dict[tuple, Catalog] = {}
_storage = None


def _brief(kwargs: dict) -> str:
    return json.dumps({k: (v[:80] + "..." if isinstance(v, str) and len(v) > 80 else v) for k, v in kwargs.items()},
                      default=str)


def _tool(fn):
    """Register `fn` as a tool; log each call; expose ToolError as structured MCP error text."""
    TOOLS[fn.__name__] = fn   # the plain function, for wc3_batch

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        ms = lambda: (time.perf_counter() - start) * 1000  # noqa: E731
        try:
            result = fn(*args, **kwargs)
        except ToolError as e:
            log.info("%s error %s %.0fms %s", fn.__name__, e.code, ms(), _brief(kwargs))
            raise McpToolError(json.dumps(e.to_dict())) from e
        except Exception:
            log.exception("%s crashed %.0fms %s", fn.__name__, ms(), _brief(kwargs))
            raise
        # result bytes: what the answer costs the conversation, so a later session can see where the tokens go
        log.info("%s ok %.0fms %dB %s", fn.__name__, ms(), len(json.dumps(result, default=str)), _brief(kwargs))
        return result
    return mcp.tool()(wrapper)


def _key(path: str) -> str:
    return str(Path(path).resolve()).lower()


def _project(path: str) -> MapProject:
    p = _projects.get(_key(path))
    if p is None:
        # the working copy outlives the server process: resume it instead of losing the session on a restart
        resolved = Path(path).resolve() if Path(path).exists() else None
        if resolved and (config.home() / "work" / project_id(resolved) / "manifest.json").is_file():
            p = _projects[_key(path)] = MapProject.open(resolved)
            log.info("resumed the working copy of %s", resolved)
        else:
            raise ToolError("not_open", f"map is not open: {path}", hint="call map_open first")
    return p


def _ops(ops: list | None, ops_file: str | None) -> list:
    """Inline ops, or the same JSON array from a local file (large generated batches stay out of the conversation)."""
    if (ops is None) == (ops_file is None):
        raise ToolError("bad_value", "pass either ops or ops_file", path="ops")
    if ops_file is None:
        return ops
    try:
        loaded = json.loads(triggers_ops.read_text_file(ops_file, "ops_file"))
    except json.JSONDecodeError as e:
        raise ToolError("bad_value", f"ops_file {ops_file} is not JSON: {e}", path="ops_file") from e
    if isinstance(loaded, dict) and isinstance(loaded.get("ops"), list):
        loaded = loaded["ops"]
    if not isinstance(loaded, list):
        raise ToolError("bad_value", f"ops_file {ops_file} must hold a JSON array of ops", path="ops_file")
    return loaded


MAX_IDS = 50


def _many(kind: str, id, get, verbose: bool) -> dict:
    """One id or a list of them through `get`, verbose or compact (data_get / objdata_get share this)."""
    ids = [id] if isinstance(id, str) else id
    if not isinstance(ids, list) or not ids or not all(isinstance(i, str) and i for i in ids):
        raise ToolError("bad_value", "id must be an id or a list of ids", path="id")
    if len(ids) > MAX_IDS:
        raise ToolError("bad_value", f"{len(ids)} ids at once; the limit is {MAX_IDS}", path="id")
    docs = [get(one) for one in ids]
    if not verbose:
        docs = [catalog_compact(doc) for doc in docs]
    # the note only fits documents that have object fields (trigger data and asset paths pass through as they are)
    note = {} if verbose or not any("fields" in doc for doc in docs) else {"note": COMPACT_NOTE}
    if isinstance(id, str):
        return {**docs[0], **note}
    return {"kind": kind, "count": len(docs), "objects": docs, **note}


def _version_reader(project, against: str):
    """A read(name) -> bytes | None over another version of the map: the file on disk, or a snapshot."""
    if against == "source":
        source = Path(project.m["source"])
        if source.is_dir():
            return lambda name: (source / name.replace("\\", "/")).read_bytes()                 if (source / name.replace("\\", "/")).is_file() else None
        if not source.is_file():
            raise ToolError("not_found", f"the map file {source} is gone, so there is nothing to compare with",
                            hint="map_snapshot create makes a version to compare with instead")
        archive = MpqArchive.open(source)
        return lambda name: archive.read(name) if archive.find(name) is not None else None
    folder = config.home() / "snapshots" / project.work.name / against / "files"
    if not folder.is_dir():
        raise ToolError("no_such_snapshot", f"snapshot {against!r} does not exist",
                        hint='map_snapshot action=list, or against="source" for the map file')
    files = json.loads((folder.parent / "manifest.json").read_text("utf-8"))["files"]
    paths = {entry["name"].upper(): folder / entry["path"] for entry in files.values()}

    def read(name: str):
        found = paths.get(name.upper())
        return found.read_bytes() if found and found.is_file() else None

    return read


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
def wc3_help(topic: str | None = None) -> dict:
    """The full reference of one tool: every op shape, field list and pitfall, which the tool descriptions leave out
    so a session does not pay for all of it up front. Without a topic it lists them. Topics: placed_edit,
    triggers_edit, terrain_edit, terrain_get, game_test, data_search, map_save, map_validate, asset_edit,
    campaign_edit, ui_edit."""
    return help_pages.help_text(topic)


@_tool
def wc3_batch(calls: list[dict], stop_on_error: bool = True) -> dict:
    """Run several of these tools in one round trip: [{"tool": "objdata_edit", "args": {...}}, {"tool": "script_build",
    "args": {"path": "..."}}, {"tool": "map_validate", "args": {"path": "..."}}]. Each call answers as it would on its
    own, under results[i].result, or with its error under results[i].error; stop_on_error=false runs the rest anyway.
    Use it for the chains that always go together (edit, rebuild, check) instead of one call each. At most 20 calls,
    no nesting, and the tools that answer with a picture (terrain_render, editor_screenshot, asset_preview) have to be
    called on their own."""
    if not isinstance(calls, list) or not calls:
        raise ToolError("bad_value", "calls is a list of {\"tool\", \"args\"}", path="calls")
    if len(calls) > MAX_BATCH:
        raise ToolError("bad_value", f"{len(calls)} calls; the limit is {MAX_BATCH}", path="calls")
    plan = []
    for i, call in enumerate(calls):
        name = call.get("tool") if isinstance(call, dict) else None
        args = call.get("args", {}) if isinstance(call, dict) else None
        if name not in TOOLS or name == "wc3_batch":
            raise ToolError("not_found", f"calls[{i}]: no tool {name!r}" if name != "wc3_batch" else
                            f"calls[{i}]: a batch cannot hold another batch", path=f"calls[{i}].tool")
        if name in IMAGE_TOOLS:
            raise ToolError("bad_value", f"calls[{i}]: {name} answers with a picture, so call it on its own",
                            path=f"calls[{i}].tool")
        if not isinstance(args, dict):
            raise ToolError("bad_value", f"calls[{i}]: args is an object of the tool's parameters",
                            path=f"calls[{i}].args")
        plan.append((name, args))
    results, failed = [], 0
    for i, (name, args) in enumerate(plan):
        try:
            results.append({"tool": name, "ok": True, "result": TOOLS[name](**args)})
        except ToolError as e:
            failed += 1
            results.append({"tool": name, "ok": False, "error": e.to_dict()})
            if stop_on_error:
                break
        except TypeError as e:   # wrong parameters for that tool: the same mistake as a bad_value, not a crash
            failed += 1
            results.append({"tool": name, "ok": False,
                            "error": {"code": "bad_value", "message": f"{name}: {e}"}})
            if stop_on_error:
                break
    return {"count": len(results), "failed": failed, "ran": len(results), "of": len(plan), "results": results}


@_tool
def map_open(path: str, merge_external: bool = False) -> dict:
    """Open a Warcraft III map (.w3x/.w3m archive or map folder) or campaign (.w3n) into a private working copy.
    Re-opening resumes unsaved edits, and so does any tool call after the server restarts (the working copy lives on
    disk). When the map file changed meanwhile (a World Editor save) and the working copy has edits, merge_external=true
    keeps the changed files of the working copy and takes every other file from the map. Returns the map status.
    Campaigns work with campaign_get / campaign_edit, objdata_* and imports_edit (their war3campaign.* files);
    map_save, map_status and map_validate take them too."""
    p = MapProject.open(path, merge_external=merge_external)
    _projects[_key(path)] = p
    return p.status()


@_tool
def map_new(path: str, width: int = 64, height: int = 64, tileset: str = "L", name: str = "Just another Warcraft III map",
            author: str = "Unknown", players: int = 2, script_language: Literal["jass", "lua"] = "jass",
            format: Literal["mpq", "folder"] = "mpq", fill_tile: str | None = None) -> dict:
    """Create a new map at path (it must not exist) and open it: width/height in tiles (32-480, steps of 32, the
    playable area is 12 tiles narrower and shorter), tileset letter (data_search kind=tile, tileset=<letter>),
    players 1-24 with start locations, one force, flat terrain, the default Melee Initialization trigger and a
    generated war3map.j, or war3map.lua for script_language=lua. The terrain is filled with fill_tile, or with the
    tileset's first tile, which is not always the obvious one (Lordaeron Summer starts at Ldrt, dirt, so a road
    painted with Ldrt would be invisible). The result names it in fill_tile."""
    project = newmap_ops.new_map(path, _catalog("enUS", "Custom_V1", True), width, height, tileset, name, author, players,
                                 script_language, format, fill_tile)
    _projects[_key(path)] = project
    return {**project.status(), "fill_tile": newmap_ops.fill_tile_of(project)}


@_tool
def campaign_new(path: str, name: str | None = None, author: str | None = None,
                 format: Literal["mpq", "folder"] = "mpq") -> dict:
    """Create an empty campaign (.w3n, it must not exist) as the Campaign Editor does and open it. Add maps and
    campaign screen buttons with campaign_edit."""
    project = campaign_ops.new_campaign(path, _catalog("enUS", "Custom_V1", True), name, author, format)
    _projects[_key(path)] = project
    return project.status()


@_tool
def campaign_get(path: str) -> dict:
    """An open campaign as the Campaign Editor shows it: name, difficulty, author, description, variable difficulty,
    minimap image, loading screen (background, background version, ambient sound, cursor, custom fog), campaign
    screen buttons (chapter, title, map, visible, cinematic), the maps inside, import and object data counts."""
    return campaign_ops.campaign_get(_project(path), _catalog("enUS", "Custom_V1", True))


@_tool
def campaign_edit(path: str, ops: list[dict]) -> dict:
    """Change an open campaign (.w3n) with an all-or-nothing batch applied to the campaign_get document:
    set/append/remove on its name, minimap, loading screen, fog and buttons, plus add_map, replace_map, remove_map and
    extract_map for the maps inside it (edit one with map_open, put it back with replace_map).
    wc3_help("campaign_edit") has the op shapes."""
    return campaign_ops.campaign_edit(_project(path), _catalog("enUS", "Custom_V1", True), ops)


@_tool
def map_close(path: str, discard: bool = False) -> dict:
    """Close an open map. Refuses while there are unsaved edits unless discard=true."""
    result = _project(path).close(discard)
    del _projects[_key(path)]
    return result


SCRIPT_SOURCES = {"war3map.wtg", "war3map.wct", "war3map.w3r", "war3map.w3c", "war3map.w3s", "war3map.doo",
                  "war3mapunits.doo", "war3map.w3i"}
SCRIPT_FILES = {"war3map.j", "war3map.lua", "scripts\\war3map.j", "scripts\\war3map.lua"}


def _refresh_minimap(project, catalog, dirty: set, warnings: list) -> str | None:
    """Like the World Editor on save: war3mapMap.blp follows the terrain unless the map imports its own. The game
    quits right after login on a map without one."""
    files = {f["name"].lower() for f in project.list_files()}
    if "war3map.w3e" not in files:
        return None
    try:
        if "war3mapmap.blp" not in files:
            state = "added"
        elif "war3map.w3e" in dirty and not any(i["path"].replace("\\", "/").lower() == "war3mapmap.blp"
                                                 for i in imports_ops.imports_list(project)):
            state = "rebuilt"
        else:
            return None
        project.write("war3mapMap.blp", terrain_ops.minimap(project, catalog))
        return state
    except ToolError as e:
        warnings.append(f"war3mapMap.blp (minimap) not refreshed: {e}")
        return None


@_tool
def map_save(path: str, dest: str | None = None, format: Literal["mpq", "folder"] | None = None,
             force: bool = False, rebuild_script: Literal["auto", "always", "never"] = "auto",
             validate: bool = True, merge_external: bool = False) -> dict:
    """Save the working copy: back up the original and replace it atomically, or write a copy elsewhere with
    dest/format (an mpq archive or a map folder). It regenerates the map script when its sources changed
    (rebuild_script auto/always/never), redraws the minimap, runs map_validate and compiles the script, and refuses
    to save on errors. A map file that changed on disk since it was opened (a World Editor save) needs
    merge_external=true, which keeps this copy's changes and takes everything else from the file.
    wc3_help("map_save") has the whole round trip with the editor."""
    project = _project(path)
    merged = project.merge_source() if merge_external and project.source_changed() else None
    catalog = _catalog("enUS", script_ops.balance(project), True)
    warnings = []
    if dest is None:  # take turns with the World Editor on the same file
        seen = desktop_editor.EDITOR.status()
        if seen["running"] and seen["map"] and _key(seen["map"]) == _key(str(project.source)):
            if seen["dirty"]:
                raise ToolError("open_in_editor", f"{project.source.name} has unsaved changes in the World Editor",
                                hint="ask the user, or save or close it there (editor_map save / close) first")
            warnings.append("the map is open in the World Editor; editor_map reload shows the saved version there")
    script = None
    dirty = {name.lower() for name in project.status()["dirty"]}
    if rebuild_script == "always" or (rebuild_script == "auto" and dirty & SCRIPT_SOURCES):
        try:
            script = script_ops.script_build(project, catalog)
        except ToolError as e:
            if rebuild_script == "always" or e.code not in ("no_triggers", "no_script",
                                                             "not_editor_script"):
                raise
            script = {"changed": False, "skipped": str(e)}
    minimap = _refresh_minimap(project, catalog, dirty, warnings)
    validation = script_ops.map_validate(project, catalog) if validate else None
    if validation and validation["errors"]:
        first = validation["errors"][0]
        raise ToolError("validation_failed", f"{len(validation['errors'])} map validation error(s); first: "
                        f"{first['file']}: {first['message']}", hint="fix them, or save with validate=false",
                        errors=validation["errors"][:20])
    compiled = None
    if validate and ((script or {}).get("changed") or dirty & SCRIPT_FILES):   # a new or edited script is compiled
        compiled = script_ops.script_validate(project, catalog)
        if not compiled["ok"]:
            first = compiled["errors"][0]
            raise ToolError("validation_failed", f"the map script does not compile: {len(compiled['errors'])} "
                            f"error(s); first: line {first.get('line')}: {first['message']}",
                            hint=(f"fix trigger {first['trigger']!r} (trigger_get, triggers_edit script_replace)"
                                  if first.get("trigger") else f"fix {compiled['file']} (script_validate)")
                            + ", or save with validate=false",
                            errors=compiled["errors"][:20])
    try:
        result = project.save(dest=dest, format=format, force=force)
    except ToolError as e:
        seen = desktop_editor.EDITOR.status()
        if (e.code == "file_in_use" and dest is None and seen["running"] and seen["map"]
                and _key(seen["map"]) == _key(str(project.source))):
            raise ToolError("editor_holds_map", f"the World Editor has {project.source.name} open and holds the file",
                            hint="editor_map action=close (the edits stay in the working copy), then map_save again",
                            path=str(project.source)) from e
        if e.code == "file_in_use" and desktop_game.GAME.status()["running"]:
            e.hint = "a game started by game_test may hold the map: game_close, then map_save again"
        raise
    result["warnings"] = warnings
    if merged is not None:
        result["merged"] = merged
    if script is not None:
        result["script"] = script
    if minimap:
        result["minimap"] = minimap
    if validation is not None:
        result["validation"] = {"errors": [], "warning_count": len(validation["warnings"]),
                                "warnings": validation["warnings"][:20]}
        if compiled is not None:
            result["validation"]["script"] = {k: compiled[k] for k in ("ok", "file", "tool", "seconds") if k in compiled}
    return result


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
                balance: str | None = "Custom_V1", hd: bool = True, tileset: str | None = None) -> dict:
    """Search the game data of the installed build: objects (unit, item, ability, buff, upgrade, doodad,
    destructible) by id, name or editor suffix; terrain and sound rows; files (model, icon, file) by path or glob;
    the World Editor's own tables (trigger_function, trigger_type, trigger_preset); and kind=native, the script API
    (common.j, Blizzard.j, common.ai) with real signatures. tileset scopes tiles, cliffs, doodads and destructibles
    to one tileset. balance picks the gameplay data set: Custom_V1 (current), Custom_V0, Melee_V0 or null for the
    base files. wc3_help("data_search") explains each kind and what its results carry."""
    catalog = _catalog(locale, balance, hd)
    results = catalog.search(kind, query, limit=min(limit, 500), offset=offset, tileset=tileset)
    return {"kind": kind, "query": query, "offset": offset, "count": len(results), "results": results,
            **({"tilesets": catalog.tilesets()} if kind in ("tile", "cliff") and not results else {})}


@_tool
def data_get(kind: Kind, id: str | list[str], fields: list[str] | None = None, verbose: bool = False,
             locale: str = "enUS", balance: str | None = "Custom_V1", hd: bool = True) -> dict:
    """Base data for one object, or for a list of ids in one call (objects, in the order asked). fields filters by
    raw code (e.g. uhpm), field name, or display-name substring. verbose=true adds each field's name, category and
    type around its value, which is about ten times the size. Doodads, destructibles and units also list their model
    files and the ones the installed game cannot load in HD or classic graphics (model.missing). An ability carries
    orders: its own order fields (data) and the World Editor's presets for it with their targeting (editor); for a few
    abilities they disagree and only one of them works."""
    catalog = _catalog(locale, balance, hd)
    return _many(kind, id, lambda one: catalog.get(kind, one, fields), verbose)


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
def objdata_get(path: str, kind: ObjectKind, id: str | list[str], fields: list[str] | None = None,
                verbose: bool = False, balance: str | None = "Custom_V1") -> dict:
    """One object as the Object Editor shows it, or a list of ids in one call (objects): base game values merged with
    this map's modifications. modified lists the raw codes the map changes; verbose=true instead gives each field its
    name, type and which levels are modified, at about ten times the size. levels and the per-level lists follow the
    map's own level count (alev, glvl); values the map stores for levels beyond it are listed under unused_levels.
    fields filters by raw code, field name or display-name substring."""
    project, catalog = _project(path), _catalog("enUS", balance, True)
    return _many(kind, id, lambda one: objdata_ops.objdata_get(project, catalog, kind, one, fields), verbose)


@_tool
def objdata_edit(path: str, kind: ObjectKind, ops: list[dict] | None = None, balance: str | None = "Custom_V1",
                 ops_file: str | None = None) -> dict:
    """Create and change objects with an all-or-nothing batch: {"op": "create", "base": "hfoo", "set": {"Name": "Guard",
    "HP": 500}} (id optional, allocated like the editor; base may be one of the map's custom objects, which copies its
    stock base and all its modifications, like the editor's copy and paste), {"op": "set", "id": "h000", "set": {"Hbz1":
    {"1": 7, "2": 9}}} (per-level fields take level keys; stock ids such as hgtw work too), {"op": "reset", "id":
    "h000", "fields": ["uhpm"]}, {"op": "delete", "id": "h000"}. Fields accept raw codes, field names or display names.
    ops_file: a local JSON file holding the ops array instead of ops."""
    return objdata_ops.objdata_edit(_project(path), _catalog("enUS", balance, True), kind, _ops(ops, ops_file))


@_tool
def ui_get(path: str, file: str | None = None) -> dict:
    """Custom user interface of an open map. Without file: the .fdf and .toc files it holds. With one: that layout
    file parsed into frames (type, name, parent, what it inherits) and its statements, plus the problems a check
    found. A file the map does not hold is read from the game data instead, so the stock UI can be studied
    (data_search kind=file query=*.fdf lists it)."""
    return ui_ops.ui_get(_project(path), _catalog("enUS", "Custom_V1", True), file)


@_tool
def ui_edit(path: str, file: str, statements: list[dict] | None = None, text: str | None = None,
            toc: str | None = None) -> dict:
    """Write a custom UI layout into an open map: an .fdf built from statements (the ui_get shape) or from ready
    FDF text, imported under war3mapImported and listed in a .toc beside it. The result carries the frames it defines,
    the problems a check found (unknown frame type, an anchor that is not a corner, a SetPoint to a frame the file
    never defines, a texture the map does not hold) and the script that loads it (BlzLoadTOCFile, then BlzCreateFrame
    or BlzGetFrameByName). wc3_help("ui_edit") has the statement shape and the anchors."""
    return ui_ops.ui_edit(_project(path), _catalog("enUS", "Custom_V1", True), file, statements, text, toc)


@_tool
def objdata_diff(path: str, kind: ObjectKind, against: str = "source", balance: str | None = "Custom_V1") -> dict:
    """What this map's object data of one kind changed against the map file on disk ("source") or a snapshot (its
    label, from map_snapshot): objects added or deleted, and per object each field whose value differs, with the
    value before and after. Use it to review a batch before map_save, or to see what a World Editor session did."""
    project = _project(path)
    return objdata_ops.objdata_diff(project, _catalog("enUS", balance, True), kind,
                                    _version_reader(project, against))


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
def triggers_edit(path: str, ops: list[dict] | None = None, validate: bool = False, ops_file: str | None = None) -> dict:
    """Change the Trigger Editor's categories, GUI variables and triggers, all-or-nothing. Ops: category,
    variable, trigger (GUI events/conditions/actions, or "script"/"script_file" for JASS or Lua), delete, header and
    script_replace (one exact piece of a script). A trigger keeps its place when it is replaced, because the script
    emits trigger functions in tree order; "index" or "after" moves one on purpose. validate=true rebuilds the map
    script and checks it right away, each error with its line inside the script that was sent. ops_file takes the ops
    array from a local JSON file. wc3_help("triggers_edit") has the op shapes and the argument forms."""
    return triggers_ops.triggers_edit(_project(path), _catalog("enUS", "Custom_V1", True), _ops(ops, ops_file), validate)


@_tool
def elements_list(path: str, kind: Literal["region", "camera", "sound"]) -> dict:
    """Regions (war3map.w3r), cameras (war3map.w3c) or sounds (war3map.w3s) of an open map with their gg_rct_ /
    gg_cam_ / gg_snd_ script names. Sounds show flags, distances, label and dialogue text resolved from war3map.wts;
    unset values are null."""
    return elements_ops.elements_list(_project(path), kind)


@_tool
def elements_edit(path: str, kind: Literal["region", "camera", "sound"], ops: list[dict]) -> dict:
    """All-or-nothing region/camera/sound changes. {"op": "upsert", "name", ...fields} creates (regions need
    left/bottom/right/top, cameras x/y, sounds path) or changes the named element; "new_name" renames it and updates
    GUI trigger references. {"op": "delete", "name"} refuses while triggers, region ambient sounds or waygates use it.
    Fields match elements_list; weather ids come from data_search kind=weather, sound labels from kind=sound."""
    return elements_ops.elements_edit(_project(path), _catalog("enUS", "Custom_V1", True), kind, ops)


@_tool
def placed_list(path: str, kind: Literal["unit", "item", "start_location", "doodad", "destructible"] | None = None,
                area: list[float] | None = None, owner: int | None = None, type_id: str | None = None,
                limit: int = 200, offset: int = 0) -> dict:
    """Placed objects of an open map: units, items and start locations (war3mapUnits.doo), doodads and destructibles
    (war3map.doo). Filters: kind, area [left, bottom, right, top], owner (player 0-23, 24 neutral hostile, 27 neutral
    passive), type_id. Each object has a ref ("unit:12") for placed_edit, world position, angle in degrees and its
    kind's fields (owner, life %, mana, hero stats, inventory, abilities, item drops, random settings, waygate region,
    script_name gg_unit_/gg_item_/gg_dest_). bounds gives the playable area and the whole map."""
    return placed_ops.placed_list(_project(path), _catalog("enUS", "Custom_V1", True), kind, area, owner, type_id,
                                  limit, offset)


@_tool
def placed_edit(path: str, ops: list[dict] | None = None, ops_file: str | None = None, verbose: bool = False) -> dict:
    """Place, change and remove units, items, start locations, doodads and destructibles, all-or-nothing.
    Ops: add (one object, or many through "columns"/"rows"), set, move, delete, scatter (uniform random), and the
    scenery generators forest, line, town, cluster and clear, which build a layout instead of a heap - seeded,
    deterministic and off water, cliffs and the boundary - and mirror, which copies objects onto the other side of an
    axis with their facing turned and, with owner_map, another player's colours. Refs are "<kind>:<editor id>", angles degrees, positions
    world units; created comes back as ref ranges (verbose=true lists every ref), and ops_file takes the ops array
    from a local JSON file. wc3_help("placed_edit") has every op, every field and the road recipe; layout_check
    reports how the result reads."""
    return placed_ops.placed_edit(_project(path), _catalog("enUS", "Custom_V1", True), _ops(ops, ops_file), verbose)


@_tool
def layout_check(path: str, area: list[float] | None = None, kinds: list[str] | None = None,
                 min_distance: float | None = None) -> dict:
    """Numbers that say whether placed scenery reads as placed: how many objects of which types stand in the area,
    their nearest-neighbour spacing (min, p10, median, mean and spread - the coefficient of variation, which is near 0
    for a grid stamp and 0.15-0.45 for hand-placed work), how many stand on water, on ground no unit can stand on or
    outside the playable area, which tiles they ended up on, and how much of the walkable map the start locations can
    still reach after the decoration went in. Pair it with terrain_render for the look; this catches what a top-down
    picture cannot show. kinds filters (doodad, destructible, unit, item), min_distance also counts the pairs closer
    than it."""
    return layout_ops.layout_check(_project(path), _catalog("enUS", "Custom_V1", True), area, kinds, min_distance)


@_tool
def terrain_get(path: str, area: list[float] | None = None,
                layers: list[Literal["height", "texture", "cliff_level", "water", "flags", "pathing"]] | None = None,
                step: int = 1) -> dict:
    """Terrain corners of an open map, one every 128 units, as grids of rows running south to north inside
    area [left, bottom, right, top] (default the whole map), every step-th corner. layers: height, texture,
    cliff_level, water, flags and pathing, which comes from the editor's last save or, after terrain_edit, is derived
    from the current tiles, cliffs, water and blight (pathing_source says which). A narrow area snaps to the nearest
    corner line (window.snapped). Also the tile palette and the map bounds; at most 65536 corners per call.
    wc3_help("terrain_get") explains each layer."""
    return terrain_ops.terrain_get(_project(path), area, layers, step, _catalog("enUS", "Custom_V1", True))


@_tool
def terrain_edit(path: str, ops: list[dict] | None = None, ops_file: str | None = None) -> dict:
    """Shape and paint terrain with all-or-nothing brushes, each {"op": <brush>, <area>, <settings>}; areas
    are a circle ("x"/"y"/"radius"), a "rect", a "path" with "width", or nothing at all for the whole map. Brushes:
    raise, lower, plateau, smooth, noise, paint, cliff, ramp, water, blight, boundary; the landscape brushes river,
    coast, ridge, erosion, terrace, blend and stamp, which shape ground the way the scenery ops shape objects; mirror,
    which copies a half or a quadrant onto the other side (terrain and placed objects both have it, so a symmetric map
    is built once); and heightmap, which reads a picture over an area. The result reports the tile
    palette and what the ops added to it, and warns when a batch paints an unbuildable or unwalkable tile widely.
    Only a World Editor save recomputes pathing, shadows and minimap icons from new terrain.
    wc3_help("terrain_edit") has every brush and its settings, wc3_help("terrain_landscape") the landscape ones."""
    return terrain_ops.terrain_edit(_project(path), _catalog("enUS", "Custom_V1", True), _ops(ops, ops_file))


@_tool
def terrain_render(path: str, scale: int | None = None, objects: bool = True, doodads: bool = True,
                   pathing: bool = False, write_preview: bool = False, heightmap: str | None = None,
                   area: list[float] | None = None) -> Image:
    """Top-down PNG of the map's terrain, north up, scale pixels per tile (default: fits 1024 px): tile colours,
    height shading, darkened cliffs, water, blight and boundary; objects draws regions (cyan), start locations
    (white), units (red) and items (yellow), and with doodads also doodads (magenta), trees (dark green) and other
    destructibles (orange) as small marks, enough to see coverage, gaps and clumps. pathing=true tints ground on
    unbuildable tiles red and on unwalkable tiles black, from the current tiles (no editor save needed).
    write_preview=true also writes this view into the map as war3mapPreview.tga, the picture the map list shows
    instead of the minimap (the minimap itself, war3mapMap.blp, is map_save's job).
    heightmap="height" (or "cliff" or "water") answers with a 16-bit grayscale picture of that layer over area
    instead of the map view, which terrain_edit's heightmap brush reads back: the result of a heightmap render also
    says which world units black and white stand for."""
    project = _project(path)
    if heightmap is not None:
        terrain, _raw = terrain_ops._load(project)
        log.info("heightmap %s", heightmap_ops.export_range(terrain, area, heightmap))
        return Image(data=heightmap_ops.export(terrain, area, scale, heightmap), format="png")
    if write_preview:
        project.write("war3mapPreview.tga", terrain_ops.preview(project, _catalog("enUS", "Custom_V1", True)))
    return Image(data=terrain_ops.terrain_render(project, _catalog("enUS", "Custom_V1", True), scale, objects,
                                                 objects and doodads, pathing), format="png")


@_tool
def script_build(path: str) -> dict:
    """Regenerate the editor-generated parts of war3map.j exactly as the World Editor writes them (variable globals,
    InitGlobals, custom script code, trigger functions, regions, cameras, sounds, placed units, items and
    destructables, item tables, random groups, map info); the rest of the script is kept. Lua maps get their whole
    war3map.lua rebuilt the way the editor transpiles it; the map header, custom text triggers and Custom Script
    actions are Lua there. map_save does this automatically when those sources changed."""
    project = _project(path)
    return script_ops.script_build(project, _catalog("enUS", script_ops.balance(project), True))


@_tool
def script_validate(path: str, lint: bool = False) -> dict:
    """Check the map script: pjass (JassHelper for vJASS) for war3map.j, a Lua 5.3 syntax check for war3map.lua.
    Errors carry line, message, the script section and the trigger they are in. lint=true adds the runtime traps a
    compiler cannot see (JASS only), each with its line, function and trigger: leaked locations, groups, forces, rects
    and boolexprs, event data read after a TriggerSleepAction, a trigger with an action but no event, a loop without
    exitwhen or over the operation limit, a handle used after it was destroyed, a local or parameter named after a
    JASS type, and game state changed inside a GetLocalPlayer() block (a multiplayer desync). They are heuristics, so
    each names what to check; a firing rule is usually a game run saved."""
    return script_ops.script_validate(_project(path), _catalog("enUS", "Custom_V1", True), lint=lint)


@_tool
def map_validate(path: str) -> dict:
    """Cross-file checks of an open map: script language against the script files, GUI trigger code against
    TriggerData and the map's variables, references to generated objects, TRIGSTR strings, object data, imports,
    placed objects without a loadable model, trigger function order, order strings, ability order clashes, command
    card clashes, inherited build lists, locked abilities, and ground a player cannot walk to. Errors break the map;
    warnings are defects that shipped maps also carry, each message saying what to check.
    wc3_help("map_validate") lists every check by name."""
    return script_ops.map_validate(_project(path), _catalog("enUS", "Custom_V1", True))


# ---- assets ----------------------------------------------------------------------------------------------------
def _storage_for_assets():
    return _catalog("enUS", None, True).storage


@_tool
def asset_info(source: dict) -> dict:
    """Facts about a texture (BLP1, DDS, TGA, PNG, JPEG: format, size, mip levels, compression, alpha) or a model (MDX,
    MDL: sequences with intervals, textures, geosets, bones, attachments, emitters, extent). source is {"file": path},
    {"map": open map path, "name": file in the map} or {"game": game data path}."""
    return assets_ops.asset_info(source, _project, _storage_for_assets())


@_tool
def asset_convert(source: dict, dest: dict,
                  format: Literal["blp", "dds", "tga", "png", "jpg", "mdx", "mdl"] | None = None,
                  compression: str | None = None, quality: int = 90, mipmaps: bool = True) -> dict:
    """Convert a texture, or a model between MDX and MDL (byte-exact both ways). dest is {"file": path} or {"map": open
    map path, "name": import path} (imported through imports_edit). format defaults to the destination extension;
    compression: blp jpeg | palette (JPEG like the game's icons by default), dds dxt1 | dxt5 | uncompressed, tga rle."""
    return assets_ops.asset_convert(source, dest, _project, _storage_for_assets(), format, compression, quality, mipmaps)


@_tool
def asset_edit(source: dict, dest: dict, ops: list[dict],
               format: Literal["blp", "dds", "tga", "png", "jpg", "mdx", "mdl"] | None = None,
               compression: str | None = None, quality: int = 90, mipmaps: bool = True) -> dict:
    """Edit a texture or a model and write the result (source and dest as in asset_convert). Texture ops:
    resize, crop, grayscale, brightness, tint, overlay and icon (the game's 64x64 BTN, DISBTN, PASBTN and DISPASBTN
    styles). Model ops: retexture, scale, rename_sequence, remove_sequence, team_color and add_attachment.
    wc3_help("asset_edit") has every op with its arguments."""
    return assets_ops.asset_edit(source, dest, ops, _project, _storage_for_assets(), format, compression, quality,
                                 mipmaps)


@_tool
def asset_preview(source: dict, size: int = 256) -> Image:
    """PNG preview of a texture (fits size pixels, checkerboard behind transparency) or of a model (its level-of-detail
    0 geosets drawn from the front left as they stand, textured when the textures are found)."""
    return Image(data=assets_ops.asset_preview(source, _project, _storage_for_assets(), size), format="png")


# ---- AI Editor -------------------------------------------------------------------------------------------------
def _ai_source(path: str):
    """An open map (its war3map.wai) or a .wai file."""
    project = _projects.get(_key(path))
    if project is not None:
        return project
    if Path(path).suffix.lower() != ".wai":
        raise ToolError("bad_value", f"{path} is neither an open map nor a .wai file", hint="map_open the map first",
                        path="path")
    return Path(path).resolve()


@_tool
def ai_get(path: str) -> dict:
    """AI Editor data of a .wai file or an open map (war3map.wai): name, race, options, workers, named conditions
    (GUI condition JSON as in triggers_edit), heroes with skills per hero order, hero order percentages, build /
    harvest / target priorities, attack groups, attack waves, test game settings."""
    return ai_ops.ai_get(_ai_source(path), _catalog("enUS", "Custom_V1", True))


@_tool
def ai_edit(path: str, ops: list[dict]) -> dict:
    """All-or-nothing AI Editor changes on the ai_get document ({"op": "set" | "append" | "remove", "path", "value"}).
    A missing .wai file is created from a new-AI starting point; an existing one is backed up and replaced atomically;
    for an open map war3map.wai changes in the working copy. Conditions are referenced by name, or
    {"custom": <condition>}; towns are "any", "main", "expansion<n>", "mine<n>"; group units use hero1-hero3 for
    the heroes and "all" quantities."""
    return ai_ops.ai_edit(_ai_source(path), _catalog("enUS", "Custom_V1", True), ops)


@_tool
def ai_export(path: str, dest: str | None = None, map_path: str | None = None, player: int | None = None,
              import_path: str | None = None) -> dict:
    """Export the AI script (.ai) exactly as the AI Editor's File > Export Script does, checked with pjass. Writes
    dest (default: next to the .wai), or with map_path (an open map) imports it as war3mapImported\\<name>.ai and,
    with player (0 = Player 1), adds a map-initialization trigger that starts it (StartMeleeAI for melee AI, else
    StartCampaignAI)."""
    project = _project(map_path) if map_path else None
    return ai_ops.ai_export(_ai_source(path), _catalog("enUS", "Custom_V1", True), dest, project, player, import_path)


# ---- World Editor ----------------------------------------------------------------------------------------------
@_tool
def editor_launch(map_path: str | None = None) -> dict:
    """Start the World Editor on the user's desktop, optionally opening a map file. Refuses when an editor is already
    running (use editor_map open to switch maps)."""
    return desktop_editor.EDITOR.launch(map_path)


@_tool
def editor_status() -> dict:
    """Whether the World Editor runs, the map it shows, unsaved changes, busy state, open dialogs and module windows.
    Check this before touching a map the user may be editing."""
    return desktop_editor.EDITOR.status()


@_tool
def editor_map(action: Literal["open", "save", "close", "reload", "compile", "quit", "save_campaign"],
               map_path: str | None = None, discard: bool = False) -> dict:
    """Map actions in the World Editor. open (map_path; shows that map, or a .w3n campaign in the Campaign Editor, and
    reports previous_instance: reused when the running editor already showed it, relaunched when it was quit and started
    again, none when no editor ran; an editor showing another map or none is always relaunched, because starting it with
    the map is the dependable way to open one), save / compile (the editor regenerates and checks the script; script
    errors come back per trigger and the editor disables failing triggers), save_campaign (the Campaign Editor's
    campaign), close, reload (reopen from disk after map_save), quit. Anything that would drop unsaved editor changes
    refuses with unsaved_changes unless discard=true: ask the user first."""
    editor = desktop_editor.EDITOR
    if action == "open":
        if not map_path:
            raise ToolError("bad_value", "open needs map_path")
        return editor.open(map_path, discard=discard)
    if action in ("save", "compile"):
        saved = editor.save()
        shown = _projects.get(_key(saved.get("map") or ""))
        if saved.get("saved") and shown is not None:   # the editor recomputed pathing, shadows and the minimap
            shown.note("terrain_edited", False)
        return saved
    if action == "save_campaign":
        return editor.save_campaign()
    if action == "close":
        return editor.close(discard=discard)
    if action == "reload":
        return editor.reload(discard=discard)
    return editor.quit(discard=discard)


@_tool
def editor_menu(path: str | None = None, window: str | None = None) -> dict:
    """Without path: the menu tree of the main window or of a module window (window="Trigger Editor"). With path:
    invoke that command, e.g. "Module/Object Editor" or "Scenario/Map Options...". Labels omit & and shortcuts."""
    if path is None:
        return {"window": window or "main", "menus": desktop_editor.EDITOR.menu(window)}
    return {"invoked": path, "status": desktop_editor.EDITOR.invoke(path, window)}


@_tool
def editor_screenshot(target: str = "main", region: list[int] | None = None) -> Image:
    """Screenshot of the editor main window, a module window or a dialog (by title); region [x, y, width, height]
    relative to that window. The window is brought to the front briefly."""
    return Image(data=desktop_editor.EDITOR.screenshot(target, region), format="png")


@_tool
def editor_dialogs(include_palettes: bool = False) -> dict:
    """Open editor dialogs with their visible controls (class, id, text, enabled, checked, list items)."""
    return {"dialogs": desktop_editor.EDITOR.dialogs(include_palettes)}


@_tool
def editor_dialog_act(dialog: str, actions: list[dict]) -> dict:
    """Operate a dialog by title. actions: [{"control": 14, "set_text": "My Map"}, {"control": "OK", "click": true},
    {"control": "Hide minimap", "check": true}, {"control": 17, "select": "Warcraft III Scenario"}]; controls by id
    or text. Returns the dialog's controls, or closed=true."""
    return desktop_editor.EDITOR.dialog_act(dialog, actions)


@_tool
def editor_input(actions: list[dict], window: str = "main") -> dict:
    """Real mouse and keyboard input into an editor window (brought to the front, focus restored afterwards); points
    are client coordinates. actions: {"click": [x, y], "button"?, "double"?}, {"drag": [[x1, y1], [x2, y2]]},
    {"keys": "ctrl+z"}, {"text": "..."}, {"wait": seconds}. Prefer editor_menu and editor_dialog_act when possible."""
    return desktop_editor.EDITOR.input(window, actions)


@_tool
def editor_log(lines: int = 200) -> dict:
    """The World Editor log: its tail, the messages the editor showed in its viewport (missing_files it could not load,
    other messages, a count of known-benign shipped-data lines) and the newest crash report folders. The editor writes
    this file only when it quits, so while it runs the log is its previous session (note says so); map_validate
    reports placed objects without a model without the editor."""
    return desktop_editor.EDITOR.log(lines)


# ---- game ------------------------------------------------------------------------------------------------------
@_tool
def game_test(path: str, timeout: float = 240, results: list[str] | None = None, close: bool = True,
              screenshot: bool = False, probe: bool = False, probe_seconds: float = 10,
              probe_script: str | None = None, probe_script_file: str | None = None,
              probe_functions: str | None = None, wait: bool = True, screenshots: int = 0,
              screenshot_every: float = 3.0) -> dict:
    """Run a map in Warcraft III (windowed; the window needs to be in front while loading) and collect what it
    reports. The map writes result files with PreloadGenEnd and the run ends as soon as every file listed in results
    exists. probe=true runs a throwaway copy that reports the state at probe_seconds; probe_script, probe_functions
    and the helpers ProbeReport, ProbeExpect, ProbeCountEvent and ProbeCamera make it a real test. wait=false runs it
    in the background (game_status reports it and its result); screenshots=N with screenshot_every saves pictures
    while the map runs. A Battle.net login screen ends the run with login_required and leaves the game open: the same
    call again continues in that game. wc3_help("game_test") has the probe helpers and the pitfalls."""
    target, extra = path, {}
    if probe_script is not None and probe_script_file is not None:
        raise ToolError("bad_value", "give probe_script or probe_script_file, not both")
    if probe_script_file is not None:
        probe_script = triggers_ops.read_text_file(probe_script_file, "probe_script_file")
    probe = probe or probe_script is not None or probe_functions is not None
    if probe:
        catalog = _catalog("enUS", None, True)
        opened = _projects.get(_key(path))
        folder = config.home() / "probe"
        for old in folder.glob("*"):   # earlier runs; a game still open keeps its copy (the rmtree skips it)
            shutil.rmtree(old, ignore_errors=True)
        run = folder / str(time.time_ns()) / Path(path).name   # a new folder per run: never one a game still holds
        target = str(probe_ops.build(path, run, catalog, opened, probe_seconds, probe_script, probe_functions))
        results = list(results or []) + [probe_ops.REPORT]
        extra["probe_map"] = target
    result = desktop_game.GAME.test(target, timeout=timeout, results=results, close=close, screenshot=screenshot,
                                    wait=wait, meta={"probe": probe, "extra": extra}, shots=screenshots,
                                    shot_every=screenshot_every)
    return {**(_finish_test(result, probe) if wait else result), **extra}


def _finish_test(result: dict, probe: bool) -> dict:
    """The parts of a run's result that need the server: the screenshot files and the probe report."""
    series = result.get("screenshots")
    if series and not all(isinstance(shot, str) for shot in series):
        folder = config.home() / "screenshots"
        folder.mkdir(parents=True, exist_ok=True)
        result["screenshots"] = []
        for i, image in enumerate(series):
            shot = folder / f"game-{result['pid']}-{i}.png"
            shot.write_bytes(image)
            result["screenshots"].append(str(shot))
    if result.get("screenshot"):
        shot = config.home() / "screenshots" / f"game-{result['pid']}.png"
        shot.parent.mkdir(parents=True, exist_ok=True)
        shot.write_bytes(result.pop("screenshot"))
        result["screenshot"] = str(shot)
    elif "screenshot" in result:
        result["screenshot"] = None
    if probe:
        lines = result["results"].pop(probe_ops.REPORT, None)
        result["probe"] = probe_ops.parse(lines) if lines is not None else None
        if lines is None and not result.get("login_required"):
            result["hint"] = ("the probed copy never reported: the game did not reach the map, it ended before "
                              f"probe_seconds, or {desktop_game.PAUSE_NOTE}")
    return result


@_tool
def game_status() -> dict:
    """Game processes (and which this server launched), their windows and the useful War3Log.txt lines. A game_test
    run started with wait=false is reported under run: while it goes, how long it has taken and which result files
    it has; when it ends, its whole result (probe reports included) under run.result."""
    job = desktop_game.GAME.run
    if job is not None and job["result"] is not None and not job.get("finished"):
        job["result"] = _finish_test(job["result"], job["meta"].get("probe", False))
        job["result"].update(job["meta"].get("extra") or {})
        job["finished"] = True
    return desktop_game.GAME.status()


@_tool
def game_close() -> dict:
    """Close game processes launched by game_test (never other game sessions)."""
    return desktop_game.GAME.close()


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
