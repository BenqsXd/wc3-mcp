"""Object data (the Object Editor): map modifications merged over base game data, plus atomic edits."""
import dataclasses
import re
import struct

from ..errors import ToolError
from ..formats import objmods
from ..formats.binary import FormatError
from ..formats.objmods import INT, LEVEL_EXTENSIONS, REAL, STRING, UNREAL, Mod, ObjectEntry, ObjectMods
from ..formats.wts import TRIGSTR, TriggerStrings
from ..gamedata.catalog import MODEL_FIELDS
from .strings import file_prefix, load_strings, strings_file

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
    stem = file_prefix(project)
    for prefix in (stem, stem + "Skin"):
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


LEVEL_FIELDS = {"ability": "alev", "upgrade": "glvl"}


def objdata_get(project, catalog, kind: str, obj_id: str, fields: list[str] | None = None) -> dict:
    main, skin, _ = _load(project, kind)
    strings = load_strings(project)
    entries = _entries((main, skin), obj_id)
    custom = any(c for _, c, _ in entries)
    base = entries[0][2].base_id.decode("latin-1") if entries else obj_id
    doc = catalog.get(kind, base, fields)
    mods = _merged(entries)
    # the map's own level count (alev, glvl) decides how many levels exist in the game
    count = mods.get((LEVEL_FIELDS.get(kind), 0))
    top = max(1, int(count.value)) if count is not None else max([doc["levels"]] + [level for _, level in mods])
    used = set()
    for rawcode, entry in doc["fields"].items():
        if "values" in entry:
            values = [_typed(entry["type"], v) for v in entry["values"]]
            values += [None] * (top - len(values))
            modified = []
            values = values[:top]
            for level in sorted({level for rid, level in mods if rid == rawcode and level > top}):
                entry.setdefault("unused_levels", {})[str(level)] = _mod_out(mods[(rawcode, level)], strings)[0]
                used.add((rawcode, level))
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
    file_field, count_field = MODEL_FIELDS.get(kind, (None, None))
    file_mod, count_mod = mods.get((file_field, 0)), mods.get((count_field, 0))
    if "model" in doc and (file_mod or count_mod):   # the map's own model: check that one, imports included
        file = file_mod.value if file_mod else catalog.field(kind, base, file_field)
        count = int(count_mod.value) if count_mod else (catalog.model(kind, base) or ("", 1))[1]
        imported = {f["name"].lower() for f in project.list_files()}
        paths = catalog.model_paths(file, count) if file else []
        doc["model"] = {"files": paths, "source": "map", "missing": [
            p for p in paths if not (catalog.model_exists(p) and catalog.model_exists(p, hd=True))
            and not {p.lower(), p[:-4].lower() + ".mdx"} & imported]}
    return doc


# ---- edits -----------------------------------------------------------------------------------------------------
ID_PREFIX = {"item": "I", "destructible": "B", "doodad": "D", "ability": "A", "buff": "B", "upgrade": "R"}
ID_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
SKIN_NETSAFE = frozenset({"1", "11"})
_HINT = ('ops: {"op": "create", "base": "hfoo", "set": {"Name": "Guard"}}, {"op": "set", "id": "h000", "set": '
         '{"uhpm": 500}}, {"op": "reset", "id": "h000", "fields": ["uhpm"]}, {"op": "delete", "id": "h000"}')
OP_KEYS = {"create": {"op", "base", "id", "set"}, "set": {"op", "id", "set"}, "reset": {"op", "id", "fields"},
           "delete": {"op", "id"}}


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
    if isinstance(value, str) and _number(value) is not None:
        value = _number(value)   # data_get hands per-level values back as text: take them as the numbers they are
    if vt == INT and isinstance(value, float) and value.is_integer():
        value = int(value)
    if (vt == INT and not isinstance(value, int)) or (vt != INT and not isinstance(value, (int, float))):
        raise ToolError("bad_value", f"{path}: {meta.id} expects {'an integer' if vt == INT else 'a number'}",
                        path=path)
    low, high = _number(meta.min), _number(meta.max)
    if (low is not None and value < low) or (high is not None and value > high):
        raise ToolError("bad_value", f"{path}: {meta.id} must be between {meta.min} and {meta.max}", path=path)
    return vt, value if vt == INT else float(value)


