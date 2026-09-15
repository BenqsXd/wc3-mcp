"""Campaigns (.w3n): war3campaign.w3f as editable JSON (text through war3campaign.wts), campaign screen buttons and
the maps stored inside the campaign."""
import copy
import math
import shutil
import struct
from pathlib import Path

from .. import pathguard
from ..errors import ToolError
from ..formats import w3f
from ..formats.binary import FormatError
from ..formats.wts import TRIGSTR, TriggerStrings
from ..mpq.writer import write_archive
from ..project.workspace import MapProject, check_name
from .edits import apply_ops
from .imports import imports_list
from .objdata import EXTENSIONS
from .strings import file_prefix, load_strings

INFO = "war3campaign.w3f"
STRINGS = "war3campaign.wts"
CURSORS = {0: "human", 1: "orc", 2: "undead", 3: "night_elf", 4: "forsaken"}
FOG_STYLES = {0: "linear", 1: "exponential_1", 2: "exponential_2", 3: "height", 4: "new_exponential_1",
              5: "new_exponential_2"}
BACKGROUND_VERSIONS = {0: "default", 1: "classic", 2: "reforged"}
FOG_FIELDS = {"z_start": "fog_z_start", "z_end": "fog_z_end", "density": "fog_density",
              "height_start": "fog_height_start", "height_end": "fog_height_end", "linear_start": "fog_linear_start",
              "linear_end": "fog_linear_end", "max_opacity": "fog_max_opacity"}
READ_ONLY = ("campaign_version", "editor_version", "maps", "imports", "object_data")
MAP_SUFFIXES = (".w3x", ".w3m")
_HINT = ('ops: {"op": "set", "path": "name", "value": "My Campaign"}, {"op": "append", "path": "buttons", "value": '
         '{"chapter": "Chapter One", "title": "The Start", "map": "Chapter1.w3x", "visible": true}}, '
         '{"op": "add_map", "source": "C:/maps/Chapter1.w3x"}, {"op": "remove_map", "name": "Chapter1.w3x"}, '
         '{"op": "extract_map", "name": "Chapter1.w3x", "dest": "C:/maps/Chapter1.w3x"}')


def _bad(path: str, message: str, code: str = "bad_value") -> ToolError:
    return ToolError(code, f"{path}: {message}", hint=_HINT, path=path)


# ---- presets ---------------------------------------------------------------------------------------------------
class Presets:
    """Campaign Editor choices from UI/WorldEditData.txt: minimap images, background screens, ambient sounds."""

    def __init__(self, catalog):
        from .script import _world_edit_data

        data = _world_edit_data(catalog)

        def rows(section: str, count_key: str) -> list[list[str]]:
            table = data.get(section, {})
            return [table[f"{i:02d}"].split(",") for i in range(int(table.get(count_key, 0))) if f"{i:02d}" in table]

        self.images = [(catalog.westring(r[0]), r[1]) for r in rows("CampaignImages", "NumImages")]
        self.backgrounds = ([catalog.westring(r[1]) for r in rows("CampaignScreens", "NumScreens")]
                            + ["Loading - " + catalog.westring(r[1]) for r in rows("LoadingScreens", "NumScreens")])
        self.sounds = [catalog.westring(r[1]) for r in rows("AmbientSounds", "NumSounds")]

    @staticmethod
    def index(names: list[str], value, path: str) -> int:
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < len(names):
            return value
        if isinstance(value, str):
            hit = next((i for i, n in enumerate(names) if n.lower() == value.lower()), None)
            if hit is not None:
                return hit
        raise ToolError("bad_value", f"{path}: unknown preset {value!r}", hint=f"one of: {', '.join(names[:20])}"
                        + (" ..." if len(names) > 20 else ""), path=path, choices=names)


# ---- JSON view -------------------------------------------------------------------------------------------------
def _text_out(doc: dict, key: str, value: str, strings: TriggerStrings) -> None:
    doc[key] = strings.resolve(value) if TRIGSTR.match(value) else value
    if TRIGSTR.match(value):
        doc[key + "_ref"] = value


def _text_in(doc: dict, key: str, path: str, original: str, strings: TriggerStrings) -> str:
    value = doc.get(key)
    if not isinstance(value, str):
        raise _bad(f"{path}{key}", "expected text")
    ref = doc.get(key + "_ref")
    m = TRIGSTR.match(ref) if isinstance(ref, str) else None
    if ref is not None and not m:
        raise _bad(f"{path}{key}_ref", "expected TRIGSTR_<number>")
    if m:
        if strings.resolve(ref) != value:
            strings.set(int(m.group(1)), value)
        return ref
    if value == original:
        return original
    return f"TRIGSTR_{strings.add(value):03d}"   # the Campaign Editor keeps edited text in war3campaign.wts


