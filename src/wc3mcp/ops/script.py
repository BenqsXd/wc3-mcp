"""Script tools on an open map: rebuild the editor-generated script parts, validate the script, cross-check files."""
import posixpath

from ..errors import ToolError
from ..formats import w3e, w3i
from ..formats.binary import FormatError
from ..script import build, world
from ..script import validate as scripts
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


def script_build(project, catalog) -> dict:
    lang = language(project)
    if lang == "lua":
        # ponytail: the editor transpiles its JASS to Lua (jass2lua); regenerate Lua here once Phase 3 can compare
        # against editor-saved Lua maps with GUI triggers
        raise ToolError("lua_not_supported", "regenerating war3map.lua is not supported yet",
                        hint="save the map in the World Editor to regenerate war3map.lua; script_validate still checks it")
    td = catalog.trigger_data
    tf, ct = _load(project, td)
    name = _script_file(project, lang)
    before = project.read(name)
    try:
        text = build.splice(before.decode("utf-8", "surrogateescape"), tf, ct, td, world=_world(project, catalog))
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
