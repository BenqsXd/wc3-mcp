"""Placed units, items and start locations (war3mapUnits.doo) and doodads and destructibles (war3map.doo) as JSON
with all-or-nothing add/set/move/delete edits. Refs are "<kind>:<editor id>", angles degrees, positions world units."""
import math
import re

from ..errors import ToolError
from ..formats import doo, unitsdoo, w3e, w3i, w3r
from ..formats.binary import FormatError
from .elements import _bad, _bool, _int, _num, _out
from .objdata import objdata_list
from .triggers import SCRIPT_WARNING, _load, _read, script_users

KINDS = ("unit", "item", "start_location", "doodad", "destructible")
UNITS_FILE, DOODADS_FILE = "war3mapUnits.doo", "war3map.doo"
RANDOM_TYPES = {"uDNR": ("unit", "Random Unit"), "bDNR": ("unit", "Random Building"), "iDNR": ("item", "Random Item")}
RANDOM_ITEM = re.compile(r"^Y[Yi-o]I[0-9/]$")  # random item of a class (Y any, i permanent, ...) and level
NO_ID = b"\0\0\0\0"
NEUTRAL_PASSIVE = 27
LEVEL_1 = b"\x01\x00\x00\x00"  # random flag 0 data the editor writes for every unit and item: level 1, class 0
SCRIPT_PREFIX = {"unit": "gg_unit_", "item": "gg_item_", "destructible": "gg_dest_"}
COMMON = {"type", "x", "y", "angle", "scale", "variation", "skin"}
FIELDS = {
    "unit": COMMON | {"owner", "life", "mana", "gold", "acquisition", "hero", "inventory", "abilities", "drops",
                      "random", "color", "waygate"},
    "item": COMMON | {"random"},
    "start_location": {"x", "y", "owner"},
    "doodad": COMMON | {"z", "flags"},
    "destructible": COMMON | {"z", "flags", "life", "drops"},
}
DERIVED_WARNING = ("war3map.wpm (pathing), war3map.shd (shadows) and war3map.mmp (minimap icons) are recomputed by "
                   "the World Editor only: editor_map open + save refreshes them")
_HINT = ('ops: {"op": "add", "kind": "unit", "type": "hfoo", "x": 0, "y": 0, "owner": 0}, {"op": "set", "ref": '
         '"unit:12", "life": 50}, {"op": "move", "ref": "doodad:3", "x": 128, "y": -64}, {"op": "delete", "ref": '
         '"item:7"}; placed_list shows refs and fields')


def _id(raw: bytes) -> str:
    return raw.decode("latin-1")


def _rawcode(v, path: str) -> bytes:
    if not isinstance(v, str) or len(v) != 4 or not v.isascii():
        raise _bad(path, "expected a 4-character id")
    return v.encode("latin-1")


def _parse(project, name: str, codec):
    data = _read(project, name)
    try:
        return (codec.parse(data) if data is not None else None), data
    except FormatError as e:
        raise ToolError("bad_file", f"{name}: {e}", hint="map_file_write can replace a damaged file") from e


