"""Script tools on an open map: rebuild the editor-generated script parts, validate the script, cross-check files."""
import posixpath

from ..errors import ToolError
from ..formats import doo, unitsdoo, w3e, w3i
from ..formats.binary import FormatError
from ..script import build, lua, mapinfo, placed, world
from ..script import validate as scripts
from . import objdata
from . import validate as checks
from .elements import SOUND_EXTENSIONS, _load_file
from .strings import load_strings
from .triggers import _load, _read

SCRIPT_FILES = {"jass": ("war3map.j", "scripts\\war3map.j"), "lua": ("war3map.lua", "scripts\\war3map.lua")}


def _names(project) -> dict[str, str]:
    return {f["name"].lower(): f["name"] for f in project.list_files()}


def language(project) -> str:
    """The script language war3map.w3i selects ("jass" or "lua"); falls back to which script file exists."""
    try:
        return "lua" if w3i.parse(project.read("war3map.w3i")).script_language == 1 else "jass"
    except (ToolError, FormatError):
        return "lua" if "war3map.lua" in _names(project) else "jass"


def _script_file(project, lang: str) -> str:
    names = _names(project)
    name = next((names[n.lower()] for n in SCRIPT_FILES[lang] if n.lower() in names), None)
    if name is None:
        raise ToolError("no_script", f"the map has no {SCRIPT_FILES[lang][0]}",
                        hint="save the map in the World Editor once to create its script")
    return name


def _world(project, catalog) -> world.World:
    terrain = _read(project, "war3map.w3e")
    try:
        terrain = w3e.parse(terrain) if terrain is not None else None
    except FormatError:
        terrain = None

    def label_row(label: str) -> dict | None:
        try:
            return catalog.get("sound", label)["fields"]
        except ToolError:
            return None

    def audio(path: str) -> bytes | None:
        data = _read(project, path)
        if data is not None:
            return data
        stem = posixpath.splitext(path.replace("\\", "/"))[0]
        for ext in SOUND_EXTENSIONS:
            full = catalog.storage.resolve(stem + ext, **{**catalog.layer, "hd": False})
            if full:
                return catalog.storage.read(full)
        return None

    return world.World(_load_file(project, "region")[0], _load_file(project, "camera")[0],
                       _load_file(project, "sound")[0], terrain, load_strings(project), label_row, audio)


def balance(project) -> str:
    """The game data layer the editor uses for this map's script: melee (latest patch) for data set 2, else custom."""
    try:
        return "Melee_V1" if w3i.parse(project.read("war3map.w3i")).game_data_set == 2 else "Custom_V1"
    except (ToolError, FormatError):
        return "Custom_V1"


class _Objects:
    """The map's object data (war3map.* and war3mapSkin.* changes) over the catalog's objects."""
    FIELDS = {"unit": ["ubdg", "uabi", "utco"], "ability": ["aher", "aord", "aoro", "aorf"],
              "destructible": ["btco", "bvcr", "bvcg", "bvcb"], "item": ["itco"]}

    def __init__(self, project, catalog):
        self.project, self.catalog = project, catalog
        self._mods, self._ids, self._rows = {}, {}, {}

    def _changes(self, kind: str) -> dict[str, tuple[str, dict]]:
        if kind not in self._mods:
            table = {}
            for om in objdata._load(self.project, kind)[:2]:
                for custom, entries in ((False, om.original), (True, om.custom)):
                    for e in entries:
                        oid = (e.new_id if custom else e.base_id).decode("latin-1")
                        table.setdefault(oid, (e.base_id.decode("latin-1"), {}))[1].update(
                            {m.id.decode("latin-1"): m.value for m in e.mods if m.level <= 1})
            self._mods[kind] = table
        return self._mods[kind]

    def exists(self, kind: str, oid: str) -> bool:
        if kind not in self._ids:
            self._ids[kind] = set(self.catalog.ids(kind)) | {k for k, (base, _) in self._changes(kind).items() if k != base}
        return oid in self._ids[kind]

    def value(self, kind: str, oid: str, field: str):
        base, changes = self._changes(kind).get(oid, (oid, {}))
        if field in changes:
            return changes[field]
        if (kind, base) not in self._rows:
            try:
                doc = self.catalog.get(kind, base, self.FIELDS[kind])["fields"]
                self._rows[(kind, base)] = {k: v.get("value") for k, v in doc.items()}
            except ToolError:
                self._rows[(kind, base)] = {}
        return self._rows[(kind, base)].get(field)


def _int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parsed(project, name: str, codec):
    data = _read(project, name)
    try:
        return codec.parse(data) if data is not None else None
    except FormatError as e:
        raise ToolError("bad_file", f"{name}: {e}", hint="map_file_write can replace a damaged file") from e


def _world_edit_data(catalog) -> dict:
    """UI/WorldEditData.txt as section -> key -> value (first value of a repeated key wins)."""
    sections, current = {}, None
    for line in (catalog._read("UI/WorldEditData.txt") or b"").decode("utf-8", "replace").splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            current = sections.setdefault(line[1:-1], {})
        elif current is not None and "=" in line and not line.startswith("//"):
            key, value = line.split("=", 1)
            current.setdefault(key, value)
    return sections


