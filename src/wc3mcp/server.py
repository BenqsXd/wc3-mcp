"""wc3-mcp MCP server. Phase 1: map working copies and game data."""
import base64
import functools
import json
import logging
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
from .ops import elements as elements_ops
from .ops import imports as imports_ops
from .ops import info as info_ops
from .ops import newmap as newmap_ops
from .ops import objdata as objdata_ops
from .ops import placed as placed_ops
from .ops import script as script_ops
from .ops import terrain as terrain_ops
from .ops import triggers as triggers_ops
from .project.workspace import MapProject

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
def map_new(path: str, width: int = 64, height: int = 64, tileset: str = "L", name: str = "Just another Warcraft III map",
            author: str = "Unknown", players: int = 2, script_language: Literal["jass", "lua"] = "jass",
            format: Literal["mpq", "folder"] = "mpq") -> dict:
    """Create a new map at path (it must not exist) and open it: width/height in tiles (32-480, steps of 32, the
    playable area is 12 tiles narrower and shorter), tileset letter (data_search kind=tile ids start with it),
    players 1-24 with start locations, one force, a flat terrain of the tileset's first tile, the default Melee
    Initialization trigger and a generated war3map.j, or war3map.lua for script_language=lua."""
    project = newmap_ops.new_map(path, _catalog("enUS", "Custom_V1", True), width, height, tileset, name, author, players,
                                 script_language, format)
    _projects[_key(path)] = project
    return project.status()


@_tool
def map_close(path: str, discard: bool = False) -> dict:
    """Close an open map. Refuses while there are unsaved edits unless discard=true."""
    result = _project(path).close(discard)
    del _projects[_key(path)]
    return result


SCRIPT_SOURCES = {"war3map.wtg", "war3map.wct", "war3map.w3r", "war3map.w3c", "war3map.w3s", "war3map.doo",
                  "war3mapunits.doo", "war3map.w3i"}


@_tool
def map_save(path: str, dest: str | None = None, format: Literal["mpq", "folder"] | None = None,
             force: bool = False, rebuild_script: Literal["auto", "always", "never"] = "auto",
             validate: bool = True) -> dict:
    """Save the working copy. By default backs up the original and replaces it atomically. dest/format write a
    copy elsewhere (mpq archive or map folder). Refuses if the original changed on disk since opening unless
    force=true. rebuild_script: auto regenerates war3map.j / war3map.lua when triggers, regions, cameras, sounds,
    placed objects or map info changed (maps with trigger data), always regenerates whenever possible, never leaves
    the script alone. validate runs map_validate first and refuses to save on errors."""
    project = _project(path)
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
    validation = script_ops.map_validate(project, catalog) if validate else None
    if validation and validation["errors"]:
        first = validation["errors"][0]
        raise ToolError("validation_failed", f"{len(validation['errors'])} map validation error(s); first: "
                        f"{first['file']}: {first['message']}", hint="fix them, or save with validate=false",
                        errors=validation["errors"][:20])
    result = project.save(dest=dest, format=format, force=force)
    result["warnings"] = warnings
    if script is not None:
        result["script"] = script
    if validation is not None:
        result["validation"] = {"errors": [], "warning_count": len(validation["warnings"]),
                                "warnings": validation["warnings"][:20]}
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
def placed_edit(path: str, ops: list[dict]) -> dict:
    """All-or-nothing placed object changes. {"op": "add", "kind", "type", "x", "y", ...fields} places an object with
    editor defaults (facing 270, z on the terrain, units owned by player 0, items neutral passive; start locations need
    owner, no type); {"op": "set", "ref", ...fields} changes fields (type too); {"op": "move", "ref", "x", "y"};
    {"op": "delete", "ref"} refuses while triggers use its gg_ name. Fields match placed_list: angle, scale (number or
    [x, y, z]), variation, skin, owner, life (unit %, null default; destructible %), mana, gold, acquisition
    ("normal", "camp" or a range), hero {level, strength, agility, intelligence}, inventory [{slot 0-5, item}],
    abilities [{id, autocast, level}], drops {table, sets: [[{item, chance}]]}, random (uDNR/bDNR/iDNR: {level,
    item_class}, {group, position} or {units: [{type, chance}]}), color, waygate (region name), doodad z and flags."""
    return placed_ops.placed_edit(_project(path), _catalog("enUS", "Custom_V1", True), ops)


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
def terrain_edit(path: str, ops: list[dict]) -> dict:
    """All-or-nothing terrain brushes on circles {"x", "y", "radius"} (world units): raise / lower {"amount",
    "falloff": smooth|linear|flat}, plateau {"height"} (default: the centre corner's), smooth {"strength" 0..1},
    noise {"amount", "seed", "falloff"}, paint {"tile"} (data_search kind=tile; a map holds at most 16 tiles),
    cliff {"level" 0..15, "cliff" tile id}, water {"level": surface z or null to remove}, ramp / blight / boundary
    {"value": true|false}. Pathing, shadows and the minimap are recomputed by the World Editor on its next save."""
    return terrain_ops.terrain_edit(_project(path), _catalog("enUS", "Custom_V1", True), ops)


@_tool
def terrain_render(path: str, scale: int | None = None, objects: bool = True) -> Image:
    """Top-down PNG of the map's terrain, north up, scale pixels per tile (default: fits 1024 px): tile colours,
    height shading, darkened cliffs, water, blight and boundary; objects draws regions (cyan), start locations
    (white), units (red) and items (yellow)."""
    return Image(data=terrain_ops.terrain_render(_project(path), _catalog("enUS", "Custom_V1", True), scale, objects),
                 format="png")


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
    imports. Errors break the map; warnings are defects that shipped maps also carry."""
    return script_ops.map_validate(_project(path), _catalog("enUS", "Custom_V1", True))


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
def editor_map(action: Literal["open", "save", "close", "reload", "compile", "quit"], map_path: str | None = None,
               discard: bool = False) -> dict:
    """Map actions in the World Editor. open (map_path; relaunches the editor on that map), save / compile (the editor
    regenerates and checks the script; script errors come back per trigger and the editor disables failing
    triggers), close, reload (reopen from disk after map_save), quit. Anything that would drop unsaved editor changes
    refuses with unsaved_changes unless discard=true: ask the user first."""
    editor = desktop_editor.EDITOR
    if action == "open":
        if not map_path:
            raise ToolError("bad_value", "open needs map_path")
        return editor.open(map_path, discard=discard)
    if action in ("save", "compile"):
        return editor.save()
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
    """The World Editor log tail and the newest crash report folders."""
    return desktop_editor.EDITOR.log(lines)


# ---- game ------------------------------------------------------------------------------------------------------
@_tool
def game_test(path: str, timeout: float = 240, results: list[str] | None = None, close: bool = True,
              screenshot: bool = False) -> dict:
    """Run a map in Warcraft III (windowed; the window needs to be in front while loading). The map script reports
    results with PreloadGenClear/PreloadGenStart/Preload("text")/PreloadGenEnd("folder\\\\file.txt"); list those
    files in results (relative to Documents\\Warcraft III\\CustomMapData) and the run ends as soon as all exist.
    Returns the Preload strings per file, the useful War3Log.txt lines and any new crash report."""
    result = desktop_game.GAME.test(path, timeout=timeout, results=results, close=close, screenshot=screenshot)
    if "screenshot" in result:
        shot = config.home() / "screenshots" / f"game-{result['pid']}.png"
        shot.parent.mkdir(parents=True, exist_ok=True)
        shot.write_bytes(result.pop("screenshot"))
        result["screenshot"] = str(shot)
    return result


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