class _Map:
    def __init__(self, project, catalog):
        self.project, self.catalog = project, catalog
        try:
            self.terrain = w3e.parse(_read(project, "war3map.w3e") or b"")
        except FormatError:
            self.terrain = None
        try:
            self.info = w3i.parse(_read(project, "war3map.w3i") or b"")
        except FormatError:
            self.info = None
        version = (13, 11) if self.terrain and self.terrain.version >= 12 else (8, 11)
        self.units, self.units_before = _parse(project, UNITS_FILE, unitsdoo)
        self.doodads, self.doodads_before = _parse(project, DOODADS_FILE, doo)
        self.units = self.units or unitsdoo.UnitFile(*version)
        self.doodads = self.doodads or doo.DoodadFile(*version)
        self._ids: dict[str, set[str]] = {}
        self._names: dict[str, dict[str, str]] = {}

    # ---- catalog and map object data
    def _objects(self, kind: str) -> None:
        if kind not in self._ids:
            mods = objdata_list(self.project, self.catalog, kind)["objects"]
            self._names[kind] = {o["id"]: o["name"] for o in mods}
            self._ids[kind] = set(self.catalog.ids(kind)) | {o["id"] for o in mods if o["custom"]}

    def ids(self, kind: str) -> set[str]:
        self._objects(kind)
        return self._ids[kind]

    def name(self, kind: str, type_id: str) -> str:
        if type_id == "sloc":
            return "Start Location"
        if type_id in RANDOM_TYPES:
            return RANDOM_TYPES[type_id][1]
        catalog_kind = "item" if kind == "item" else kind
        self._objects(catalog_kind)
        return self._names[catalog_kind].get(type_id) or self.catalog.name(catalog_kind, type_id)

    def kind_of(self, o) -> str:
        t = _id(o.id)
        if isinstance(o, unitsdoo.Unit):
            if t == "sloc":
                return "start_location"
            return "item" if RANDOM_TYPES.get(t, ("",))[0] == "item" or t in self.ids("item") else "unit"
        return "destructible" if t in self.ids("destructible") else "doodad"

    # ---- geometry
    def playable(self) -> list[float] | None:
        t, i = self.terrain, self.info
        if t is None or i is None:
            return None
        c = i.camera_complements
        return [t.offset_x + c[0] * 128, t.offset_y + c[2] * 128, t.offset_x + (t.width - 1 - c[1]) * 128,
                t.offset_y + (t.height - 1 - c[3]) * 128]

    def whole(self) -> list[float] | None:
        t = self.terrain
        return None if t is None else [t.offset_x, t.offset_y, t.offset_x + (t.width - 1) * 128,
                                       t.offset_y + (t.height - 1) * 128]

    def ground(self, x: float, y: float) -> float:
        return w3e.ground_height(self.terrain, x, y) if self.terrain else 0.0

    # ---- JSON
    def regions(self) -> list[w3r.Region]:
        rf, _ = _parse(self.project, "war3map.w3r", w3r)
        return rf.regions if rf else []

    def to_json(self, kind: str, o, region_names: dict[int, str]) -> dict:
        t = _id(o.id)
        doc = {"ref": f"{kind}:{o.editor_id}", "kind": kind, "type": t, "name": self.name(kind, t),
               "x": _out(o.x), "y": _out(o.y), "z": _out(o.z)}
        if kind == "start_location":
            doc["owner"] = o.owner
            return doc
        doc.update({"angle": _out(math.degrees(o.angle) % 360), "scale": [_out(s) for s in o.scale],
                    "variation": o.variation, "skin": _id(o.skin)})
        if kind in SCRIPT_PREFIX:
            doc["script_name"] = f"{SCRIPT_PREFIX[kind]}{t}_{o.editor_id:04d}"
        if kind in ("doodad", "destructible"):
            doc["flags"] = o.flags
        if kind == "destructible":
            doc["life"] = o.life
        if kind == "unit":
            doc.update({"owner": o.owner, "life": None if o.hp < 0 else o.hp, "mana": None if o.mp < 0 else o.mp,
                        "gold": o.gold, "acquisition": {-1.0: "normal", -2.0: "camp"}.get(o.target_acquisition,
                                                                                         _out(o.target_acquisition))})
            if t[0].isupper() and t not in RANDOM_TYPES:
                doc["hero"] = {"level": o.hero_level, "strength": o.strength, "agility": o.agility,
                               "intelligence": o.intelligence}
            doc["inventory"] = [{"slot": slot, "item": _id(item)} for slot, item in o.inventory]
            doc["abilities"] = [{"id": _id(a), "autocast": bool(auto), "level": lv} for a, auto, lv in o.abilities]
            doc["color"] = None if o.color < 0 else o.color
            doc["waygate"] = None if o.waygate < 0 else region_names.get(o.waygate, o.waygate)
        if kind in ("unit", "destructible"):
            doc["drops"] = None if o.item_table < 0 and not o.item_sets else {
                "table": None if o.item_table < 0 else o.item_table,
                "sets": [[{"item": None if i == NO_ID else _id(i), "chance": c} for i, c in s] for s in o.item_sets]}
        if t in RANDOM_TYPES:
            doc["random"] = _random_json(o)
        return doc

    def placed(self):
        for o in self.units.units:
            yield self.kind_of(o), o
        for o in self.doodads.doodads:
            yield self.kind_of(o), o


def _random_json(u: unitsdoo.Unit) -> dict:
    if u.random_flag == 0:
        return {"level": int.from_bytes(u.random_data[:3], "little", signed=True), "item_class": u.random_data[3]}
    if u.random_flag == 1:
        return {"group": int.from_bytes(u.random_data[:4], "little", signed=True),
                "position": int.from_bytes(u.random_data[4:], "little", signed=True)}
    if u.random_flag == 2:
        return {"units": [{"type": _id(i), "chance": c} for i, c in u.random_units]}
    return {"flag": u.random_flag}


