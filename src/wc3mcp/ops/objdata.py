"""Object data (the Object Editor): map modifications merged over base game data, plus atomic edits."""
import struct

from ..errors import ToolError
from ..formats import objmods
from ..formats.binary import FormatError
from ..formats.objmods import INT, LEVEL_EXTENSIONS, REAL, STRING, UNREAL, Mod, ObjectEntry, ObjectMods
from ..formats.wts import TRIGSTR, TriggerStrings
from .strings import load_strings

EXTENSIONS = {"unit": "w3u", "item": "w3t", "destructible": "w3b", "doodad": "w3d", "ability": "w3a",
              "buff": "w3h", "upgrade": "w3q"}
INT_TYPES = frozenset({
    "int", "bool", "attackBits", "channelFlags", "channelType", "deathType", "detectionType", "fullFlags",
    "spellDetail", "stackFlags", "teamColor", "versionFlags",
    # never used in local maps; UI/UnitEditorData.txt lists numeric values for them
    "damageType", "defenseTypeInt", "interactionFlags", "morphFlags", "pickFlags", "proctargetType", "silenceFlags",
})
NAME_FIELDS = ("name", "editorname", "bufftip")


def var_type(meta_type: str) -> int:
    if meta_type == "real":
        return REAL
    if meta_type == "unreal":
        return UNREAL
    return INT if meta_type in INT_TYPES else STRING


def _check_kind(kind: str) -> str:
    if kind not in EXTENSIONS:
        raise ToolError("bad_kind", f"object data kind {kind!r} is not supported",
                        hint="one of: " + ", ".join(EXTENSIONS))
    return EXTENSIONS[kind]


def _load(project, kind: str) -> tuple[ObjectMods, ObjectMods, dict]:
    """The main and skin files for `kind` (empty v3 tables when absent) plus their original bytes by name."""
    ext = _check_kind(kind)
    levels, files, raw = ext in LEVEL_EXTENSIONS, [], {}
    for prefix in ("war3map", "war3mapSkin"):
        name = f"{prefix}.{ext}"
        try:
            data = project.read(name)
        except ToolError as e:
            if e.code != "no_such_file":
                raise
            data = None
        raw[name] = data
        try:
            files.append(objmods.parse(data, levels) if data is not None else ObjectMods(3, levels))
        except FormatError as e:
            raise ToolError("bad_file", f"{name}: {e}") from e
    return files[0], files[1], raw


def _key(entry: ObjectEntry, custom: bool) -> str:
    return (entry.new_id if custom else entry.base_id).decode("latin-1")


def _entries(files, obj_id: str) -> list[tuple[ObjectMods, bool, ObjectEntry]]:
    return [(om, custom, entry) for om in files for custom, table in ((False, om.original), (True, om.custom))
            for entry in table if _key(entry, custom) == obj_id]


def _merged(entries) -> dict[tuple[str, int], Mod]:
    merged = {}
    for _, _, entry in entries:
        for mod in entry.mods:
            merged[(mod.id.decode("latin-1"), mod.level)] = mod
    return merged


def _f32(v: float) -> float:
    """Shortest decimal that encodes to the same float32 (0.300000012 -> 0.3)."""
    packed = struct.pack("<f", v)
    for digits in range(6, 10):
        candidate = float(f"{v:.{digits}g}")
        if struct.pack("<f", candidate) == packed:
            return candidate
    return v


def _typed(meta_type: str, raw):
    """Catalog values are raw SLK/profile strings; show them with the type the object editor stores."""
    vt = var_type(meta_type)
    if raw is None or vt == STRING:
        return raw
    try:
        return int(float(raw)) if vt == INT else _f32(float(raw))
    except ValueError:
        return raw


def _mod_out(mod: Mod, strings: TriggerStrings) -> tuple[object, str | None]:
    if mod.var_type in (REAL, UNREAL):
        return _f32(mod.value), None
    if mod.var_type == STRING and TRIGSTR.match(mod.value):
        return strings.resolve(mod.value), mod.value
    return mod.value, None


def _name(catalog, kind: str, base: str, mods: dict, strings: TriggerStrings) -> str:
    by_field = {f.field.lower(): f.id for f in catalog.fields(kind)}
    for key in NAME_FIELDS:
        rawcode = by_field.get(key)
        mod = rawcode and (mods.get((rawcode, 0)) or mods.get((rawcode, 1)))
        if mod:
            return str(_mod_out(mod, strings)[0])
    return catalog.name(kind, base)


def objdata_list(project, catalog, kind: str, custom_only: bool = False) -> dict:
    main, skin, _ = _load(project, kind)
    strings = load_strings(project)
    found: dict[str, dict] = {}
    for om in (main, skin):
        for custom, table in ((False, om.original), (True, om.custom)):
            for entry in table:
                oid = _key(entry, custom)
                item = found.setdefault(oid, {"id": oid, "base": entry.base_id.decode("latin-1"), "custom": custom,
                                              "modifications": 0})
                item["modifications"] += len(entry.mods)
    objects = []
    for oid, item in found.items():
        if (custom_only and not item["custom"]) or (not item["custom"] and item["modifications"] == 0):
            continue
        item["name"] = _name(catalog, kind, item["base"], _merged(_entries((main, skin), oid)), strings)
        objects.append(item)
    objects.sort(key=lambda o: (not o["custom"], o["id"]))
    return {"kind": kind, "count": len(objects), "objects": objects}


def objdata_get(project, catalog, kind: str, obj_id: str, fields: list[str] | None = None) -> dict:
    main, skin, _ = _load(project, kind)
    strings = load_strings(project)
    entries = _entries((main, skin), obj_id)
    custom = any(c for _, c, _ in entries)
    base = entries[0][2].base_id.decode("latin-1") if entries else obj_id
    doc = catalog.get(kind, base, fields)
    mods = _merged(entries)
    top = max([doc["levels"]] + [level for _, level in mods])
    used = set()
    for rawcode, entry in doc["fields"].items():
        if "values" in entry:
            values = [_typed(entry["type"], v) for v in entry["values"]]
            values += [None] * (top - len(values))
            modified = []
            for level in range(1, top + 1):
                mod = mods.get((rawcode, level)) or (mods.get((rawcode, 0)) if level == 1 else None)
                if mod is None:
                    continue
                values[level - 1], ref = _mod_out(mod, strings)
                used.add((rawcode, mod.level))
                modified.append(level)
                if ref:
                    entry.setdefault("value_refs", {})[str(level)] = ref
            entry["values"], entry["modified"] = values, modified
        else:
            entry["value"] = _typed(entry["type"], entry["value"])
            mod = mods.get((rawcode, 0))
            entry["modified"] = mod is not None
            if mod is not None:
                entry["value"], ref = _mod_out(mod, strings)
                used.add((rawcode, 0))
                if ref:
                    entry["value_ref"] = ref
    if fields is None:
        doc["unknown_modifications"] = [{"id": rid, "level": level, "value": _mod_out(mod, strings)[0]}
                                        for (rid, level), mod in mods.items() if (rid, level) not in used]
    doc.update({"id": obj_id, "base": base, "custom": custom, "levels": top,
                "name": _name(catalog, kind, base, mods, strings)})
    return doc
