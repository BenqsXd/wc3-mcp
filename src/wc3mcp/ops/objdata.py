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


# ---- edits -----------------------------------------------------------------------------------------------------
ID_PREFIX = {"item": "I", "destructible": "B", "doodad": "D", "ability": "A", "buff": "B", "upgrade": "R"}
ID_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
SKIN_NETSAFE = frozenset({"1", "11"})
_HINT = ('ops: {"op": "create", "base": "hfoo", "set": {"Name": "Guard"}}, {"op": "set", "id": "h000", "set": '
         '{"uhpm": 500}}, {"op": "reset", "id": "h000", "fields": ["uhpm"]}, {"op": "delete", "id": "h000"}')


def _next_id(kind: str, base: str, taken: set[str]) -> str:
    prefix = base[0] if kind == "unit" else ID_PREFIX[kind]
    for n in range(36 ** 3):
        candidate = prefix + ID_ALPHABET[n // 1296] + ID_ALPHABET[n // 36 % 36] + ID_ALPHABET[n % 36]
        if candidate not in taken:
            return candidate
    raise ToolError("ids_exhausted", f"no free {kind} id with prefix {prefix!r}")


def _field(catalog, kind: str, base: str, key, path: str):
    fields = catalog.fields(kind)
    meta = next((f for f in fields if f.id == key), None)
    if meta is None:
        lowered = key.lower() if isinstance(key, str) else None
        candidates = [f for f in fields if lowered in (f.field.lower(), f.display_name.lower())
                      and catalog.applies(kind, base, f)]
        if len(candidates) > 1:
            raise ToolError("ambiguous_field", f"{path}: {key!r} matches several fields", hint="use the raw code",
                            candidates=[f"{f.id} ({f.display_name})" for f in candidates][:20])
        if not candidates:
            raise ToolError("unknown_field", f"{path}: no {kind} field {key!r}",
                            hint="objdata_get or data_get lists raw codes and field names")
        meta = candidates[0]
    if not catalog.applies(kind, base, meta):
        raise ToolError("field_not_applicable", f"{path}: field {meta.id} does not apply to {base}")
    return meta


def _number(text: str) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _convert(meta, value, path: str) -> tuple[int, object]:
    vt = var_type(meta.type)
    if vt == STRING:
        if isinstance(value, list) and all(isinstance(v, str) for v in value):
            value = ",".join(value)
        if not isinstance(value, str):
            raise ToolError("bad_value", f"{path}: {meta.id} expects text", path=path)
        return vt, value
    if isinstance(value, bool):
        value = int(value)
    if vt == INT and isinstance(value, float) and value.is_integer():
        value = int(value)
    if (vt == INT and not isinstance(value, int)) or (vt != INT and not isinstance(value, (int, float))):
        raise ToolError("bad_value", f"{path}: {meta.id} expects {'an integer' if vt == INT else 'a number'}",
                        path=path)
    low, high = _number(meta.min), _number(meta.max)
    if (low is not None and value < low) or (high is not None and value > high):
        raise ToolError("bad_value", f"{path}: {meta.id} must be between {meta.min} and {meta.max}", path=path)
    return vt, value if vt == INT else float(value)


def _level_values(meta, value, path: str) -> list[tuple[int, object]]:
    if meta.repeat > 0:
        if not isinstance(value, dict) or not value:
            raise ToolError("bad_value", f'{path}: {meta.id} has levels; give {{"1": value, "2": value}}', path=path)
        pairs = []
        for level, v in value.items():
            if not (isinstance(level, str) and level.isdigit() and int(level) >= 1):
                raise ToolError("bad_value", f"{path}: level keys must be numbers starting at 1", path=path)
            pairs.append((int(level), v))
        return pairs
    if isinstance(value, dict):
        raise ToolError("bad_value", f"{path}: {meta.id} has no levels", path=path)
    return [(0, value)]


def _entry_in(om: ObjectMods, custom: bool, base: bytes, new: bytes) -> ObjectEntry:
    table, key = (om.custom, new) if custom else (om.original, base)
    for entry in table:
        if (entry.new_id if custom else entry.base_id) == key:
            return entry
    entry = ObjectEntry(base, new if custom else objmods.ZERO_ID)
    table.append(entry)
    return entry


def _set(files, kind: str, custom: bool, base: bytes, new: bytes, meta, level: int, vt: int, value,
         strings: TriggerStrings) -> None:
    rid = meta.id.encode("latin-1")
    levels = EXTENSIONS[kind] in LEVEL_EXTENSIONS
    level = level if levels else 0
    for om in files:  # update an existing record wherever it lives (older maps keep skin fields in the main file)
        for mod in _entry_in(om, custom, base, new).mods:
            if mod.id == rid and mod.level == level:
                m = TRIGSTR.match(mod.value) if vt == STRING and isinstance(mod.value, str) else None
                if m:
                    strings.set(int(m.group(1)), value)
                else:
                    mod.var_type, mod.value = vt, value
                return
    target = files[1] if meta.netsafe in SKIN_NETSAFE else files[0]
    _entry_in(target, custom, base, new).mods.append(
        Mod(rid, vt, value, level, meta.data if levels else 0, objmods.ZERO_ID if custom else base))


def _set_many(files, catalog, kind: str, custom: bool, base: bytes, new: bytes, values, strings, path: str) -> None:
    if not isinstance(values, dict):
        raise ToolError("bad_op", f"{path}: set must be an object of field: value", hint=_HINT)
    for key, value in values.items():
        fpath = f"{path}.set.{key}"
        meta = _field(catalog, kind, base.decode("latin-1"), key, fpath)
        for level, v in _level_values(meta, value, fpath):
            vt, converted = _convert(meta, v, fpath)
            _set(files, kind, custom, base, new, meta, level, vt, converted, strings)


def _locate(files, base_ids: set[str], kind: str, obj_id, path: str) -> tuple[bool, bytes, bytes]:
    if not isinstance(obj_id, str):
        raise ToolError("bad_op", f"{path}: id must be a string", hint=_HINT)
    entries = _entries(files, obj_id)
    if entries:
        _, custom, entry = entries[0]
        return custom, entry.base_id, entry.new_id if custom else objmods.ZERO_ID
    if obj_id in base_ids:
        return False, obj_id.encode("latin-1"), objmods.ZERO_ID
    raise ToolError("not_found", f"{path}: no {kind} {obj_id!r} in this map or the game data",
                    hint="objdata_list shows map objects; data_search finds base objects")


def _remove(files, custom: bool, key: bytes) -> None:
    for om in files:
        if custom:
            om.custom = [e for e in om.custom if e.new_id != key]
        else:
            om.original = [e for e in om.original if e.base_id != key]


def objdata_edit(project, catalog, kind: str, ops: list) -> dict:
    main, skin, raw = _load(project, kind)
    files = (main, skin)
    strings = load_strings(project)
    wts_before = strings.serialize()
    base_ids = set(catalog.ids(kind))
    taken = base_ids | {_key(e, True) for om in files for e in om.custom}
    created = []
    for i, op in enumerate(ops):
        path = f"ops[{i}]"
        try:
            if not isinstance(op, dict):
                raise ToolError("bad_op", f"{path}: each op must be an object", hint=_HINT)
            action = op.get("op")
            if action == "create":
                base = op.get("base")
                if not isinstance(base, str) or base not in base_ids:
                    raise ToolError("not_found", f"{path}: base {kind} {base!r} does not exist",
                                    hint="data_search finds base object ids")
                new = op.get("id")
                if new is None:
                    new = _next_id(kind, base, taken)
                elif not (isinstance(new, str) and len(new) == 4 and all(33 <= ord(c) < 127 for c in new)):
                    raise ToolError("bad_value", f"{path}: id must be 4 printable ASCII characters", path=f"{path}.id")
                elif new in taken:
                    raise ToolError("id_taken", f"{path}: id {new!r} is already used", hint="omit id to allocate one")
                taken.add(new)
                created.append(new)
                base_b, new_b = base.encode("latin-1"), new.encode("latin-1")
                for om in files:  # the editor lists every object in both the main and the skin file
                    _entry_in(om, True, base_b, new_b)
                _set_many(files, catalog, kind, True, base_b, new_b, op.get("set", {}), strings, path)
            elif action == "set":
                custom, base_b, new_b = _locate(files, base_ids, kind, op.get("id"), path)
                for om in files:
                    _entry_in(om, custom, base_b, new_b)
                _set_many(files, catalog, kind, custom, base_b, new_b, op.get("set"), strings, path)
            elif action == "reset":
                custom, base_b, new_b = _locate(files, base_ids, kind, op.get("id"), path)
                keys = op.get("fields")
                if keys is None and not custom:
                    _remove(files, False, base_b)
                    continue
                if keys is not None and not (isinstance(keys, list) and all(isinstance(k, str) for k in keys)):
                    raise ToolError("bad_op", f"{path}: fields must be a list of field keys", hint=_HINT)
                rawcodes = None if keys is None else {
                    _field(catalog, kind, base_b.decode("latin-1"), k, f"{path}.fields[{j}]").id.encode("latin-1")
                    for j, k in enumerate(keys)}
                for _, _, entry in _entries(files, op["id"]):
                    entry.mods = [m for m in entry.mods if rawcodes is not None and m.id not in rawcodes]
            elif action == "delete":
                custom, base_b, new_b = _locate(files, base_ids, kind, op.get("id"), path)
                _remove(files, custom, new_b if custom else base_b)
            else:
                raise ToolError("bad_op", f"{path}: unknown op {action!r}", hint=_HINT)
        except ToolError as e:
            e.details.setdefault("op_index", i)
            raise
    try:
        payloads = [(name, objmods.serialize(om)) for om, name in zip(files, raw)
                    if raw[name] is not None or om.original or om.custom]
    except (FormatError, struct.error) as e:
        raise ToolError("bad_value", f"cannot encode object data: {e}", path="") from e
    changed = False
    for name, data in payloads:
        if data != raw[name]:
            project.write(name, data)
            changed = True
    wts_after = strings.serialize()
    if wts_after != wts_before:
        project.write("war3map.wts", wts_after)
        changed = True
    return {"changed": changed, "created": created, "warnings": []}