GENERATOR_KEYS = {"from", "step", "to", "levels"}
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _fmt(value) -> str:
    """A field value as a tooltip shows it: 12.0 -> 12, 7.50 -> 7.5."""
    number = _number(value) if not isinstance(value, (int, float)) else float(value)
    if number is None:
        return str(value)
    return str(int(number)) if number.is_integer() else f"{number:g}"


def _generated(meta, value: dict, path: str, count: int) -> list[tuple[int, object]]:
    """{"from": a, "step": s} or {"from": a, "to": b}, with "levels" (default: the object's level count)."""
    if set(value) - GENERATOR_KEYS or "from" not in value or ("step" in value) == ("to" in value):
        raise ToolError("bad_value", f'{path}: a generated {meta.id} is {{"from": a, "step": s}} or '
                                     '{"from": a, "to": b}, optionally with "levels"', path=path)
    n = value.get("levels", count)
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 100:
        raise ToolError("bad_value", f"{path}: levels must be 1-100", path=path)
    start = _number(value["from"])
    end = _number(value.get("to", 0))
    step = _number(value["step"]) if "step" in value else ((end - start) / (n - 1) if n > 1 and start is not None
                                                           and end is not None else 0.0)
    if start is None or step is None:
        raise ToolError("bad_value", f"{path}: from, step and to are numbers", path=path)
    whole = var_type(meta.type) == INT
    return [(level, round(start + step * (level - 1)) if whole else round(start + step * (level - 1), 4))
            for level in range(1, n + 1)]


def _level_values(meta, value, path: str, count: int = 1) -> list[tuple[int, object]]:
    if meta.repeat > 0:
        if isinstance(value, list):
            if not value or len(value) > 100:
                raise ToolError("bad_value", f"{path}: a list gives levels 1..n (1-100 values)", path=path)
            return list(enumerate(value, start=1))
        if isinstance(value, dict) and GENERATOR_KEYS & set(value):
            return _generated(meta, value, path, count)
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


def _level_count(files, catalog, kind: str, custom: bool, base: bytes, new: bytes) -> int:
    """How many levels the object has in the game: the map's own alev/glvl, else the base object's."""
    field = LEVEL_FIELDS.get(kind)
    if field is None:
        return 0
    rid = field.encode("latin-1")
    for om in files:
        for mod in _entry_in(om, custom, base, new).mods:
            if mod.id == rid and mod.level == 0:
                return max(1, int(mod.value))
    return max(1, int(_number(catalog.field(kind, base.decode("latin-1"), field)) or 1))


def _extend_levels(files, catalog, kind: str, custom: bool, base: bytes, new: bytes, before: int, strings,
                   path: str) -> dict | None:
    """More levels than the base object has: the World Editor repeats the last value of every per-level field into
    the new ranks, and the game reads nothing there otherwise, so do the same."""
    top = _level_count(files, catalog, kind, custom, base, new)
    if top <= before:
        return None
    doc = catalog.get(kind, base.decode("latin-1"), None)
    metas = {f.id: f for f in catalog.fields(kind)}
    mods = _merged([(om, custom, _entry_in(om, custom, base, new)) for om in files])
    written = []
    for rawcode, entry in doc["fields"].items():
        meta = metas.get(rawcode)
        if "values" not in entry or meta is None or meta.repeat <= 0:
            continue
        defined = [level for (rid, level) in mods if rid == rawcode and 1 <= level <= before]
        last = max(defined) if defined else min(before, len(entry["values"]))
        if last < 1:
            continue
        mod = mods.get((rawcode, last))
        if mod is not None:
            vt, value = mod.var_type, mod.value
        else:
            raw = _typed(entry["type"], entry["values"][last - 1])
            if raw is None or raw == "":
                continue
            try:
                vt, value = _convert(meta, raw, path)
            except ToolError:
                continue   # a base value outside the field's own range: leave that field to the caller
        for level in range(before + 1, top + 1):
            if (rawcode, level) not in mods:
                _set(files, kind, custom, base, new, meta, level, vt, value, strings)
        written.append(rawcode)
    if not written:
        return None
    return {"id": (new if custom else base).decode("latin-1"), "levels": f"{before + 1}..{top}",
            "fields": sorted(written)}