def _float_out(v: float) -> float:
    return round(v, 4) if math.isfinite(v) and abs(v) < 1e30 else 0.0   # the editor shows its garbage defaults as 0


def to_json(ci: w3f.CampaignInfo, strings: TriggerStrings, presets: Presets, project) -> dict:
    doc = {}
    for key in ("name", "difficulty", "author", "description"):
        _text_out(doc, key, getattr(ci, key), strings)
    doc["variable_difficulty"] = bool(ci.flags & w3f.FLAG_VARIABLE_DIFFICULTY)
    if ci.flags & w3f.FLAG_MINIMAP_FROM_MAP:
        doc["minimap"] = {"map": ci.minimap_path}
    elif not ci.minimap_path:
        doc["minimap"] = None
    else:
        preset = next((label for label, p in presets.images if p.lower() == ci.minimap_path.lower()), None)
        doc["minimap"] = {"preset": preset} if preset else {"file": ci.minimap_path}

    def choice(index: int, file: str, names: list[str]):
        if file:
            return {"file": file}
        if index < 0:
            return None
        return {"preset": index, "name": names[index] if index < len(names) else None}

    fog = None
    if ci.fog_style >= 0:
        fog = {"style": FOG_STYLES.get(ci.fog_style, ci.fog_style),
               **{k: _float_out(getattr(ci, attr)) for k, attr in FOG_FIELDS.items()},
               "color": {"r": ci.fog_color[2], "g": ci.fog_color[1], "b": ci.fog_color[0], "a": ci.fog_color[3]},
               "over_sky": bool(ci.fog_over_sky)}
    doc["loading_screen"] = {
        "background": choice(ci.background, ci.background_path, presets.backgrounds),
        "background_version": BACKGROUND_VERSIONS.get(ci.background_version, ci.background_version),
        "ambient_sound": choice(ci.ambient_sound, ci.ambient_sound_path, presets.sounds),
        "cursor": CURSORS.get(ci.cursor, ci.cursor), "fog": fog}
    buttons = []
    for b in ci.buttons:
        button = {}
        _text_out(button, "chapter", b.chapter, strings)
        _text_out(button, "title", b.title, strings)
        button.update(map=b.map, visible=bool(b.flags & w3f.BUTTON_VISIBLE), cinematic=bool(b.flags & w3f.BUTTON_CINEMATIC))
        buttons.append(button)
    doc["buttons"] = buttons
    sizes = {f["name"].lower(): f["size"] for f in project.list_files()}
    used = {b.map.lower() for b in ci.buttons}
    doc["maps"] = [{"name": m.path, "size": sizes.get(m.path.lower()), "used": m.path.lower() in used} for m in ci.maps]
    doc["campaign_version"], doc["editor_version"] = ci.campaign_version, ci.editor_version
    return doc


def _enum_in(value, names: dict, path: str) -> int:
    for k, v in names.items():
        if value == v or value == k:
            return k
    raise _bad(path, f"expected one of {', '.join(names.values())}")


def _bool(doc: dict, key: str, path: str) -> bool:
    if not isinstance(doc.get(key), bool):
        raise _bad(path + key, "expected true or false")
    return doc[key]