def _mapinfo(project, catalog, objects: "_Objects", terrain) -> mapinfo.MapInfoParts | None:
    info = _parsed(project, "war3map.w3i", w3i)
    if info is None:
        return None
    return mapinfo.MapInfoParts(info, load_strings(project), _world_edit_data(catalog), terrain,
                                lambda i: objects.exists("ability", i) and not objects.exists("unit", i))


def _placed(project, catalog, objects: "_Objects | None" = None) -> placed.Placed:
    objects = objects or _Objects(project, catalog)
    parsed = lambda name, codec: _parsed(project, name, codec)  # noqa: E731

    def item(t: str) -> dict | None:
        if t != "iDNR" and not objects.exists("item", t):
            return None
        return {"team_color": _int(objects.value("item", t, "itco"), 0)}

    def unit(t: str) -> dict | None:
        if t == "sloc" or item(t) is not None:
            return None
        if t in ("uDNR", "bDNR"):
            return {"building": t == "bDNR", "abilities": [], "team_color": -1}
        return {"building": objects.value("unit", t, "ubdg") in (1, "1"),
                "abilities": str(objects.value("unit", t, "uabi") or "").split(","),
                "team_color": _int(objects.value("unit", t, "utco"), -1)}

    def ability(a: str) -> dict:
        return {"hero": objects.value("ability", a, "aher") in (1, "1"), "order": objects.value("ability", a, "aord"),
                "orderon": objects.value("ability", a, "aoro"), "orderoff": objects.value("ability", a, "aorf")}

    def destructible(t: str) -> dict | None:
        if not objects.exists("destructible", t):
            return None
        return {"team_color": _int(objects.value("destructible", t, "btco"), 24),
                "vertex": tuple(objects.value("destructible", t, f) for f in ("bvcr", "bvcg", "bvcb"))}

    info = parsed("war3map.w3i", w3i)
    return placed.Placed(parsed("war3mapUnits.doo", unitsdoo), parsed("war3map.doo", doo), info,
                         _load_file(project, "region")[0], unit, ability, destructible, item)


def lua_script(project, catalog, tf, ct, reference: str = "") -> str:
    """The editor's war3map.lua for the map files: its JASS script transpiled in the style of `reference`."""
    objects, scene = _Objects(project, catalog), _world(project, catalog)
    jass = build.new_script(tf, ct, catalog.trigger_data, scene, _placed(project, catalog, objects),
                            _mapinfo(project, catalog, objects, scene.terrain), reference=reference, raw=lua.RAW)
    return lua.transpile(jass, lua.natives(catalog), *lua.style(reference))


def script_build(project, catalog) -> dict:
    lang = language(project)
    td = catalog.trigger_data
    tf, ct = _load(project, td)
    names = _names(project)
    found = {k: next((names[n.lower()] for n in files if n.lower() in names), None) for k, files in SCRIPT_FILES.items()}
    name = found[lang] or SCRIPT_FILES[lang][0]
    before = project.read(name) if found[lang] else b""
    other = found["jass" if lang == "lua" else "lua"]
    try:
        original = before.decode("utf-8", "surrogateescape")
        # a missing script (a new map, or one switched to the other language) is generated whole; the other
        # language's script still supplies sound lengths and object order
        reference = original if original.strip() or other is None else project.read(other).decode("utf-8", "surrogateescape")
        if lang == "lua":
            if original.strip() and not lua.editor_generated(original):
                raise ValueError("no main and config functions")
            text = lua_script(project, catalog, tf, ct, reference)
        else:
            objects, scene = _Objects(project, catalog), _world(project, catalog)
            parts = dict(world=scene, placed=_placed(project, catalog, objects),
                         info=_mapinfo(project, catalog, objects, scene.terrain))
            text = (build.splice(original, tf, ct, td, **parts) if original.strip()
                    else build.new_script(tf, ct, td, reference=reference, **parts))
    except ValueError as e:
        raise ToolError("not_editor_script", f"{name}: {e}",
                        hint="this script was not written by the World Editor; edit it with map_file_write") from e
    data = text.encode("utf-8", "surrogateescape")
    if data != before:
        project.write(name, data)
    return {"changed": data != before, "language": lang, "file": name}


def script_validate(project, catalog) -> dict:
    lang = language(project)
    name = _script_file(project, lang)
    text = project.read(name).decode("utf-8", "surrogateescape")
    result = scripts.validate_lua(text) if lang == "lua" else scripts.validate_jass(text, catalog)
    return {"language": lang, "file": name, **result}


def map_validate(project, catalog) -> dict:
    names = _names(project)
    files = {real: project.read(real) for low, real in names.items()
             if ("\\" not in low and low.startswith("war3map")) or low.startswith("scripts\\")}
    return checks.validate(files, catalog, has_file=lambda n: n.replace("/", "\\").lower() in names)