def _clear(files, custom: bool, base: bytes, new: bytes, meta, level: int) -> None:
    """Drop the map's own value for a field, so the object uses the base object's again (null, as `reset` does)."""
    rid = meta.id.encode("latin-1")
    for om in files:
        entry = _entry_in(om, custom, base, new)
        entry.mods = [m for m in entry.mods if not (m.id == rid and (level is None or m.level == level))]


def _set_many(files, catalog, kind: str, custom: bool, base: bytes, new: bytes, values, strings, path: str) -> list:
    """Applies one op's field values. Returns what growing a level count (alev, glvl) extended, if anything."""
    if not isinstance(values, dict):
        raise ToolError("bad_op", f"{path}: set must be an object of field: value", hint=_HINT)
    levels_before = _level_count(files, catalog, kind, custom, base, new)
    templates = []
    for key, value in values.items():
        fpath = f"{path}.set.{key}"
        meta = _field(catalog, kind, base.decode("latin-1"), key, fpath)
        if isinstance(value, dict) and "template" in value:
            templates.append((meta, value, fpath))   # rendered last, from the values every other op already wrote
            continue
        if value is None:   # clear the whole field, levels included: the base object's own value applies again
            _clear(files, custom, base, new, meta, None)
            continue
        count = _level_count(files, catalog, kind, custom, base, new)
        for level, v in _level_values(meta, value, fpath, count):
            if v is None:
                _clear(files, custom, base, new, meta, level if meta.repeat > 0 else 0)
                continue
            vt, converted = _convert(meta, v, fpath)
            _set(files, kind, custom, base, new, meta, level, vt, converted, strings)
    grown = []
    if LEVEL_FIELDS.get(kind) in values:
        extended = _extend_levels(files, catalog, kind, custom, base, new, levels_before, strings, path)
        grown = [extended] if extended else []
    for meta, value, fpath in templates:
        _render(files, catalog, kind, custom, base, new, meta, value, fpath, strings)
    return grown


def _render(files, catalog, kind: str, custom: bool, base: bytes, new: bytes, meta, value: dict, path: str,
            strings) -> None:
    """A text field per level from a template: {level} is the level, {<field>} the object's value of that field at
    that level (the map's own, else the base object's), so a tooltip never drifts from the numbers."""
    template = value["template"]
    if set(value) - {"template", "levels"} or not isinstance(template, str):
        raise ToolError("bad_value", f'{path}: {{"template": "text with {{field}} and {{level}}"}}', path=path)
    count = value.get("levels") or _level_count(files, catalog, kind, custom, base, new)
    metas = {f.id: f for f in catalog.fields(kind)}
    mods = _merged([(om, custom, _entry_in(om, custom, base, new)) for om in files])
    base_id = base.decode("latin-1")
    for level in range(1, (count if meta.repeat > 0 else 1) + 1):
        def fill(m, level=level):
            code = m.group(1)
            if code == "level":
                return str(level)
            if code not in metas:
                raise ToolError("bad_value", f"{path}: the template names {code!r}, which is no {kind} field",
                                path=path)
            mod = mods.get((code, level)) or (mods.get((code, 0)) if level == 1 or metas[code].repeat <= 0 else None)
            if mod is not None:
                raw = strings.resolve(mod.value) if isinstance(mod.value, str) else mod.value
            else:
                raw = catalog.value(kind, base_id, metas[code], level)
            return _fmt(raw)
        text = PLACEHOLDER.sub(fill, template)
        vt, converted = _convert(meta, text, path)
        _set(files, kind, custom, base, new, meta, level if meta.repeat > 0 else 0, vt, converted, strings)


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
    created, extended = [], []
    for i, op in enumerate(ops):
        path = f"ops[{i}]"
        try:
            if not isinstance(op, dict):
                raise ToolError("bad_op", f"{path}: each op must be an object", hint=_HINT)
            action = op.get("op")
            extra = set(op) - OP_KEYS.get(action, set(op))
            if extra:   # a misspelt key would otherwise drop the caller's values without a word
                raise ToolError("bad_op", f"{path}: {action} takes no {sorted(extra)}", hint=_HINT)
            if action == "create":
                base = op.get("base")
                copied = [] if base in base_ids else [(om, e) for om, custom, e in _entries(files, base) if custom]
                if not isinstance(base, str) or (base not in base_ids and not copied):
                    raise ToolError("not_found", f"{path}: base {kind} {base!r} does not exist",
                                    hint="data_search finds stock ids, objdata_list the map's custom ones")
                if copied:   # a copy of a custom object, as the editor's copy and paste: its stock base and its mods
                    base = copied[0][1].base_id.decode("latin-1")
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
                    entry = _entry_in(om, True, base_b, new_b)
                    for source in (e for o, e in copied if o is om):
                        entry.mods += [dataclasses.replace(m, value=strings.resolve(m.value)) if m.var_type == STRING
                                       else dataclasses.replace(m) for m in source.mods]
                extended += _set_many(files, catalog, kind, True, base_b, new_b, op.get("set", {}), strings, path)
            elif action == "set":
                custom, base_b, new_b = _locate(files, base_ids, kind, op.get("id"), path)
                for om in files:
                    _entry_in(om, custom, base_b, new_b)
                extended += _set_many(files, catalog, kind, custom, base_b, new_b, op.get("set"), strings, path)
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
        project.write(strings_file(project), wts_after)
        changed = True
    out = {"changed": changed, "created": created, "warnings": []}
    if extended:
        out["extended_levels"] = extended
        out["extended_levels_note"] = ("these objects got more levels than their base object has, so the last value "
                                       "of every per-level field was repeated into the new ranks (what the World "
                                       "Editor does); set the ranks that should differ")
    return out


