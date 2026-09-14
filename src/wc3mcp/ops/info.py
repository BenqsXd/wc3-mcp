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