def placed_list(project, catalog, kind: str | None = None, area: list | None = None, owner: int | None = None,
                type_id: str | None = None, limit: int = 200, offset: int = 0) -> dict:
    if kind is not None and kind not in KINDS:
        raise ToolError("bad_kind", f"unknown placed kind {kind!r}", hint="one of: " + ", ".join(KINDS))
    if area is not None:
        if not isinstance(area, list) or len(area) != 4:
            raise _bad("area", "expected [left, bottom, right, top]")
        area = [_num(v, f"area[{i}]") for i, v in enumerate(area)]
    limit, offset = _int(limit, "limit", 1, 5000), _int(offset, "offset", 0)
    m = _Map(project, catalog)
    hits = [(k, o) for k, o in m.placed() if (kind is None or k == kind)
            and (area is None or (area[0] <= o.x <= area[2] and area[1] <= o.y <= area[3]))
            and (owner is None or (isinstance(o, unitsdoo.Unit) and k != "item" and o.owner == owner))
            and (type_id is None or _id(o.id) == type_id)]
    names = {g.index: g.name for g in m.regions()}
    return {"total": len(hits), "bounds": {"playable": m.playable(), "map": m.whole()},
            "items": [m.to_json(k, o, names) for k, o in hits[offset:offset + limit]]}