# ---- diff ------------------------------------------------------------------------------------------------------
def _side(read, kind: str, catalog) -> dict:
    """{object id: {(field, level): value}} of one version of the map, main and skin files merged."""
    ext = _check_kind(kind)
    out: dict[str, dict] = {}
    for prefix in ("war3map", "war3mapSkin"):
        data = read(f"{prefix}.{ext}")
        if data is None:
            continue
        try:
            om = objmods.parse(data, ext in LEVEL_EXTENSIONS)
        except FormatError as e:
            raise ToolError("bad_file", f"{prefix}.{ext}: {e}") from e
        for custom, table in ((False, om.original), (True, om.custom)):
            for entry in table:
                item = out.setdefault(_key(entry, custom), {})
                item["base"] = entry.base_id.decode("latin-1")
                item["custom"] = custom
                for mod in entry.mods:
                    item[(mod.id.decode("latin-1"), mod.level)] = _f32(mod.value) if mod.var_type in (REAL, UNREAL) \
                        else mod.value
    return out


def objdata_diff(project, catalog, kind: str, before) -> dict:
    """What this map's object data of one kind changed against `before(name) -> bytes | None`: objects added or
    deleted, and per object the fields whose value differs, with both values."""
    now, was = _side(lambda n: _maybe(project, n), kind, catalog), _side(before, kind, catalog)
    strings = load_strings(project)
    names = {f.id: f.display_name or f.field for f in catalog.fields(kind)}
    added = sorted(set(now) - set(was))
    removed = sorted(set(was) - set(now))
    changed = []
    for oid in sorted(set(now) & set(was)):
        fields = []
        for key in sorted(set(now[oid]) | set(was[oid]), key=str):
            if key in ("base", "custom") or now[oid].get(key) == was[oid].get(key):
                continue
            rawcode, level = key
            fields.append({"field": rawcode, "name": names.get(rawcode, rawcode),
                           **({"level": level} if level else {}),
                           "before": _resolved(was[oid].get(key), strings),
                           "after": _resolved(now[oid].get(key), strings)})
        if fields:
            changed.append({"id": oid, "base": now[oid].get("base"), "fields": fields})
    return {"kind": kind, "added": [{"id": oid, "base": now[oid].get("base")} for oid in added],
            "removed": [{"id": oid, "base": was[oid].get("base")} for oid in removed], "changed": changed,
            "count": len(added) + len(removed) + sum(len(c["fields"]) for c in changed)}


def _maybe(project, name: str) -> bytes | None:
    try:
        return project.read(name)
    except ToolError as e:
        if e.code != "no_such_file":
            raise
        return None


def _resolved(value, strings: TriggerStrings):
    return strings.resolve(value) if isinstance(value, str) and TRIGSTR.match(value) else value