def from_json(doc: dict, strings: TriggerStrings, presets: Presets, original: w3f.CampaignInfo,
              maps: list[str], imported) -> tuple[w3f.CampaignInfo, list[str]]:
    ci, warnings = copy.deepcopy(original), []
    for key in ("name", "difficulty", "author", "description"):
        setattr(ci, key, _text_in(doc, key, "", getattr(original, key), strings))
    flags = ci.flags & ~(w3f.FLAG_VARIABLE_DIFFICULTY | w3f.FLAG_MINIMAP_FROM_MAP | w3f.FLAG_IMPORTED_AMBIENT)
    if _bool(doc, "variable_difficulty", ""):
        flags |= w3f.FLAG_VARIABLE_DIFFICULTY

    minimap = doc.get("minimap")
    if minimap is None:
        ci.minimap_path = ""
    elif isinstance(minimap, dict) and len(minimap) == 1 and "map" in minimap:
        if not any(isinstance(minimap["map"], str) and minimap["map"].lower() == m.lower() for m in maps):
            raise _bad("minimap.map", f"{minimap['map']!r} is not a map of this campaign")
        ci.minimap_path, flags = minimap["map"], flags | w3f.FLAG_MINIMAP_FROM_MAP
    elif isinstance(minimap, dict) and len(minimap) == 1 and "preset" in minimap:
        ci.minimap_path = presets.images[Presets.index([n for n, _ in presets.images], minimap["preset"],
                                                       "minimap.preset")][1]
    elif isinstance(minimap, dict) and len(minimap) == 1 and isinstance(minimap.get("file"), str):
        ci.minimap_path = minimap["file"].replace("/", "\\")
        if not imported(minimap["file"]):
            warnings.append(f"minimap file {minimap['file']!r} is not in the campaign (imports_edit adds it)")
    else:
        raise _bad("minimap", 'expected null, {"preset": name}, {"map": name} or {"file": import path}')

    screen = doc.get("loading_screen")
    if not isinstance(screen, dict):
        raise _bad("loading_screen", "expected an object")

    def choice(key: str, names: list[str]) -> tuple[int, str]:
        value, path = screen.get(key), f"loading_screen.{key}"
        if value is None:
            return -1, ""
        if isinstance(value, dict) and "preset" in value and set(value) <= {"preset", "name"}:
            index = Presets.index(names, value["preset"], path + ".preset")
            if value.get("name") is not None and value["preset"] != value["name"] and names[index] != value["name"]:
                raise _bad(path + ".name", "set preset to change the choice (name is read-only)")
            return index, ""
        if isinstance(value, dict) and set(value) == {"file"} and isinstance(value["file"], str) and value["file"]:
            if not imported(value["file"]):
                warnings.append(f"{key.replace('_', ' ')} file {value['file']!r} is not in the campaign "
                                "(imports_edit adds it)")
            return -1, value["file"].replace("/", "\\")
        raise _bad(path, 'expected null, {"preset": index or name} or {"file": import path}')

    ci.background, ci.background_path = choice("background", presets.backgrounds)
    ci.ambient_sound, ci.ambient_sound_path = choice("ambient_sound", presets.sounds)
    if ci.ambient_sound_path:
        flags |= w3f.FLAG_IMPORTED_AMBIENT
    ci.flags = flags
    ci.background_version = _enum_in(screen.get("background_version"), BACKGROUND_VERSIONS,
                                     "loading_screen.background_version")
    ci.cursor = _enum_in(screen.get("cursor"), CURSORS, "loading_screen.cursor")
    fog = screen.get("fog")
    if fog is None:
        ci.fog_style = -1
    elif isinstance(fog, dict):
        path = "loading_screen.fog."
        unknown = set(fog) - set(FOG_FIELDS) - {"style", "color", "over_sky"}
        if unknown:
            raise _bad(path + sorted(unknown)[0], "unknown fog field")
        ci.fog_style = _enum_in(fog.get("style"), FOG_STYLES, path + "style")
        was_off = original.fog_style < 0
        for key, attr in FOG_FIELDS.items():
            old = getattr(original, attr)
            if key not in fog:
                if was_off and _float_out(old) == 0.0:
                    setattr(ci, attr, 0.0)
                continue
            value = fog[key]
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                raise _bad(path + key, "expected a number")
            if value != _float_out(old) or was_off:   # an unchanged shown value keeps the stored bits
                setattr(ci, attr, struct.unpack("<f", struct.pack("<f", value))[0])
        if "color" in fog:
            color = fog["color"]
            parts = [color.get(k, 255 if k == "a" else None) for k in ("b", "g", "r", "a")] if isinstance(color, dict) else []
            if len(parts) != 4 or not all(isinstance(x, int) and not isinstance(x, bool) and 0 <= x <= 255 for x in parts):
                raise _bad(path + "color", "expected {r, g, b, a?} with components 0-255")
            ci.fog_color = bytes(parts)
        elif was_off:
            ci.fog_color = b"\0\0\0\xff"
        if "over_sky" in fog:
            ci.fog_over_sky = int(_bool(fog, "over_sky", path))
    else:
        raise _bad("loading_screen.fog", "expected null or an object with style and fog values")

    buttons = doc.get("buttons")
    if not isinstance(buttons, list):
        raise _bad("buttons", "expected a list")
    old_buttons = original.buttons
    ci.buttons = []
    for i, b in enumerate(buttons):
        path = f"buttons[{i}]."
        if not isinstance(b, dict):
            raise _bad(f"buttons[{i}]", "expected {chapter, title, map, visible, cinematic}")
        unknown = set(b) - {"chapter", "chapter_ref", "title", "title_ref", "map", "visible", "cinematic"}
        if unknown:
            raise _bad(path + sorted(unknown)[0], "unknown button field")
        b = {"chapter": "", "title": "", "visible": False, "cinematic": False, **b}
        target = b.get("map")
        hit = next((m for m in maps if isinstance(target, str) and m.lower() == target.lower()), None)
        if hit is None:
            raise _bad(path + "map", f"{target!r} is not a map of this campaign (add_map adds it)")
        before = old_buttons[i] if i < len(old_buttons) else w3f.Button(0, "", "", "")
        ci.buttons.append(w3f.Button(
            (w3f.BUTTON_VISIBLE if _bool(b, "visible", path) else 0) | (w3f.BUTTON_CINEMATIC if _bool(b, "cinematic", path) else 0),
            _text_in(b, "chapter", path, before.chapter, strings), _text_in(b, "title", path, before.title, strings), hit))
    used = {b.map.lower() for b in ci.buttons}
    unused = [m for m in maps if m.lower() not in used]
    if unused:
        warnings.append(f"maps without a campaign screen button: {', '.join(unused)} (the editor warns on save)")
    return ci, warnings