# ---- edits -----------------------------------------------------------------------------------------------------
class _Edit(_Map):
    def __init__(self, project, catalog):
        super().__init__(project, catalog)
        self.region_list = None
        self.created: list[str] = []
        self.warnings: list[str] = []

    def _find(self, ref, path: str):
        if not isinstance(ref, str) or ":" not in ref:
            raise _bad(path, 'expected a ref such as "unit:12" (placed_list shows them)')
        kind, _, number = ref.partition(":")
        if kind not in KINDS or not number.lstrip("-").isdigit():
            raise _bad(path, f"bad ref {ref!r}; kinds: {', '.join(KINDS)}")
        pool = self.units.units if kind in ("unit", "item", "start_location") else self.doodads.doodads
        found = [o for o in pool if o.editor_id == int(number) and self.kind_of(o) == kind]
        if not found:
            raise ToolError("not_found", f"{path}: no {kind} with ref {ref!r}", hint="placed_list lists refs")
        if len(found) > 1:
            raise ToolError("ambiguous", f"{path}: {len(found)} objects share the ref {ref!r}",
                            hint="the map has duplicate editor ids; open and save it in the World Editor first")
        return kind, found[0]

    def _type(self, kind: str, value, path: str) -> bytes:
        raw = _rawcode(value, path)
        t = _id(raw)
        if RANDOM_TYPES.get(t, ("",))[0] == kind or t in self.ids(kind):
            return raw
        raise _bad(path, f"no {kind} type {t!r} in the game data or this map's object data "
                         f"(data_search kind={kind} / objdata_list)")

    def _position(self, kind: str, o, fields: dict, path: str) -> None:
        if "x" not in fields and "y" not in fields:
            return
        x = _num(fields.get("x", o.x), f"{path}.x")
        y = _num(fields.get("y", o.y), f"{path}.y")
        bounds = self.playable() if kind in ("unit", "item", "start_location") else self.whole()
        if bounds and not (bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3]):
            area = "playable area" if kind in ("unit", "item", "start_location") else "map"
            raise _bad(path, f"({x}, {y}) is outside the {area} {bounds}")
        o.x, o.y = x, y
        if "z" not in fields:
            o.z = self.ground(x, y)

    def _region_index(self, name, path: str) -> int:
        if name is None:
            return -1
        if self.region_list is None:
            self.region_list = self.regions()
        found = [g.index for g in self.region_list if g.name == name]
        if not found:
            raise _bad(path, f"no region named {name!r} (elements_list kind=region)")
        return found[0]

    def _ability(self, a, path: str) -> tuple[bytes, int, int]:
        if not isinstance(a, dict) or not {"id"} <= set(a) <= {"id", "autocast", "level"}:
            raise _bad(path, "expected {id, autocast?, level?}")
        raw = _rawcode(a["id"], f"{path}.id")
        if _id(raw) not in self.ids("ability"):
            raise _bad(f"{path}.id", f"no ability {_id(raw)!r} (data_search kind=ability)")
        return raw, int(_bool(a.get("autocast", False), f"{path}.autocast")), _int(a.get("level", 0), f"{path}.level", 0)

    def _drop_item(self, v, path: str) -> bytes:
        if v is None:
            return NO_ID
        raw = _rawcode(v, path)
        if _id(raw) in self.ids("item") or RANDOM_ITEM.match(_id(raw)):
            return raw
        raise _bad(path, f"no item {_id(raw)!r} (data_search kind=item; YiI1-style ids pick a random item of a "
                         "class and level)")

    def _drops(self, o, v, path: str) -> None:
        if v is None:
            o.item_table, o.item_sets = -1, []
            return
        if not isinstance(v, dict) or not set(v) <= {"table", "sets"}:
            raise _bad(path, "expected {table: id|null, sets: [[{item, chance}]]} or null")
        if "table" in v:
            table = v["table"]
            if table is not None:
                tables = [t.id for t in self.info.random_item_tables] if self.info else []
                if _int(table, f"{path}.table", 0) not in tables:
                    raise _bad(f"{path}.table", f"the map has no random item table {table} (info_get lists them)")
            if isinstance(o, unitsdoo.Unit) and self.units.subversion < 11 and table is not None:
                raise _bad(f"{path}.table", "this map's unit file (subversion 9) cannot store item tables")
            o.item_table = -1 if table is None else table
        if "sets" in v:
            sets = v["sets"]
            if not isinstance(sets, list) or not all(isinstance(s, list) for s in sets):
                raise _bad(f"{path}.sets", "expected a list of item sets, each a list of {item, chance}")
            out = []
            for i, s in enumerate(sets):
                entries = []
                for j, e in enumerate(s):
                    epath = f"{path}.sets[{i}][{j}]"
                    if not isinstance(e, dict) or set(e) != {"item", "chance"}:
                        raise _bad(epath, "expected {item, chance}")
                    entries.append((self._drop_item(e["item"], f"{epath}.item"), _int(e["chance"], f"{epath}.chance", 0, 100)))
                out.append(entries)
            o.item_sets = out

    def _random(self, o: unitsdoo.Unit, v, path: str) -> None:
        if not isinstance(v, dict):
            raise _bad(path, "expected {level, item_class}, {group, position} or {units: [{type, chance}]}")
        keys = set(v)
        if keys <= {"level", "item_class"} and keys:
            level = _int(v.get("level", 1), f"{path}.level", -1, 2 ** 23 - 1)
            o.random_flag, o.random_units = 0, []
            o.random_data = level.to_bytes(3, "little", signed=True) + bytes([_int(v.get("item_class", 0),
                                                                                  f"{path}.item_class", 0, 255)])
        elif keys == {"group", "position"}:
            tables = {t.id: t for t in self.info.random_unit_tables} if self.info else {}
            group = _int(v["group"], f"{path}.group")
            if group not in tables:
                raise _bad(f"{path}.group", f"the map has no random unit group {group} (info_get lists them)")
            position = _int(v["position"], f"{path}.position", 0, len(tables[group].positions) - 1)
            o.random_flag, o.random_units = 1, []
            o.random_data = group.to_bytes(4, "little", signed=True) + position.to_bytes(4, "little", signed=True)
        elif keys == {"units"} and isinstance(v["units"], list):
            units = []
            for i, e in enumerate(v["units"]):
                epath = f"{path}.units[{i}]"
                if not isinstance(e, dict) or set(e) != {"type", "chance"}:
                    raise _bad(epath, "expected {type, chance}")
                units.append((self._type("unit", e["type"], f"{epath}.type"), _int(e["chance"], f"{epath}.chance", 0, 100)))
            o.random_flag, o.random_data, o.random_units = 2, b"", units
        else:
            raise _bad(path, "expected {level, item_class}, {group, position} or {units: [{type, chance}]}")

    def _apply(self, kind: str, o, fields: dict, path: str) -> None:
        extra = set(fields) - FIELDS[kind]
        if extra:
            raise ToolError("bad_op", f"{path}: {kind} has no fields {sorted(extra)}", hint=_HINT)
        if "type" in fields:
            raw = self._type(kind, fields["type"], f"{path}.type")
            if o.skin == o.id:
                o.skin = raw
            o.id = raw
        if "skin" in fields:
            o.skin = self._type(kind, fields["skin"], f"{path}.skin")
        if "z" in fields:
            o.z = _num(fields["z"], f"{path}.z")
        self._position(kind, o, fields, path)
        if "angle" in fields:
            o.angle = math.radians(_num(fields["angle"], f"{path}.angle") % 360)
        if "scale" in fields:
            v = fields["scale"]
            scale = [v] * 3 if not isinstance(v, list) else v
            if len(scale) != 3:
                raise _bad(f"{path}.scale", "expected a number or [x, y, z]")
            o.scale = [_num(s, f"{path}.scale") for s in scale]
            if kind == "destructible" and len(set(o.scale)) > 1:
                raise _bad(f"{path}.scale", "destructibles scale uniformly")
        if "variation" in fields:
            o.variation = _int(fields["variation"], f"{path}.variation", 0)
        if "flags" in fields:
            o.flags = _int(fields["flags"], f"{path}.flags", 0, 255)
        if "owner" in fields:
            o.owner = _int(fields["owner"], f"{path}.owner", 0, 23 if kind == "start_location" else 27)
        if "life" in fields:
            v = fields["life"]
            if kind == "destructible":
                o.life = _int(v, f"{path}.life", 0, 100)
            else:
                o.hp = -1 if v is None else _int(v, f"{path}.life", 1, 100)
        if "mana" in fields:
            o.mp = -1 if fields["mana"] is None else _int(fields["mana"], f"{path}.mana", 0)
        if "gold" in fields:
            o.gold = _int(fields["gold"], f"{path}.gold", 0)
        if "acquisition" in fields:
            v = fields["acquisition"]
            o.target_acquisition = {"normal": -1.0, "camp": -2.0}.get(v) if isinstance(v, str) else None
            if o.target_acquisition is None:
                o.target_acquisition = _num(v, f"{path}.acquisition")
                if o.target_acquisition < 0:
                    raise _bad(f"{path}.acquisition", 'expected "normal", "camp" or a range >= 0')
        if "hero" in fields:
            v, hpath = fields["hero"], f"{path}.hero"
            if not isinstance(v, dict) or not set(v) <= {"level", "strength", "agility", "intelligence"}:
                raise _bad(hpath, "expected {level, strength, agility, intelligence}")
            if "level" in v:
                o.hero_level = _int(v["level"], f"{hpath}.level", 1, 10000)
            for k in ("strength", "agility", "intelligence"):
                if k in v:
                    if self.units.subversion < 11:
                        raise _bad(f"{hpath}.{k}", "this map's unit file (subversion 9) cannot store hero attributes")
                    setattr(o, k, _int(v[k], f"{hpath}.{k}", 0))
        if "inventory" in fields:
            v = fields["inventory"]
            if not isinstance(v, list) or len(v) > 6:
                raise _bad(f"{path}.inventory", "expected up to 6 {slot, item}")
            inventory = []
            for i, e in enumerate(v):
                epath = f"{path}.inventory[{i}]"
                if not isinstance(e, dict) or set(e) != {"slot", "item"}:
                    raise _bad(epath, "expected {slot, item}")
                item = _rawcode(e["item"], f"{epath}.item")
                if _id(item) not in self.ids("item"):
                    raise _bad(f"{epath}.item", f"no item {_id(item)!r} (data_search kind=item)")
                inventory.append((_int(e["slot"], f"{epath}.slot", 0, 5), item))
            if len({slot for slot, _ in inventory}) != len(inventory):
                raise _bad(f"{path}.inventory", "each slot holds one item")
            o.inventory = sorted(inventory)
        if "abilities" in fields:
            v = fields["abilities"]
            if not isinstance(v, list):
                raise _bad(f"{path}.abilities", "expected a list of {id, autocast, level}")
            o.abilities = [self._ability(a, f"{path}.abilities[{i}]") for i, a in enumerate(v)]
        if "drops" in fields:
            self._drops(o, fields["drops"], f"{path}.drops")
        if "random" in fields:
            if _id(o.id) not in RANDOM_TYPES:
                raise _bad(f"{path}.random", f"only random types ({', '.join(RANDOM_TYPES)}) take random settings")
            self._random(o, fields["random"], f"{path}.random")
        if "color" in fields:
            o.color = -1 if fields["color"] is None else _int(fields["color"], f"{path}.color", 0, 23)
        if "waygate" in fields:
            o.waygate = self._region_index(fields["waygate"], f"{path}.waygate")

    # ops
    def op_add(self, op: dict, path: str) -> None:
        kind = op.get("kind")
        if kind not in KINDS:
            raise ToolError("bad_kind", f"{path}: unknown placed kind {kind!r}", hint="one of: " + ", ".join(KINDS))
        fields = {k: v for k, v in op.items() if k not in ("op", "kind")}
        if kind == "start_location":
            fields.pop("type", None)
        missing = [k for k in ("type", "x", "y") if k not in fields and not (k == "type" and kind == "start_location")]
        if kind == "start_location" and "owner" not in fields:
            missing.append("owner")
        if missing:
            raise _bad(path, f"a new {kind} needs {', '.join(missing)}")
        raw = b"sloc" if kind == "start_location" else self._type(kind, fields["type"], f"{path}.type")
        if kind in ("doodad", "destructible"):
            pool = self.doodads.doodads
            o = doo.Doodad(raw, 0, 0.0, 0.0, 0.0, math.radians(270), [1.0, 1.0, 1.0], raw, 2,
                           100 if kind == "destructible" else 255)
        else:
            pool = self.units.units
            o = unitsdoo.Unit(raw, 0, 0.0, 0.0, 0.0, math.radians(270), [1.0, 1.0, 1.0], raw, 2, 0,
                              random_flag=0, random_data=LEVEL_1)
            if kind != "unit":
                o.gold, o.target_acquisition, o.hero_level = 0, 0.0, 0
            if kind == "item":
                o.owner = NEUTRAL_PASSIVE
        o.editor_id = max((x.editor_id for x in pool), default=-1) + 1
        self._apply(kind, o, {k: v for k, v in fields.items() if k != "type"}, path)
        pool.append(o)
        self.created.append(f"{kind}:{o.editor_id}")

    def op_set(self, op: dict, path: str) -> None:
        kind, o = self._find(op.get("ref"), f"{path}.ref")
        self._apply(kind, o, {k: v for k, v in op.items() if k not in ("op", "ref")}, path)

    def op_move(self, op: dict, path: str) -> None:
        if set(op) != {"op", "ref", "x", "y"}:
            raise ToolError("bad_op", f"{path}: move takes ref, x and y", hint=_HINT)
        self.op_set(op, path)

    def op_delete(self, op: dict, path: str) -> None:
        if set(op) != {"op", "ref"}:
            raise ToolError("bad_op", f"{path}: delete takes only ref", hint=_HINT)
        kind, o = self._find(op["ref"], f"{path}.ref")
        if kind in SCRIPT_PREFIX:
            script = f"{SCRIPT_PREFIX[kind]}{_id(o.id)}_{o.editor_id:04d}"
            try:
                tf, ct = _load(self.project, self.catalog.trigger_data)
                users = script_users(tf, ct, script)
            except ToolError as e:
                if e.code != "no_triggers":
                    raise
                users = []
            if users:
                raise ToolError("in_use", f"{path}: {script} is used by {len(users)} trigger(s)",
                                hint="change or delete those triggers first", triggers=users[:20])
        pool = self.units.units if isinstance(o, unitsdoo.Unit) else self.doodads.doodads
        pool.remove(o)

    def finish(self) -> dict:
        changed = []
        for name, model, before, codec in ((UNITS_FILE, self.units, self.units_before, unitsdoo),
                                           (DOODADS_FILE, self.doodads, self.doodads_before, doo)):
            if before is None and not (model.units if codec is unitsdoo else model.doodads):
                continue
            try:
                data = codec.serialize(model)
            except FormatError as e:
                raise ToolError("bad_value", f"cannot encode {name}: {e}") from e
            if data != before:
                self.project.write(name, data)
                changed.append(name)
        if changed:
            self.warnings += [SCRIPT_WARNING, DERIVED_WARNING]
        return {"changed": bool(changed), "files": changed, "created": self.created, "warnings": self.warnings}


def placed_edit(project, catalog, ops: list) -> dict:
    edit = _Edit(project, catalog)
    for i, op in enumerate(ops):
        path = f"ops[{i}]"
        try:
            action = op.get("op") if isinstance(op, dict) else None
            if action not in ("add", "set", "move", "delete"):
                raise ToolError("bad_op", f"{path}: unknown op {action!r}", hint=_HINT)
            getattr(edit, f"op_{action}")(op, path)
        except ToolError as e:
            e.details.setdefault("op_index", i)
            if e.code == "bad_value" and not e.hint:
                e.hint = "placed_list shows refs and fields"
            raise
    return edit.finish()
