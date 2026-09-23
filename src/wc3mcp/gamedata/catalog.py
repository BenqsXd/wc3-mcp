"""Game data lookups: base objects with their editor fields, terrain/sound rows, asset paths."""
import fnmatch
from dataclasses import dataclass
from functools import cached_property

from ..errors import ToolError
from . import natives as natives_module
from .kinds import OBJECT_KINDS, PATH_KINDS, ROW_KINDS
from .profile import parse_profile, split_list, unquote
from .slk import Table, parse_slk
from .triggerdata import KIND_NAMES, TriggerData

TRIGGER_KINDS = ("trigger_function", "trigger_type", "trigger_preset", "native")
# model file field and variation count field of the placeable kinds
MODEL_FIELDS = {"doodad": ("dfil", "dvar"), "destructible": ("bfil", "bvar"), "unit": ("umdl", None)}
TILESET_FIELDS = {"doodad": "dtil", "destructible": "btil"}
ORDER_KIND = "order"
KINDS = tuple(OBJECT_KINDS) + tuple(ROW_KINDS) + tuple(PATH_KINDS) + TRIGGER_KINDS + (ORDER_KIND,)


# the extension object data and scripts name a file by: the game finds the .dds or .mdx next to it
REF_EXTENSION = {"icon": ".blp", "model": ".mdl"}
# ability fields holding an order string, and the GUI preset types that list order strings with their targeting
ORDER_FIELDS = {"aord": "use/turn on", "aoro": "turn on", "aorf": "turn off"}
ORDER_TARGETS = {"unitordernotarg": "immediate", "unitorderptarg": "point", "unitorderutarg": "unit",
                 "unitorderitarg": "item", "unitorderdtarg": "destructible"}
ORDER_NOTE = ("the game accepts only one of data and editor when they differ: Issue*Order returns false for a "
              "rejected string, so a script can try one and fall back to the other")
# order strings the game was seen to accept where data and editor disagree (issued in a probe, GetUnitCurrentOrder)
GAME_ORDERS = {"ANlm": "lavamonster", "AHpx": "summonphoenix", "AUin": "dreadlordinferno"}


COMPACT_NOTE = ("fields are raw code -> value (per-level fields a list), and fields holding nothing are left out; "
                "verbose=true adds each field's name, category, type and, for a map, which levels it modifies")


def _has_value(value) -> bool:
    return any(v is not None for v in value) if isinstance(value, list) else value is not None


def compact(doc: dict) -> dict:
    """An object document without the per-field metadata: raw code -> value (or per-level values), leaving out
    fields that hold nothing. About a tenth of the verbose size; verbose=true names, categorises and types them.
    Documents that carry no field metadata (terrain and sound rows, assets, trigger data) pass through."""
    if not any(isinstance(entry, dict) for entry in doc.get("fields", {}).values()):
        return doc
    fields, modified, refs, unused = {}, [], {}, {}
    for rawcode, entry in doc["fields"].items():
        value = entry["values"] if "values" in entry else entry.get("value")
        if entry.get("modified"):
            modified.append(rawcode)
        if _has_value(value) or entry.get("modified"):
            fields[rawcode] = value
        if entry.get("value_refs") or entry.get("value_ref"):
            refs[rawcode] = entry.get("value_refs") or entry["value_ref"]
        if entry.get("unused_levels"):
            unused[rawcode] = entry["unused_levels"]
    out = {**{k: v for k, v in doc.items() if k != "fields"}, "fields": fields}
    if any("modified" in entry for entry in doc["fields"].values()):   # an open map's object data
        out["modified"] = modified
    for key, value in (("value_refs", refs), ("unused_levels", unused)):
        if value:
            out[key] = value
    return out


def _matcher(query: str):
    """A text query matches as a substring; one with * ? or [ is a glob over the whole text, like the file kinds."""
    q = query.casefold()
    if any(c in q for c in "*?["):
        return lambda text: fnmatch.fnmatchcase(text.casefold(), q)
    return lambda text: q in text.casefold()