# ---- loading ---------------------------------------------------------------------------------------------------
def _load(project) -> w3f.CampaignInfo:
    if file_prefix(project) != "war3campaign":
        raise ToolError("not_a_campaign", "this is a map, not a campaign (no war3campaign.w3f)",
                        hint="open a .w3n campaign, or create one with campaign_new")
    try:
        return w3f.parse(project.read(INFO))
    except FormatError as e:
        raise ToolError("bad_file", f"{INFO}: {e}", hint="re-save the campaign in the Campaign Editor") from e


def _object_data(project) -> dict:
    names = {f["name"].lower() for f in project.list_files()}
    return {kind: [n for n in (f"war3campaign.{ext}", f"war3campaignSkin.{ext}") if n.lower() in names]
            for kind, ext in EXTENSIONS.items() if f"war3campaign.{ext}" in names or f"war3campaignskin.{ext}" in names}


def campaign_get(project, catalog) -> dict:
    ci = _load(project)
    doc = to_json(ci, load_strings(project), Presets(catalog), project)
    doc["imports"] = len(imports_list(project))
    doc["object_data"] = _object_data(project)
    return doc


def _map_source(op: dict, path: str) -> bytes:
    src = op.get("source")
    if not isinstance(src, str) or not Path(src).is_file():
        raise _bad(path + ".source", f"no map file at {src!r}", "not_found")
    data = Path(src).read_bytes()
    if not (data[:4] in (b"HM3W", b"MPQ\x1a") or data.find(b"MPQ\x1a", 0, 0x10000) >= 0):
        raise _bad(path + ".source", "not a Warcraft III map archive (.w3x/.w3m)")
    return data


def _map_name(value, path: str) -> str:
    if not isinstance(value, str) or "\\" in value or "/" in value or not value.lower().endswith(MAP_SUFFIXES):
        raise _bad(path, "expected a map file name ending in .w3x or .w3m, without folders")
    return check_name(value)


