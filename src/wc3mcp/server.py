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
from .desktop import editor as desktop_editor
from .desktop import game as desktop_game
from .errors import ToolError
from .gamedata.catalog import Catalog
from .ops import ai as ai_ops
from .ops import assets as assets_ops
from .ops import campaign as campaign_ops
from .ops import elements as elements_ops
from .ops import imports as imports_ops
from .ops import info as info_ops
from .ops import newmap as newmap_ops
from .ops import objdata as objdata_ops
from .ops import placed as placed_ops
from .ops import probe as probe_ops
from .ops import script as script_ops
from .ops import terrain as terrain_ops
from .ops import triggers as triggers_ops
from .project.workspace import MapProject, project_id

log = logging.getLogger("wc3mcp")
mcp = FastMCP("wc3", instructions=(
    "Warcraft III map making. map_open copies a map into a private working copy; change files there; map_save "
    "backs up the original and replaces it atomically. The game install is read-only. Look up units, abilities, "
    "items, buffs, upgrades, doodads, destructibles, terrain, sounds and assets with data_search / data_get."))

Kind = Literal["unit", "item", "ability", "buff", "upgrade", "destructible", "doodad", "tile", "cliff", "water",
               "weather", "sound", "model", "icon", "file", "trigger_function", "trigger_type", "trigger_preset"]
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
    """All-or-nothing campaign changes. ops on the campaign_get document: {"op": "set", "path": "name", "value":
    "My Campaign"}, {"op": "set", "path": "minimap", "value": {"preset": "Human"} | {"map": "Ch1.w3x"} |
    {"file": "war3campImported/map.tga"} | null}, {"op": "set", "path": "loading_screen.background", "value":
    {"preset": "Orc" or index} | {"file": "war3campImported/intro.webm"} | null} (ambient_sound likewise),
    loading_screen.cursor / background_version / fog ({"style": "linear", "z_start", "z_end", "density", "color":
    {r, g, b, a}, ...} or null), {"op": "append", "path": "buttons", "value": {"chapter", "title", "map", "visible",
    "cinematic"}}, {"op": "set"/"remove", "path": "buttons[0]..."}; maps: {"op": "add_map", "source":
    "C:/maps/Ch1.w3x", "name"?}, {"op": "replace_map", "name", "source"}, {"op": "remove_map", "name"},
    {"op": "extract_map", "name", "dest"} (edit it with map_open, put it back with replace_map)."""
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
    """Save the working copy. By default backs up the original and replaces it atomically. dest/format write a
    copy elsewhere (mpq archive or map folder). Refuses if the original changed on disk since opening (source_changed,
    e.g. after a World Editor save) unless merge_external=true, which first takes every file this working copy has not
    changed from the map on disk (pathing, shadows and minimap the editor recomputed) and keeps the working copy's own
    changes, or force=true, which overwrites the map with the working copy. rebuild_script: auto regenerates war3map.j / war3map.lua when triggers, regions, cameras, sounds,
    placed objects or map info changed (maps with trigger data), always regenerates whenever possible, never leaves
    the script alone. The minimap war3mapMap.blp is added when missing and redrawn after terrain edits unless the map
    imports its own. validate runs map_validate first, compiles a regenerated or edited map
    script (pjass / Lua check, reported in validation.script) and refuses to save on errors of either. The World Editor keeps the map
    file open, so when it shows the same map the safe round trip is: edits here -> editor_map close -> map_save ->
    editor_map open -> editor_map save (which recomputes pathing, shadows and the minimap)."""
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
    """Search base game data by id, name or editor suffix (object, terrain and sound kinds) or by path substring or
    glob (model, icon, file). model, icon and file results give one entry per file: ref is the path as object data
    and scripts write it (backslashes, icons as .blp, models as .mdl), layers the storage layers holding it (base,
    _HD, _DE, ...) and id a storage path for data_file and the asset tools. trigger_function / trigger_type /
    trigger_preset search GUI trigger functions, variable types and preset values. tileset (a letter, e.g. "L", or a name, e.g. "Lordaeron Summer") lists only what that
    tileset offers for kind=tile, cliff, doodad and destructible; tile and cliff results name their tileset. Doodad
    and destructible results carry model_ok: false when the installed game cannot load the id's model in HD or in
    classic graphics, which the World Editor uses (it would place but render nothing, or show a checkerboard cube in
    the editor); variations_ok then lists the variations that do load. balance selects the gameplay data set: Custom_V1 (current), Custom_V0, Melee_V0, or null for
    the base files."""
    catalog = _catalog(locale, balance, hd)
    results = catalog.search(kind, query, limit=min(limit, 500), offset=offset, tileset=tileset)
    return {"kind": kind, "query": query, "offset": offset, "count": len(results), "results": results,
            **({"tilesets": catalog.tilesets()} if kind in ("tile", "cliff") and not results else {})}