def _group_layers(paths: list[str], kind: str) -> list[dict]:
    """One result per file as object data references it (ref: backslashes, .blp icons, .mdl models), with the
    storage layers that hold it; id stays a storage path (the base layer's when it has one)."""
    groups: dict[str, dict] = {}
    for path in paths:
        *mods, rel = path.split(".w3mod:")
        layer = ":".join(mods[1:]) or "base"
        ref = rel.replace("/", "\\")
        if kind in REF_EXTENSION:
            ref = ref.rsplit(".", 1)[0] + REF_EXTENSION[kind]
        group = groups.setdefault(ref.lower(), {"id": path, "ref": ref, "layers": []})
        group["layers"].append(layer)
        if layer == "base":
            group["id"] = path
    return list(groups.values())


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
        self._profiles_lower: dict[str, dict] = {}
        self._fields: dict[str, list[FieldMeta]] = {}
        self._pathing: dict[str, tuple | None] = {}

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
            # the game finds sections whatever their case ([YCgd] holds Ycgd's model); an exact match still wins
            self._profiles_lower[kind] = {k.lower(): v for k, v in reversed(list(merged.items()))}
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

    @cached_property
    def natives(self) -> dict:
        """The script API of this install: name -> natives.Entry from common.j, Blizzard.j and common.ai."""
        sources = {}
        for rel in natives_module.SOURCES:
            data = self._read(rel)
            if data is not None:
                sources[rel.split("/")[-1]] = data.decode("utf-8", "replace")
        return natives_module.parse(sources)

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
        if kind == "native":
            entry = self.natives.get(obj_id)
            if entry is None:
                raise missing
            return {"kind": kind, **entry.to_json()}
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
            section = self.profile(kind).get(obj_id) or self._profiles_lower[kind].get(obj_id.lower(), {})
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
        return [f"{stem}{v}.mdl" for v in (range(count) if variation is None else [variation % count])]

    @cached_property
    def sd(self) -> "Catalog":
        """The data as classic (SD) graphics read it: the World Editor uses it, with other model paths for some types
        and fewer model files."""
        if not self.layer["hd"]:
            return self
        return Catalog(self.storage, self.layer["locale"], self.layer["balance"], hd=False)

    def model_exists(self, path: str, hd: bool = False) -> bool:
        """Whether the game data has a model; by default in classic graphics, which then also has it in HD."""
        stem = path[:-4]
        layer = {**self.layer, "hd": hd and self.layer["hd"]}
        return any(self.storage.resolve(stem + ext, **layer) for ext in (".mdx", ".mdl"))

    def icon_exists(self, path: str) -> bool:
        """Whether the game data has an icon (or any texture object data names) in either graphics mode: object data
        says .blp, and the game loads the .dds beside it in HD."""
        stem = path.replace("/", "\\").rsplit(".", 1)[0] if path.lower().endswith((".blp", ".dds", ".tga")) else path
        return any(self.storage.resolve(stem + ext, **{**self.layer, "hd": hd})
                   for hd in {self.layer["hd"], False} for ext in (".blp", ".dds", ".tga"))

    def missing_models(self, kind: str, obj_id: str, variation: int | None = None) -> tuple[list[str], list[str]] | None:
        """(model paths, the ones the game cannot load in HD or classic graphics) of a base doodad, destructible or
        unit, for every variation or one."""
        found = self.model(kind, obj_id)
        if found is None:
            return None
        paths = self.model_paths(*found, variation)
        missing = [p for p in paths if not self.model_exists(p, hd=True)]
        classic = self.sd.model(kind, obj_id)
        for p in self.sd.model_paths(*classic, variation) if classic else ():
            if p not in missing and not self.sd.model_exists(p):
                missing.append(p)
        return paths, missing

    def variations_ok(self, kind: str, obj_id: str) -> list[int] | None:
        """Variations whose models load in both graphics modes (None: the type has no model)."""
        found = self.model(kind, obj_id)
        if found is None:
            return None
        return [v for v in range(max(found[1], 1)) if not self.missing_models(kind, obj_id, v)[1]]

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
        if kind == "native":
            return natives_module.search(self.natives, query)[offset:offset + limit]
        match = _matcher(query)
        if kind == ORDER_KIND:
            hits = [r for r in self._orders.values() if match(r["id"]) or any(match(a) for a in r["abilities"])]
            return hits[offset:offset + limit]
        if kind in TRIGGER_KINDS:
            hits = [r for r in self._trigger_rows(kind) if match(r["id"]) or match(r["name"])]
            return hits[offset:offset + limit]
        if kind in PATH_KINDS:
            exts, needle = PATH_KINDS[kind]
            if any(c in query for c in "*?[") and ":" not in query:
                query = "*" + query   # storage ids start with their layer (War3.w3mod:...)
            hits = [p for p in self.storage.list(query)
                    if (not exts or p.lower().endswith(exts)) and needle in p.lower()]
            return _group_layers(hits, kind)[offset:offset + limit]
        wanted = self._tileset_letter(tileset) if tileset else None
        out = []
        for obj_id in self.ids(kind):
            if wanted and not {"*", wanted} & set(split_list(self.field(kind, obj_id, TILESET_FIELDS[kind]) or "")):
                continue
            name = self.name(kind, obj_id)
            suffix = self._lookup(kind, obj_id, OBJECT_KINDS[kind].suffix_keys) if kind in OBJECT_KINDS else ""
            if match(obj_id) or match(name) or (suffix and match(suffix)):
                out.append({"id": obj_id, "name": name, "suffix": suffix})
        page = out[offset:offset + limit]
        if kind in TILESET_FIELDS:   # some ids of the data files have no model in the installed game
            for row in page:
                found, ok = self.model(kind, row["id"]), self.variations_ok(kind, row["id"])
                row["model_ok"] = ok is None or len(ok) == max(found[1], 1)
                if ok and not row["model_ok"]:
                    row["variations_ok"] = ok
                path = self.field(kind, row["id"], "dptx" if kind == "doodad" else "bptx") or ""
                blocked = self.pathing_pixels(path)
                row["pathing"], row["blocks"] = path or None, bool(blocked and blocked[2])
        return page

    def pathing_pixels(self, path: str):
        """(width, height, the pixels a unit cannot walk on) of a pathing texture, or None when there is none. Red
        marks unwalkable ground (blue is build-only, green flying); one pixel is one 32-unit cell."""
        key = (path or "").strip()
        if key not in self._pathing:
            self._pathing[key] = None
            if key and key.lower() not in ("none", "_"):
                from ..formats import texture

                full = self.storage.resolve(key.replace("\\", "/"), **self.layer)
                data = self.storage.read(full) if full else None
                if data is not None:
                    image = texture.decode(data, key).convert("RGB")
                    w, h = image.size
                    pixels = image.tobytes()
                    self._pathing[key] = (w, h, frozenset((i % w, i // w) for i in range(w * h)
                                                          if pixels[i * 3] > 127))
        return self._pathing[key]

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
                out.append({"id": obj_id, "name": name, "suffix": "", "tileset": letter, "tileset_name": of,
                            **(self.tile_pathing(obj_id) if kind == "tile" else {})})
        return out[offset:offset + limit]

    @cached_property
    def _order_presets(self) -> dict[str, list[dict]]:
        """Editor order presets by the ability they belong to: display name (and its part after " - ") -> orders."""
        index: dict[str, list[dict]] = {}
        for p in self.trigger_data.presets.values():
            target = ORDER_TARGETS.get(p.type)
            if target is None:
                continue
            entry = {"order": p.code.strip("`'"), "targets": target, "preset": p.name, "name": p.display}
            for key in {p.display.casefold(), p.display.rpartition(" - ")[2].casefold()}:
                rows = index.setdefault(key, [])
                if not any(r["order"] == entry["order"] and r["targets"] == target for r in rows):
                    rows.append(entry)
        return index

    def ability_orders(self, obj_id: str) -> dict:
        """The order strings of one ability: the ability data's own fields and the World Editor's presets for it,
        which disagree for a few abilities (only one of the two works, per ability)."""
        data = {f: v for f in ORDER_FIELDS if (v := self.field("ability", obj_id, f))}
        name = self.name("ability", obj_id)
        # the hero skill preset of this ability carries its id, and names it the way the order presets do
        label = next((p.display for p in self.trigger_data.presets.values()
                      if p.type == "heroskillcode" and p.code.strip("`'") == obj_id), None)
        editor = self._order_presets.get((label or name).casefold()) or self._order_presets.get(name.casefold()) or []
        out = {"data": data, "editor": editor}
        # only the main order is compared: the turn on/off strings of an autocast have no preset of their own
        if data.get("aord") and editor and data["aord"].casefold() not in {e["order"].casefold() for e in editor}:
            out.update(disagree=True, note=ORDER_NOTE)
            if obj_id in GAME_ORDERS:
                out["game"] = GAME_ORDERS[obj_id]
        return out

    @cached_property
    def _orders(self) -> dict[str, dict]:
        """Every order string the data or the editor knows: its targeting (from the editor's presets), the abilities
        whose order fields name it, and whether one of them disagrees with the editor about its own order."""
        out: dict[str, dict] = {}

        def row(order: str) -> dict:
            return out.setdefault(order.casefold(), {"id": order, "targets": set(), "abilities": [], "presets": [],
                                                     "disagree": False})

        for rows in self._order_presets.values():
            for r in rows:
                entry = row(r["order"])
                entry["targets"].add(r["targets"])
                if r["preset"] not in entry["presets"]:
                    entry["presets"].append(r["preset"])
        for obj_id in self.ids("ability"):
            orders = self.ability_orders(obj_id)
            for value in orders["data"].values():
                entry = row(value)
                if obj_id not in entry["abilities"]:
                    entry["abilities"].append(obj_id)
                if orders.get("disagree") and value == orders["data"].get("aord"):
                    entry["disagree"] = True
        from . import orderids

        for entry in out.values():
            entry["targets"] = sorted(entry["targets"])
            # backed: a shipped ability uses it; resolves: what a game run measured OrderId() to answer for it
            entry["backed"] = bool(entry["abilities"])
            entry["resolves"] = orderids.resolves(entry["id"])
            number = orderids.order_id(entry["id"])
            if number is not None:
                entry["order_id"] = number
        return dict(sorted(out.items()))

    def tile_pathing(self, tile: str) -> dict:
        """Whether ground of this tile lets players build, units walk and flyers fly (TerrainArt/Terrain.slk)."""
        row = self._row("tile", tile) or {}
        return {k: row.get(k, "1") != "0" for k in ("buildable", "walkable", "flyable")}

    def get(self, kind: str, obj_id: str, fields: list[str] | None = None) -> dict:
        self._check(kind)
        missing = ToolError("not_found", f"no {kind} with id {obj_id!r}", hint="data_search finds ids")
        if kind in TRIGGER_KINDS:
            return self._trigger_get(kind, obj_id, missing)
        if kind == ORDER_KIND:
            found = self._orders.get(obj_id.casefold())
            if found is None:
                raise missing
            return {"kind": kind, **found}
        if kind in PATH_KINDS:
            if self.storage.norm(obj_id) in self.storage.names():
                return {"kind": kind, "id": obj_id, "local": self.storage.is_local(obj_id)}
            # the way object data names a file (Units\...\X.mdl, ...\BTNX.blp): the game loads the .mdx / .dds
            # beside it, and so does objdata_get's model check - answer the same
            stem = obj_id.replace("/", "\\").rsplit(".", 1)[0] if "." in obj_id.rsplit("\\", 1)[-1] else None
            exts = {"model": (".mdx", ".mdl"), "icon": (".blp", ".dds", ".tga")}.get(kind, ())
            for hd in (True, False) if stem and exts else ():
                for ext in exts:
                    found = self.storage.resolve(stem + ext, **{**self.layer, "hd": hd and self.layer["hd"]})
                    if found:
                        return {"kind": kind, "id": found, "ref": obj_id, "resolved_from": obj_id,
                                "local": self.storage.is_local(found)}
            # a bare name ("BTNChainLightning") or a path with the other extension names one file often enough
            stem = obj_id.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
            hits = self.search(kind, f"*/{stem}.*", limit=20)
            if len(hits) == 1:
                path = hits[0]["id"]
                return {"kind": kind, "id": path, "ref": hits[0].get("ref"), "resolved_from": obj_id,
                        "local": self.storage.is_local(path)}
            raise ToolError("not_found", f"no {kind} {obj_id!r}",
                            hint='the id is a storage path (data_search kind=icon query="*ChainLightning*" finds '
                                 "them); a bare name like BTNChainLightning works when it names one file",
                            candidates=[h["id"] for h in hits[:10]])
        if kind in ROW_KINDS:
            row = self._row(kind, obj_id)
            if row is None:
                raise missing
            wanted = {f.lower() for f in fields} if fields else None
            doc = {"kind": kind, "id": obj_id, "name": self.name(kind, obj_id),
                   "fields": {k: self.westring(v) for k, v in row.items() if wanted is None or k.lower() in wanted}}
            unknown = [f for f in fields if f.lower() not in {k.lower() for k in row}] if fields else []
            if unknown:
                doc["unknown_fields"] = unknown
            return doc
        spec = OBJECT_KINDS[kind]
        if obj_id not in self.table(spec.slks[spec.id_slk]).rows:
            raise missing
        levels = self.levels(kind, obj_id)
        wanted = [f.lower() for f in fields] if fields else None
        matched: set[str] = set()
        out = {}
        for meta in self.fields(kind):
            hits = [] if wanted is None else [w for w in wanted
                                              if w in (meta.id.lower(), meta.field.lower())
                                              or w in meta.display_name.lower()]
            if wanted is not None and not hits:
                continue
            matched.update(hits)   # a field that exists but does not apply to this object is not unknown
            if not self.applies(kind, obj_id, meta):
                continue
            entry = {"field": meta.field, "name": meta.display_name, "category": meta.category, "type": meta.type}
            if meta.repeat > 0:
                entry["values"] = [self.value(kind, obj_id, meta, lv) for lv in range(1, levels + 1)]
            else:
                entry["value"] = self.value(kind, obj_id, meta)
            out[meta.id] = entry
        doc = {"kind": kind, "id": obj_id, "name": self.name(kind, obj_id), "levels": levels, "fields": out}
        unknown = [f for f in fields if f.lower() not in matched] if fields else []
        if unknown:
            doc["unknown_fields"] = unknown
        if kind == "ability":
            doc["orders"] = self.ability_orders(obj_id)
        models = self.missing_models(kind, obj_id) if kind in MODEL_FIELDS else None
        if models is not None:
            doc["model"] = {"files": models[0], "missing": models[1]}
        return doc