def campaign_edit(project, catalog, ops: list) -> dict:
    ci = _load(project)
    strings = load_strings(project)
    presets = Presets(catalog)
    wts_before = strings.serialize()
    doc = to_json(ci, strings, presets, project)
    maps = [m.path for m in ci.maps]
    files = {f["name"].lower() for f in project.list_files()}
    writes, deletes, extracts = {}, set(), []
    if not isinstance(ops, list):
        raise ToolError("bad_op", "ops must be a list", hint=_HINT)
    for i, op in enumerate(ops):
        path = f"ops[{i}]"
        try:
            kind = op.get("op") if isinstance(op, dict) else None
            if kind in ("set", "append", "remove"):
                root = str(op.get("path", "")).split(".")[0].split("[")[0]
                if root in READ_ONLY:
                    raise _bad(f"{path}.path", f"{root} is read-only here" + (" (use add_map / remove_map)"
                                                                               if root == "maps" else ""))
                doc = apply_ops(doc, [op])
            elif kind == "add_map":
                name = _map_name(op.get("name", Path(str(op.get("source", ""))).name), f"{path}.name")
                if any(m.lower() == name.lower() for m in maps):
                    raise _bad(f"{path}.name", f"the campaign already has {name!r} (replace_map swaps it)", "name_taken")
                writes[name.lower()] = (name, _map_source(op, path))
                deletes.discard(name.lower())
                maps.append(name)
            elif kind in ("replace_map", "remove_map", "extract_map"):
                name = next((m for m in maps if isinstance(op.get("name"), str) and m.lower() == op["name"].lower()), None)
                if name is None:
                    raise _bad(f"{path}.name", f"no map {op.get('name')!r} in this campaign", "not_found")
                if kind == "replace_map":
                    writes[name.lower()] = (name, _map_source(op, path))
                elif kind == "remove_map":
                    maps.remove(name)
                    writes.pop(name.lower(), None)
                    deletes.add(name.lower())
                else:
                    dest = op.get("dest")
                    if not isinstance(dest, str):
                        raise _bad(f"{path}.dest", "expected a file path")
                    target = pathguard.ensure_writable(dest)
                    if target.exists():
                        raise _bad(f"{path}.dest", f"{target} already exists", "exists")
                    extracts.append((name, target))
            else:
                raise ToolError("bad_op", f"{path}: unknown op {kind!r}", hint=_HINT)
        except ToolError as e:
            e.details.setdefault("op_index", i)
            raise
    for root in READ_ONLY:
        doc.pop(root, None)
    imported_names = files | set(writes)
    new_ci, warnings = from_json(doc, strings, presets, ci, maps,
                                 lambda p: p.replace("/", "\\").lower() in imported_names)
    new_ci.maps = [next((m for m in ci.maps if m.path == name), w3f.CampaignMap("", name)) for name in maps]
    for name, target in extracts:
        if name.lower() in writes:
            data = writes[name.lower()][1]
        elif name.lower() in deletes:
            raise ToolError("bad_op", f"cannot extract {name!r}: it is removed in the same batch", hint=_HINT)
        else:
            data = project.read(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    data = w3f.serialize(new_ci)
    changed = False
    for name, payload in writes.values():
        project.write(name, payload)
        changed = True
    for f in project.list_files():
        if f["name"].lower() in deletes:
            project.delete(f["name"])
            changed = True
    if data != project.read(INFO):
        project.write(INFO, data)
        changed = True
    wts_after = strings.serialize()
    if wts_after != wts_before:
        project.write(STRINGS, wts_after)
        changed = True
    return {"changed": changed, "extracted": [str(t) for _, t in extracts], "warnings": warnings}


def campaign_checks(project) -> dict:
    """map_validate for campaigns: buttons, maps and strings."""
    errors, warnings = [], []
    try:
        ci = _load(project)
    except ToolError as e:
        return {"errors": [{"file": INFO, "check": "campaign", "message": e.message}], "warnings": []}
    names = {f["name"].lower() for f in project.list_files()}
    strings = load_strings(project)
    ids = {e.id for e in strings.entries}
    for m in ci.maps:
        if m.path.lower() not in names:
            errors.append({"file": INFO, "check": "campaign_map", "message": f"map {m.path!r} is listed but not stored"})
    listed = {m.path.lower() for m in ci.maps}
    for i, b in enumerate(ci.buttons):
        if b.map.lower() not in listed:
            errors.append({"file": INFO, "check": "campaign_button", "message": f"button {i} loads {b.map!r}, which is "
                                                                                 "not a map of the campaign"})
    used = {b.map.lower() for b in ci.buttons}
    for m in ci.maps:
        if m.path.lower() not in used:
            warnings.append({"file": INFO, "check": "campaign_map", "message": f"map {m.path!r} has no campaign "
                                                                               "screen button"})
    texts = [ci.name, ci.difficulty, ci.author, ci.description] + [t for b in ci.buttons for t in (b.chapter, b.title)]
    for text in texts:
        m = TRIGSTR.match(text)
        if m and int(m.group(1)) not in ids:
            errors.append({"file": INFO, "check": "trigstr", "message": f"{text} is missing from {STRINGS}"})
    return {"errors": errors, "warnings": warnings}


def new_campaign(path, catalog, name: str | None = None, author: str | None = None, format: str = "mpq") -> MapProject:
    target = pathguard.ensure_writable(path)
    if target.exists():
        raise ToolError("exists", f"{target} already exists", hint="choose a new path, or map_open the campaign")
    if format not in ("mpq", "folder"):
        raise ToolError("bad_value", "format: expected mpq or folder", path="format")
    files = {INFO: w3f.serialize(w3f.CampaignInfo())}
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        if format == "folder":
            target.mkdir()
            (target / INFO).write_bytes(files[INFO])
        else:
            target.write_bytes(write_archive(files))
        project = MapProject.open(target)
        ops = [{"op": "set", "path": key, "value": value} for key, value in (("name", name), ("author", author))
               if value is not None]
        if ops:
            campaign_edit(project, catalog, ops)
            project.save(force=True)
        return project
    except BaseException:
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        else:
            target.unlink(missing_ok=True)
        raise