@_tool
def data_get(kind: Kind, id: str, fields: list[str] | None = None, locale: str = "enUS",
             balance: str | None = "Custom_V1", hd: bool = True) -> dict:
    """Base data for one object with editor field raw codes, names, types and values (per level for leveled
    fields). fields filters by raw code (e.g. uhpm), field name, or display-name substring. Doodads, destructibles and
    units also list their model files and the ones the installed game cannot load in HD or classic graphics
    (model.missing)."""
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
    has raw code, name, type, value (or per-level values) and whether the map modifies it. levels and the per-level
    lists follow the map's own level count (alev, glvl); values the map stores for levels beyond it are listed under
    unused_levels. fields filters by raw code, field name or display-name substring."""
    return objdata_ops.objdata_get(_project(path), _catalog("enUS", balance, True), kind, id, fields)


@_tool
def objdata_edit(path: str, kind: ObjectKind, ops: list[dict] | None = None, balance: str | None = "Custom_V1",
                 ops_file: str | None = None) -> dict:
    """Create and change objects with an all-or-nothing batch: {"op": "create", "base": "hfoo", "set": {"Name":
    "Guard", "HP": 500}} (id optional, allocated like the editor), {"op": "set", "id": "h000", "set": {"Hbz1":
    {"1": 7, "2": 9}}} (per-level fields take level keys; stock ids such as hgtw work too), {"op": "reset", "id":
    "h000", "fields": ["uhpm"]}, {"op": "delete", "id": "h000"}. Fields accept raw codes, field names or display
    names. ops_file: a local JSON file holding the ops array instead of ops."""
    return objdata_ops.objdata_edit(_project(path), _catalog("enUS", balance, True), kind, _ops(ops, ops_file))


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
    """All-or-nothing Trigger Editor changes. ops:
    {"op": "category", "name", "parent"?, "new_name"?};
    {"op": "variable", "name", "type", "array_size"?, "initial"?, "category"?, "new_name"?};
    {"op": "trigger", "name", "category"?, "description"?, "enabled"?, "initially_on"?, "run_on_init"?,
     "events"/"conditions"/"actions": [{"fn": "KillUnit", "args": [{"call": "GetTriggerUnit"}]}, ...] or
     "script": "<JASS or Lua>" or "script_file": "C:/local/trigger.j", "new_name"?};
    {"op": "delete", "what": "trigger"|"category"|"variable", "name"}; {"op": "header", "script"?, "script_file"?,
    "comment"?}; {"op": "script_replace", "name" (or "header": true), "old", "new"} replaces one exact piece of a
    script trigger's text (or the map header) without resending the script; old must occur exactly once.
    An argument is a literal, {"preset": name}, {"var": name, "index"?} or {"call": name, "args": [...]}; block
    functions take "if"/"then"/"else" (IfThenElseMultiple), "conditions" (And/OrMultiple) or "actions" (loops).
    GUI code is checked against TriggerData; data_search kind=trigger_function finds functions. run_on_init is for
    script triggers; a GUI trigger runs at map start through the event {"fn": "MapInitializationEvent"}.
    A "script" trigger gets the editor's InitTrig_<script name> wrapper added when it does not define one, so the
    actions alone are enough (the result says what was added). validate=true regenerates the map script and checks it
    right away (pjass, or the Lua syntax check) instead of waiting for map_save; each error also carries script_line,
    its line inside the script that was sent. ops_file: a local JSON file holding the ops array instead of ops."""
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
    """All-or-nothing placed object changes. {"op": "add", "kind", "type", "x", "y", ...fields} places an object with
    editor defaults (facing 270, z on the terrain, units owned by player 0, items neutral passive; start locations need
    owner, no type). Many adds at once: {"op": "add", "kind": "destructible", <fields shared by all>, "columns":
    ["type", "x", "y", "variation", "angle"], "rows": [["LTlt", -1833, -3653, 2, 113], ...]}. {"op": "scatter", "kind",
    "types": {"LTlt": 3, "LTlf": 1} (weights) or [ids], "count", area ("rect": [left, bottom, right, top], or "x"/"y"/
    "radius"; default the playable area), "exclude": [{"x", "y", "radius"} | {"rect": [...]}], "min_distance"?,
    "seed"?, "where": "land" (default, no water or boundary) | "water" | "any", ...shared fields} places random
    objects; doodads and destructibles get a random installed variation and their fixed or a random facing.
    {"op": "set", "ref", ...fields} changes fields (type too); {"op": "move", "ref", "x", "y"} (moving a start
    location also moves the player's start in war3map.w3i, reported in synced); {"op": "delete", "ref"} refuses while
    triggers use its gg_ name. Fields match placed_list: angle, scale (number or [x, y, z]), variation, skin, owner,
    life (unit %, null default; destructible %), mana, gold, acquisition ("normal", "camp" or a range), hero {level,
    strength, agility, intelligence}, inventory [{slot 0-5, item}], abilities [{id, autocast, level}], drops {table,
    sets: [[{item, chance}]]}, random (uDNR/bDNR/iDNR: {level, item_class}, {group, position} or {units: [{type,
    chance}]}), color, waygate (region name), doodad z and flags. created lists the new refs as ranges in op order
    ("doodad:422..909"; verbose=true lists every ref). ops_file: a local JSON file holding the ops array instead of
    ops. A doodad or destructible whose model the installed game cannot load, or whose scale is outside its type's
    minimum and maximum (the World Editor clamps it on save), is placed with a warning."""
    return placed_ops.placed_edit(_project(path), _catalog("enUS", "Custom_V1", True), _ops(ops, ops_file), verbose)


@_tool
def terrain_get(path: str, area: list[float] | None = None,
                layers: list[Literal["height", "texture", "cliff_level", "water", "flags", "pathing"]] | None = None,
                step: int = 1) -> dict:
    """Terrain corners of an open map (one every 128 units) inside area [left, bottom, right, top] (default: the
    whole map), every step-th corner, as grids of rows running south to north. height is the ground height without
    cliffs (ground z = height + (cliff_level - 2) * 128), texture the tile id, water the water surface z or null,
    flags letters r ramp, b blight, w water, x boundary, pathing letters w unwalkable, f unflyable, b unbuildable,
    B blight from the editor's last save. Also the tile lists and map bounds. At most 65536 corners per call."""
    return terrain_ops.terrain_get(_project(path), area, layers, step)


@_tool
def terrain_edit(path: str, ops: list[dict] | None = None, ops_file: str | None = None) -> dict:
    """All-or-nothing terrain brushes. Every op is {"op": <brush>, <area>, <settings>}, for example {"op": "paint",
    "tile": "Lgrs", "x": 0, "y": 0, "radius": 384}. Areas (world units): "x"/"y"/"radius" a circle, "rect": [left,
    bottom, right, top], "path": [[x, y], ...] with "width" a stroke along a line (roads), or no area at all for the
    whole map. Brushes and their settings: raise / lower {"amount", "falloff": smooth|linear|flat}, plateau
    {"height"} (default: the centre corner's), smooth {"strength" 0..1}, noise {"amount", "seed", "falloff"}, paint
    {"tile"} (data_search kind=tile, tileset=<letter>), cliff {"level" 0..15, "cliff": cliff tile id}, water
    {"level": surface z, or null to remove}, ramp / blight / boundary {"value": true|false}. The result reports the
    map's tile palette and what the ops added to it (a map holds at most 16 ground tiles). Pathing, shadows and the
    minimap are recomputed by the World Editor on its next save. ops_file: a local JSON file holding the ops array
    instead of ops."""
    return terrain_ops.terrain_edit(_project(path), _catalog("enUS", "Custom_V1", True), _ops(ops, ops_file))


@_tool
def terrain_render(path: str, scale: int | None = None, objects: bool = True, doodads: bool = True) -> Image:
    """Top-down PNG of the map's terrain, north up, scale pixels per tile (default: fits 1024 px): tile colours,
    height shading, darkened cliffs, water, blight and boundary; objects draws regions (cyan), start locations
    (white), units (red) and items (yellow), and with doodads also doodads (magenta), trees (dark green) and other
    destructibles (orange) as small marks, enough to see coverage, gaps and clumps."""
    return Image(data=terrain_ops.terrain_render(_project(path), _catalog("enUS", "Custom_V1", True), scale, objects,
                                                 objects and doodads), format="png")


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
def script_validate(path: str) -> dict:
    """Check the map script: pjass (JassHelper for vJASS) for war3map.j, a Lua 5.3 syntax check for war3map.lua.
    Errors carry line, message, the script section and the trigger they are in."""
    return script_ops.script_validate(_project(path), _catalog("enUS", "Custom_V1", True))


@_tool
def map_validate(path: str) -> dict:
    """Cross-file checks of an open map: script language vs script files, GUI trigger code against TriggerData and
    variables, trigger names, references to generated objects, TRIGSTR strings, object data base ids and fields,
    imports. Errors break the map; warnings are defects that shipped maps also carry, plus a reminder while terrain
    edits are newer than the pathing, shadow and minimap files only the World Editor recomputes."""
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
    """Edit a texture or a model and write the result (source and dest as in asset_convert). ops apply in order.
    Texture ops: {"op": "resize", "width", "height"}, {"op": "crop", "left", "top", "right", "bottom"}, {"op":
    "grayscale"}, {"op": "brightness", "factor"}, {"op": "tint", "color": [r, g, b], "strength"}, {"op": "overlay",
    "source", "x", "y", "width"?, "height"?, "opacity"?}, {"op": "icon", "kind": "BTN" | "DISBTN" | "PASBTN" |
    "DISPASBTN"} (64x64 command button styles of the game's icons). Model ops: {"op": "retexture", "texture": index or
    current path, "path": new path, "replaceable_id"?}, {"op": "scale", "factor"} (geometry, pivots, extents,
    translations, emitters, cameras, collision), {"op": "rename_sequence", "sequence": index or name, "name"}, {"op":
    "remove_sequence", "sequence"}, {"op": "team_color", "material": index} (adds the team colour texture: a layer
    under classic materials, texture slot 4 of Reforged ones), {"op": "add_attachment", "name", "parent"?: node name or
    object id, "position"?: [x, y, z], "path"?}."""
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
    """Map actions in the World Editor. open (map_path; shows that map, or a .w3n campaign in the Campaign Editor,
    and reports previous_instance: reused when the running editor already showed it, relaunched when it was quit and
    started again, none when no editor ran), save / compile (the editor regenerates and checks the script; script errors come back per
    trigger and the editor disables failing triggers), save_campaign (the Campaign Editor's campaign), close, reload
    (reopen from disk after map_save), quit. Anything that would drop unsaved editor changes
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
              probe_script: str | None = None, probe_script_file: str | None = None) -> dict:
    """Run a map in Warcraft III (windowed; the window needs to be in front while loading). The map script reports
    results with PreloadGenClear/PreloadGenStart/Preload("text")/PreloadGenEnd("folder\\\\file.txt"); list those
    files in results (relative to Documents\\Warcraft III\\CustomMapData) and the run ends as soon as all exist.
    Strings come back unescaped (single backslashes). The game keeps about 259 characters of one Preload string:
    longer lines come back cut off and are listed in truncated. A loading screen that waits for a key (maps with
    loading_screen title, subtitle or text) gets a space key press (loading_screen_keys). A Battle.net login screen
    ends the run after about 30 s with login_required: the game stays open for the user to log in (game_close it
    before running again). An open dialog
    (DialogDisplay) pauses a single-player game until someone clicks it, so timers and probe_seconds wait for it:
    report before the dialog opens (e.g. probe_seconds 0.3). To capture the hero learn menu, the map's test
    code runs SelectUnit(h, true), waits 0.5 s (TriggerSleepAction), calls ForceUIKey("O") and reports afterwards;
    a user click in the game window changes what screenshot=true captures.
    probe=true instead runs a throwaway copy of the map (the open working copy when the map is open) with one added
    trigger that reports, probe_seconds into the game, the units, heroes, gold and lumber of every playing slot and the
    BJDebugMsg text: use it to check that a map loads and runs without touching its own triggers. probe_script (or
    probe_script_file, a local file; either implies probe=true) adds test code in the map's language (JASS or Lua
    statements, JASS locals first) that runs at that moment and may call the map's own functions and read its udg_
    globals; ProbeReport(text) writes any length of text, returned in probe.reports. screenshot=true saves a PNG of
    the game window (screenshot_of says what was captured, or why nothing was). Returns the Preload strings per file,
    the useful War3Log.txt lines (known-benign shipped-data lines are counted separately in benign_log) and any new
    crash."""
    target, extra = path, {}
    if probe_script is not None and probe_script_file is not None:
        raise ToolError("bad_value", "give probe_script or probe_script_file, not both")
    if probe_script_file is not None:
        probe_script = triggers_ops.read_text_file(probe_script_file, "probe_script_file")
    probe = probe or probe_script is not None
    if probe:
        catalog = _catalog("enUS", None, True)
        opened = _projects.get(_key(path))
        folder = config.home() / "probe"
        shutil.rmtree(folder, ignore_errors=True)
        target = str(probe_ops.build(path, folder / Path(path).name, catalog, opened, probe_seconds, probe_script))
        results = list(results or []) + [probe_ops.REPORT]
        extra["probe_map"] = target
    result = desktop_game.GAME.test(target, timeout=timeout, results=results, close=close, screenshot=screenshot)
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
    return {**result, **extra}


@_tool
def game_status() -> dict:
    """Game processes (and which this server launched), their windows and the useful War3Log.txt lines."""
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
