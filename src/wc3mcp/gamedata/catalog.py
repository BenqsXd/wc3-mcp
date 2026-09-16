"""Game data lookups: base objects with their editor fields, terrain/sound rows, asset paths."""
from dataclasses import dataclass
from functools import cached_property

from ..errors import ToolError
from .kinds import OBJECT_KINDS, PATH_KINDS, ROW_KINDS
from .profile import parse_profile, split_list, unquote
from .slk import Table, parse_slk
from .triggerdata import KIND_NAMES, TriggerData

TRIGGER_KINDS = ("trigger_function", "trigger_type", "trigger_preset")
# model file field and variation count field of the placeable kinds
MODEL_FIELDS = {"doodad": ("dfil", "dvar"), "destructible": ("bfil", "bvar"), "unit": ("umdl", None)}
TILESET_FIELDS = {"doodad": "dtil", "destructible": "btil"}
KINDS = tuple(OBJECT_KINDS) + tuple(ROW_KINDS) + tuple(PATH_KINDS) + TRIGGER_KINDS


def _int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _codes(value: str | None) -> tuple[str, ...]:
    return tuple(c for c in (value or "").split(",") if c)


@dataclass(frozen=True)
class FieldMeta:
    id: str
    field: str
    slk: str
    index: int
    repeat: int
    data: int
    category: str
    display_name: str
    type: str
    min: str
    max: str
    use_specific: tuple[str, ...]
    not_specific: tuple[str, ...]
    netsafe: str = "0"  # "1"/"11": cosmetic field that the 2.x editor stores in war3mapSkin.* files

    def column(self, level: int) -> str:
        """Data column / profile key: Data + letter for ability data fields, + level for per-level SLK columns."""
        name = self.field + (chr(ord("A") + self.data - 1) if self.data > 0 else "")
        return name + str(level) if self.repeat > 0 and self.slk != "Profile" else name


class Catalog:
    """ponytail: parsed tables are cached in memory per process; add a per-build disk cache if startup gets slow."""

    def __init__(self, storage, locale: str = "enUS", balance: str | None = "Custom_V1", hd: bool = True):
        self.storage = storage
        self.layer = {"locale": locale, "balance": balance, "hd": hd}
        self.variant = "hd" if hd else "sd"
        self._tables: dict[str, Table] = {}
        self._profiles: dict[str, dict] = {}
        self._fields: dict[str, list[FieldMeta]] = {}

    # raw data
    def _read(self, relpath: str) -> bytes | None:
        full = self.storage.resolve(relpath, **self.layer)
        return None if full is None else self.storage.read(full)

    def table(self, relpath: str) -> Table:
        if relpath not in self._tables:
            data = self._read(relpath)
            self._tables[relpath] = parse_slk(data) if data else Table([], {})
        return self._tables[relpath]

    def profile(self, kind: str) -> dict:
        if kind not in self._profiles:
            merged = {}
            for rel in OBJECT_KINDS[kind].profiles:
                data = self._read(rel)
                if data:
                    parse_profile(data, into=merged)
            self._profiles[kind] = merged
        return self._profiles[kind]

    @cached_property
    def _westrings(self) -> dict[str, str]:
        merged = {}
        for rel in ("UI/WorldEditStrings.txt", "UI/WorldEditGameStrings.txt"):
            data = self._read(rel)
            if data:
                parse_profile(data, into=merged)
        return {k: unquote(v) for section in merged.values() for k, v in section.items()}

    def westring(self, value: str) -> str:
        return self._westrings.get(value.lower(), value) if value.startswith("WESTRING_") else value

    @cached_property
    def trigger_data(self) -> TriggerData:
        return TriggerData.parse(self._read("UI/TriggerData.txt") or b"", self.westring)

    def _trigger_rows(self, kind: str) -> list[dict]:
        td = self.trigger_data
        if kind == "trigger_function":
            return [{"id": f.name, "name": f.display, "suffix": KIND_NAMES[f.kind]}
                    for table in td.functions for f in table.values()]
        if kind == "trigger_type":
            return [{"id": t.name, "name": t.display, "suffix": "" if t.base == t.name else t.base}
                    for t in td.types.values()]
        return [{"id": p.name, "name": p.display, "suffix": p.type} for p in td.presets.values()]

    def _trigger_get(self, kind: str, obj_id: str, missing: ToolError) -> dict:
        td = self.trigger_data
        if kind == "trigger_function":
            found = [table[obj_id] for table in td.functions if obj_id in table]
            if not found:
                raise missing
            return {"kind": kind, "id": obj_id, "name": found[0].display, "variants": [
                {"kind": KIND_NAMES[f.kind], "args": list(f.args), "returns": f.returns, "text": "".join(f.layout),
                 "defaults": list(f.defaults), "category": td.categories.get(f.category, (f.category,))[0]}
                for f in found]}
        if kind == "trigger_type":
            t = td.types.get(obj_id)
            if t is None:
                raise missing
            return {"kind": kind, "id": obj_id, "name": t.display, "base": t.base, "global": t.global_ok,
                    "comparable": t.comparable, "presets": [p.name for p in td.presets.values() if p.type == obj_id]}
        p = td.presets.get(obj_id)
        if p is None:
            raise missing
        return {"kind": kind, "id": obj_id, "name": p.display, "type": p.type, "code": p.code}

    # metadata
    def _check(self, kind: str) -> None:
        if kind not in KINDS:
            raise ToolError("bad_kind", f"unknown kind {kind!r}", hint="one of: " + ", ".join(KINDS))

    def fields(self, kind: str) -> list[FieldMeta]:
        self._check(kind)
        spec = OBJECT_KINDS[kind]
        if kind not in self._fields:
            out = []
            for r in self.table(spec.meta).rows.values():
                slk = r.get("slk", "")
                if slk != "Profile" and slk not in spec.slks:
                    continue
                if spec.use_flags and not any(r.get(flag) == "1" for flag in spec.use_flags):
                    continue
                out.append(FieldMeta(
                    id=r["ID"], field=r.get("field", ""), slk=slk, index=_int(r.get("index"), -1),
                    repeat=_int(r.get("repeat"), 0), data=_int(r.get("data"), 0), category=r.get("category", ""),
                    display_name=self.westring(r.get("displayName", "")), type=r.get("type", ""),
                    min=r.get("minVal", ""), max=r.get("maxVal", ""),
                    use_specific=_codes(r.get("useSpecific")), not_specific=_codes(r.get("notSpecific")),
                    netsafe=r.get("netsafe") or "0"))
            self._fields[kind] = out
        return self._fields[kind]

    def field(self, kind: str, obj_id: str, field_id: str) -> str | None:
        """One base value by field raw code (first level)."""
        meta = next((m for m in self.fields(kind) if m.id == field_id), None)
        return None if meta is None else self.value(kind, obj_id, meta)

    def ids(self, kind: str) -> list[str]:
        if kind in OBJECT_KINDS:
            spec = OBJECT_KINDS[kind]
            return list(self.table(spec.slks[spec.id_slk]).rows)
        return [k for rel in ROW_KINDS[kind].slks for k in self.table(rel).rows]

    def levels(self, kind: str, obj_id: str) -> int:
        spec = OBJECT_KINDS[kind]
        if spec.level_column is None:
            return 1
        row = self.table(spec.slks[spec.id_slk]).rows.get(obj_id, {})
        return max(1, _int(row.get(spec.level_column), 1))

    # values
    def _raw(self, kind: str, obj_id: str, source: str, key: str) -> str | None:
        if source == "Profile":
            section = self.profile(kind).get(obj_id, {})
            k = key.lower()
            return section.get(f"{k}:{self.variant}", section.get(k))
        row = self.table(OBJECT_KINDS[kind].slks[source]).rows.get(obj_id)
        return None if row is None else row.get(key)

    def value(self, kind: str, obj_id: str, meta: FieldMeta, level: int = 1) -> str | None:
        raw = self._raw(kind, obj_id, meta.slk, meta.column(level))
        if raw is None or meta.slk != "Profile":
            return raw
        if meta.repeat > 0:  # per-level comma list; missing levels reuse the last entry
            parts = split_list(raw)
            return parts[min(level, len(parts)) - 1]
        if meta.index >= 0:
            parts = split_list(raw)
            return parts[meta.index] if meta.index < len(parts) else None
        return unquote(raw)

    def applies(self, kind: str, obj_id: str, meta: FieldMeta) -> bool:
        if kind != "ability" or not (meta.use_specific or meta.not_specific):
            return True
        code = self.table(OBJECT_KINDS["ability"].slks["AbilityData"]).rows.get(obj_id, {}).get("code", obj_id)
        return (not meta.use_specific or code in meta.use_specific) and code not in meta.not_specific

    def _lookup(self, kind: str, obj_id: str, keys: tuple[str, ...]) -> str:
        for spec_key in keys:
            source, key = spec_key.split(":", 1)
            raw = self._raw(kind, obj_id, "Profile" if source == "profile" else OBJECT_KINDS[kind].id_slk, key)
            if raw:
                return self.westring(split_list(raw)[0])
        return ""

    def _row(self, kind: str, obj_id: str) -> dict | None:
        for rel in ROW_KINDS[kind].slks:
            row = self.table(rel).rows.get(obj_id)
            if row is not None:
                return row
        return None

    # public queries
    def name(self, kind: str, obj_id: str) -> str:
        self._check(kind)
        if kind in OBJECT_KINDS:
            return self._lookup(kind, obj_id, OBJECT_KINDS[kind].name_keys)
        if kind in ROW_KINDS:
            row, col = self._row(kind, obj_id), ROW_KINDS[kind].name_column
            return self.westring(row[col]) if row and col and row.get(col) else obj_id
        return obj_id

    def tilesets(self) -> dict[str, str]:
        """Tileset letter -> display name, from UI/WorldEditData.txt [TileSets] (tile ids start with the letter,
        cliff ids carry it second)."""
        if getattr(self, "_tilesets", None) is None:
            out, inside = {}, False
            for line in (self._read("UI/WorldEditData.txt") or b"").decode("utf-8", "replace").splitlines():
                line = line.strip()
                if line.startswith("["):
                    inside = line.lower() == "[tilesets]"
                elif inside and "=" in line and not line.startswith("//"):
                    letter, _, value = line.partition("=")
                    if len(letter) == 1:
                        out[letter] = self.westring(value.split(",")[0])
            self._tilesets = out
        return self._tilesets

    def _tileset_letter(self, tileset: str) -> str:
        names = self.tilesets()
        wanted = tileset if tileset in names else next(
            (letter for letter, name in names.items() if name.casefold() == tileset.casefold()), None)
        if wanted is None:
            raise ToolError("not_found", f"no tileset {tileset!r}",
                            hint="a tileset letter or name: " + ", ".join(f"{k} {v}" for k, v in names.items()))
        return wanted

    # models
    def model(self, kind: str, obj_id: str) -> tuple[str, int] | None:
        """(model file, variation count) of a doodad, destructible or unit in the base data."""
        file_field, count_field = MODEL_FIELDS[kind]
        file = self.field(kind, obj_id, file_field)
        return (file, _int(self.field(kind, obj_id, count_field), 1) if count_field else 1) if file else None

    @staticmethod
    def model_paths(file: str, count: int, variation: int | None = None) -> list[str]:
        """The model files the editor and the game load: file.mdl, or file<variation>.mdl when there are several."""
        stem = file[:-4] if file.lower().endswith((".mdl", ".mdx")) else file
        if count <= 1:
            return [stem + ".mdl"]
        return [f"{stem}{v}.mdl" for v in (range(count) if variation is None else [variation])]

    def model_exists(self, path: str) -> bool:
        stem = path[:-4]
        return any(self.storage.resolve(stem + ext, **self.layer) for ext in (".mdx", ".mdl"))

    def missing_models(self, kind: str, obj_id: str) -> tuple[list[str], list[str]] | None:
        """(model paths, the ones the game data does not have) for a base doodad, destructible or unit."""
        found = self.model(kind, obj_id)
        if found is None:
            return None
        paths = self.model_paths(*found)
        return paths, [p for p in paths if not self.model_exists(p)]

    def tileset_of(self, kind: str, obj_id: str) -> str | None:
        """The tileset letter a tile or cliff id belongs to."""
        if kind == "tile" and len(obj_id) == 4:
            return obj_id[0]
        return obj_id[1] if kind == "cliff" and len(obj_id) == 4 else None

    def search(self, kind: str, query: str = "", limit: int = 50, offset: int = 0, tileset: str | None = None) -> list[dict]:
        self._check(kind)
        if tileset and kind not in ("tile", "cliff", *TILESET_FIELDS):
            raise ToolError("bad_value", "tileset filters tiles, cliffs, doodads and destructibles only", path="tileset")
        if kind in ("tile", "cliff"):
            return self._search_terrain(kind, query, limit, offset, tileset)
        if kind in TRIGGER_KINDS:
            q = query.casefold()
            hits = [r for r in self._trigger_rows(kind) if q in r["id"].casefold() or q in r["name"].casefold()]
            return hits[offset:offset + limit]
        if kind in PATH_KINDS:
            exts, needle = PATH_KINDS[kind]
            hits = [p for p in self.storage.list(query)
                    if (not exts or p.lower().endswith(exts)) and needle in p.lower()]
            return [{"id": p} for p in hits[offset:offset + limit]]
        wanted = self._tileset_letter(tileset) if tileset else None
        q, out = query.casefold(), []
        for obj_id in self.ids(kind):
            if wanted and not {"*", wanted} & set(split_list(self.field(kind, obj_id, TILESET_FIELDS[kind]) or "")):
                continue
            name = self.name(kind, obj_id)
            suffix = self._lookup(kind, obj_id, OBJECT_KINDS[kind].suffix_keys) if kind in OBJECT_KINDS else ""
            if q in obj_id.casefold() or q in name.casefold() or q in suffix.casefold():
                out.append({"id": obj_id, "name": name, "suffix": suffix})
        page = out[offset:offset + limit]
        if kind in TILESET_FIELDS:   # some ids of the data files have no model in the installed game
            for row in page:
                row["model_ok"] = not (self.missing_models(kind, row["id"]) or ([], []))[1]
        return page

    def _search_terrain(self, kind: str, query: str, limit: int, offset: int, tileset: str | None) -> list[dict]:
        """Tiles and cliffs carry their tileset, and can be filtered and searched by its letter or display name."""
        names = self.tilesets()
        wanted = self._tileset_letter(tileset) if tileset else None
        q, out = query.casefold(), []
        for obj_id in self.ids(kind):
            letter = self.tileset_of(kind, obj_id)
            if wanted and letter != wanted:
                continue
            name, of = self.name(kind, obj_id), names.get(letter, "")
            if q in obj_id.casefold() or q in name.casefold() or q in of.casefold():
                out.append({"id": obj_id, "name": name, "suffix": "", "tileset": letter, "tileset_name": of})
        return out[offset:offset + limit]

    def get(self, kind: str, obj_id: str, fields: list[str] | None = None) -> dict:
        self._check(kind)
        missing = ToolError("not_found", f"no {kind} with id {obj_id!r}", hint="data_search finds ids")
        if kind in TRIGGER_KINDS:
            return self._trigger_get(kind, obj_id, missing)
        if kind in PATH_KINDS:
            if self.storage.norm(obj_id) not in self.storage.names():
                raise missing
            return {"kind": kind, "id": obj_id, "local": self.storage.is_local(obj_id)}
        if kind in ROW_KINDS:
            row = self._row(kind, obj_id)
            if row is None:
                raise missing
            return {"kind": kind, "id": obj_id, "name": self.name(kind, obj_id),
                    "fields": {k: self.westring(v) for k, v in row.items()}}
        spec = OBJECT_KINDS[kind]
        if obj_id not in self.table(spec.slks[spec.id_slk]).rows:
            raise missing
        levels = self.levels(kind, obj_id)
        wanted = [f.lower() for f in fields] if fields else None
        out = {}
        for meta in self.fields(kind):
            if wanted is not None and not any(w in (meta.id.lower(), meta.field.lower()) or w in meta.display_name.lower()
                                              for w in wanted):
                continue
            if not self.applies(kind, obj_id, meta):
                continue
            entry = {"field": meta.field, "name": meta.display_name, "category": meta.category, "type": meta.type}
            if meta.repeat > 0:
                entry["values"] = [self.value(kind, obj_id, meta, lv) for lv in range(1, levels + 1)]
            else:
                entry["value"] = self.value(kind, obj_id, meta)
            out[meta.id] = entry
        doc = {"kind": kind, "id": obj_id, "name": self.name(kind, obj_id), "levels": levels, "fields": out}
        models = self.missing_models(kind, obj_id) if kind in MODEL_FIELDS else None
        if models is not None:
            doc["model"] = {"files": models[0], "missing": models[1]}
        return doc
