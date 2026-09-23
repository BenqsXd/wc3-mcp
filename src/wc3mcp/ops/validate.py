"""map_validate: cross-file reference checks over a map's files, using the repo codecs.

validate(files, catalog, has_file=None) -> {"errors": [...], "warnings": [...]}, items {"check", "file", "message"}.
`files` maps archive names to bytes; `has_file(name)` answers for files not passed in (imports), default: in `files`.
Errors are problems that stop the map (or its regenerated script) from loading; warnings are defects that shipped
Blizzard maps carry and still load with.
"""
import dataclasses
import re
from collections import Counter

from ..formats import doo, imp, objmods, unitsdoo, w3e, w3i, w3r, wct, wtg
from ..formats.binary import FormatError
from ..formats.wts import TriggerStrings
from ..gamedata import orderids
from ..gamedata.catalog import MODEL_FIELDS
from ..gamedata.kinds import OBJECT_KINDS
from .gui import GENERATED, Checker, script_name
from . import objdata as objdata_ops
from .objdata import EXTENSIONS, var_type as mod_type

TRIGSTR_ANY = re.compile(r"TRIGSTR_(-?\d+)")
KIND_OF = {ext: kind for kind, ext in EXTENSIONS.items()}
GG_REF = re.compile(r"\bgg_(?:trg|rct|snd|cam|unit|item|dest)_\w+")
UDG_REF = re.compile(r"\budg_(\w+)")
SCRIPTS = ("war3map.j", "scripts\\war3map.j", "war3map.lua", "scripts\\war3map.lua")


def _key(name: str) -> str:
    return name.replace("/", "\\").lower()


def script_globals(text: str, lua: bool) -> set[str]:
    if lua:
        return set(re.findall(r"(?m)^([A-Za-z_]\w*)\s*=", text))
    m = re.search(r"(?ms)^globals\b(.*?)^endglobals\b", text)
    body = m.group(1) if m else ""
    return set(re.findall(r"(?m)^[ \t]*(?:constant[ \t]+)?[A-Za-z_]\w*[ \t]+(?:array[ \t]+)?([A-Za-z_]\w*)", body))


def code_only(text: str, lua: bool) -> str:
    """Script text with string literals emptied and comments removed."""
    if lua:
        text = re.sub(r"--\[(=*)\[.*?\]\1\]", "", text, flags=re.S)
        text = re.sub(r'"(?:[^"\\\n]|\\.)*"' + r"|'(?:[^'\\\n]|\\.)*'", '""', text)
        return re.sub(r"--[^\n]*", "", text)
    text = re.sub(r'"(?:[^"\\\n]|\\.)*"', '""', text)
    return re.sub(r"//[^\n]*", "", text)


def _params(ecas, enabled_only=True):
    for e in ecas:
        if enabled_only and not e.enabled:
            continue
        stack = list(e.params)
        while stack:
            p = stack.pop()
            yield p
            if p.index is not None:
                stack.append(p.index)
            if p.call is not None:
                stack.extend(p.call.params or [])
        yield from _params(e.children, enabled_only)


def _strings(obj):
    """Every str inside a (nested) dataclass / list."""
    if isinstance(obj, str):
        yield obj
    elif dataclasses.is_dataclass(obj):
        for f in dataclasses.fields(obj):
            yield from _strings(getattr(obj, f.name))
    elif isinstance(obj, (list, tuple)):
        for x in obj:
            yield from _strings(x)


class _V:
    def __init__(self, files, catalog, has_file):
        self.catalog, self.td = catalog, catalog.trigger_data
        self.files = {_key(k): v for k, v in files.items()}
        self.has_file = has_file or (lambda name: _key(name) in self.files)
        self.errors, self.warnings = [], []

    def get(self, name):
        return self.files.get(_key(name))

    def add(self, error: bool, check: str, file: str, message: str):
        (self.errors if error else self.warnings).append({"check": check, "file": file, "message": message})

    def parse(self, name, fn):
        data = self.get(name)
        if data is None:
            return None
        try:
            return fn(data)
        except (FormatError, ValueError, IndexError, UnicodeDecodeError) as e:
            self.add(True, "format", name, f"cannot parse: {e}")
            return None

    # ---------------------------------------------------------------------------------------------------------
    def run(self):
        self.mi = self.parse("war3map.w3i", w3i.parse)
        wts = self.get("war3map.wts")
        self.strings = TriggerStrings.parse(wts) if wts is not None else None
        self.tf = self.parse("war3map.wtg", lambda d: wtg.parse(d, self.td.arg_count))
        self.ct = self.parse("war3map.wct", wct.parse)
        self.objects = {}
        for ext in objmods.EXTENSIONS:
            for prefix in ("war3map", "war3mapSkin"):
                name = f"{prefix}.{ext}"
                om = self.parse(name, lambda d, ext=ext: objmods.parse(d, ext in objmods.LEVEL_EXTENSIONS))
                if om is not None:
                    self.objects[name] = om
        self.script_file = next((n for n in SCRIPTS if self.get(n) is not None), None)
        self.script = self.get(self.script_file).decode("utf-8", "replace") if self.script_file else None
        self.lua = bool(self.script_file and self.script_file.endswith(".lua"))
        self.triggers = [t for t in self.tf.elements if isinstance(t, wtg.Trigger) and t.kind == wtg.TRIGGER] \
            if self.tf else []
        texts = self.ct.texts if self.ct and len(self.ct.texts) == len(self.triggers) else [None] * len(self.triggers)
        self.texts = list(zip(self.triggers, texts))
        self.check_script_language()
        self.check_trigstr()
        self.check_triggers()
        self.check_objects()
        self.check_imports()
        self.check_constants()
        self.check_placed()
        self.check_command_cards()
        self.check_function_order()
        self.check_order_strings()
        self.check_ability_orders()
        self.check_heroes()
        self.check_channel_targets()
        self.check_waygates()
        self.check_shops()
        self.check_icons()
        self.check_reachable()
        return {"errors": self.errors, "warnings": self.warnings}

    def generated(self, t) -> bool:
        """Whether the editor writes this trigger's code into the script."""
        return bool(t.enabled) and not t.is_comment

    def check_script_language(self):
        if self.mi is None:
            return
        lang = self.mi.script_language if self.mi.version >= 28 else 0
        if lang not in (0, 1):
            self.add(True, "script_language", "war3map.w3i", f"unknown script language {lang}")
            return
        want, other = ("war3map.lua", "war3map.j") if lang == 1 else ("war3map.j", "war3map.lua")
        if self.get(want) is None and self.get("scripts\\" + want) is None:
            self.add(True, "script_language", "war3map.w3i",
                     f"script language is {'Lua' if lang else 'JASS'} but the map has no {want}")
        if self.get(other) is not None or self.get("scripts\\" + other) is not None:
            self.add(False, "script_language", other, f"{other} is ignored: war3map.w3i selects {want}")

    def check_trigstr(self):
        ids = {e.id for e in self.strings.entries} if self.strings else set()
        sources = []
        if self.mi is not None:
            sources.append(("war3map.w3i", _strings(self.mi)))
        for name, om in self.objects.items():
            sources.append((name, (m.value for t in (om.original, om.custom) for e in t for m in e.mods
                                   if m.var_type == objmods.STRING)))
        if self.tf is not None:
            sources.append(("war3map.wtg", [p.value for t in self.triggers if self.generated(t) and not t.custom_text
                                            for p in _params(t.ecas)]
                            + [v.initial for v in self.tf.variables if v.initialized]))
        if self.ct is not None:
            sources.append(("war3map.wct", [self.ct.header or ""]
                            + [s for t, s in self.texts if s and self.generated(t) and t.custom_text]))
        if self.script is not None:
            sources.append((self.script_file, [self.script]))
        for name, values in sources:
            # negative ids (TRIGSTR_-1) are the editor's "no string" marker
            missing = sorted({int(n) for v in values for n in TRIGSTR_ANY.findall(v) if int(n) >= 0} - ids)
            if missing:
                self.add(False, "trigstr", name, f"{len(missing)} TRIGSTR reference(s) without a war3map.wts entry: "
                         + ", ".join(f"TRIGSTR_{n:03d}" for n in missing[:10]))

    def check_triggers(self):
        if self.tf is None:
            return
        tf, td = self.tf, self.td
        if self.ct is not None and len(self.ct.texts) != len(self.triggers):
            self.add(True, "wct_count", "war3map.wct",
                     f"{len(self.ct.texts)} custom texts for {len(self.triggers)} triggers in war3map.wtg")
        # structure
        category_ids = {e.id for e in tf.elements if isinstance(e, wtg.Category)}
        for e in [*tf.elements, *tf.variables]:
            if not (isinstance(e, wtg.Category) and e.kind == wtg.ROOT) and e.parent not in category_ids:
                self.add(True, "structure", "war3map.wtg", f"{e.name!r} is in category id {e.parent}, which does not exist")
        # variables
        variables = {}
        for v in tf.variables:
            if v.name in variables:
                self.add(True, "variable", "war3map.wtg", f"variable {v.name!r} is declared twice")
            variables[v.name] = v
            t = td.types.get(v.type)
            if t is None or not t.global_ok:
                self.add(True, "variable", "war3map.wtg", f"variable {v.name!r} has invalid type {v.type!r}")
            if not re.fullmatch(r"[A-Za-z0-9_]+", v.name):  # the script name is udg_<name>
                self.add(True, "variable", "war3map.wtg", f"variable name {v.name!r} is not a valid identifier")
            if v.initialized and v.initial:
                preset = td.presets.get(v.initial)
                if preset is not None and td.compatible(v.type, preset.type):
                    continue
                c = Checker(td, {}, set())
                c.literal(v.initial, v.type, v.name)
                for msg in c.errors:
                    self.add(True, "variable", "war3map.wtg", f"initial value: {msg}")
        # trigger names: every non-comment trigger (disabled ones too) declares gg_trg_<script name>
        names = {}
        for t in self.triggers:
            if not t.is_comment:
                names.setdefault(script_name(t.name), []).append(t.name)
        for sname, group in names.items():
            if len(group) > 1:
                self.add(True, "trigger_name", "war3map.wtg", f"triggers {group} share script name gg_trg_{sname}")
        globals_ = script_globals(self.script, self.lua) if self.script is not None else None
        # GUI code
        for t in self.triggers:
            if not self.generated(t) or t.custom_text:
                continue
            c = Checker(td, variables, set(names))
            c.ecas(t.ecas, t.name)
            for msg in c.errors:
                self.add(True, "gui", "war3map.wtg", msg)
            for msg in c.warnings:
                self.add(True, "trigger_ref", "war3map.wtg", msg)
            if globals_ is not None:
                for p in _params(t.ecas):
                    if p.type == wtg.VARIABLE and p.value.startswith(tuple(GENERATED)):
                        self.generated_ref(p.value, globals_, set(names), "war3map.wtg", t.name)
        # custom script text
        if self.ct is None:
            return
        for where, text in [("map header", self.ct.header)] + [(t.name, s) for t, s in self.texts
                                                              if self.generated(t) and t.custom_text]:
            code = code_only(text or "", self.lua)
            for ref in sorted(set(UDG_REF.findall(code)) - set(variables)):
                self.add(True, "variable_ref", "war3map.wct", f"{where}: udg_{ref} is not a trigger variable")
            if globals_ is not None:
                for ref in sorted(set(GG_REF.findall(code))):
                    self.generated_ref(ref, globals_, set(names), "war3map.wct", where)
        for t, text in self.texts:
            if self.generated(t) and t.custom_text:
                sname = script_name(t.name)
                if not re.search(rf"\bfunction\s+InitTrig_{sname}\b", code_only(text or "", self.lua)):
                    self.add(True, "custom_text", "war3map.wct",
                             f"{t.name}: custom text defines no function InitTrig_{sname}, which the script calls")

    def generated_ref(self, ref, globals_, trigger_names, file, where):
        if ref.startswith("gg_trg_"):
            if ref[len("gg_trg_"):] not in trigger_names and file != "war3map.wtg":  # wtg: reported by Checker
                self.add(True, "trigger_ref", file, f"{where}: no trigger matches {ref}")
        elif ref not in globals_:
            self.add(True, "generated_ref", file, f"{where}: {ref} is not a global of the current {self.script_file}")

    def check_objects(self):
        for name, om in self.objects.items():
            ext = name.rsplit(".", 1)[1]
            kind = KIND_OF[ext]
            base_ids = set(self.catalog.ids(kind))
            meta = self.catalog.table(OBJECT_KINDS[kind].meta).rows
            seen = set()
            for custom, table in ((False, om.original), (True, om.custom)):
                for e in table:
                    base, new = e.base_id.decode("latin-1"), e.new_id.decode("latin-1")
                    oid = new if custom else base
                    if base not in base_ids:
                        self.add(False, "objdata_base", name, f"{kind} {oid}: base id {base!r} is not in the game data"
                                 + (" (the object cannot be created)" if custom else " (modifications are ignored)"))
                    if custom:
                        if new in seen:
                            self.add(False, "objdata_id", name, f"custom {kind} id {new!r} is defined twice")
                        if new in base_ids:
                            self.add(False, "objdata_id", name, f"custom {kind} id {new!r} is a standard object id")
                        seen.add(new)
                    for m in e.mods:
                        rid = m.id.decode("latin-1")
                        row = meta.get(rid)
                        if row is None:
                            self.add(False, "objdata_field", name, f"{kind} {oid}: unknown field {rid!r}")
                        elif mod_type(row.get("type", "")) != m.var_type:
                            self.add(False, "objdata_type", name, f"{kind} {oid}: field {rid} ({row.get('type')}) "
                                     f"stored as value type {m.var_type}")

    def check_imports(self):
        il = self.parse("war3map.imp", imp.parse)
        if il is None:
            return
        for e in il.entries:
            if not (self.has_file(e.path) or self.has_file("war3mapImported\\" + e.path)):
                self.add(False, "import", "war3map.imp", f"imported file {e.path!r} (flag {e.flag}) is not in the map")


    def check_constants(self):
        """war3mapMisc.txt is read key by key, so a misspelt key is simply ignored by the game."""
        from . import constants as constants_ops

        data = self.get(constants_ops.MAP_FILE)
        if data is None:
            return
        known = constants_ops.defaults(self.catalog)
        for key in constants_ops._parse(data.decode("utf-8", "replace")):
            if key not in known:
                self.add(False, "constant", constants_ops.MAP_FILE,
                         f"{key} is not a gameplay constant the game defines, so it has no effect "
                         f"(constants_get lists them)")

    def _mods(self, kind: str) -> dict[str, tuple[str, dict[str, object], bool]]:
        """Object id -> (base id, the first-level values the map sets, custom) for the map's objects of a kind."""
        out = {}
        for prefix in ("war3map", "war3mapSkin"):
            om = self.objects.get(f"{prefix}.{EXTENSIONS[kind]}")
            for custom, table in ((False, om.original), (True, om.custom)) if om else ():
                for e in table:
                    oid = (e.new_id if custom else e.base_id).decode("latin-1")
                    base, fields, _ = out.setdefault(oid, (e.base_id.decode("latin-1"), {}, custom))
                    fields.update({m.id.decode("latin-1"): m.value for m in e.mods if m.level in (0, 1)})
        return out

    def _art(self, kind: str) -> dict[str, tuple[str, dict[str, str]]]:
        """Object id -> (base id, model and variation fields the map sets) for the map's objects of a kind."""
        wanted = {f for f in MODEL_FIELDS[kind] if f}
        return {oid: (base, {k: v for k, v in fields.items() if k in wanted})
                for oid, (base, fields, _) in self._mods(kind).items()}

    def _emitted(self) -> list[tuple[str, str]]:
        """(where, custom script text) in the order the generated script emits them: header, then triggers by tree."""
        return [("map header", self.ct.header or "")] + [(t.name, s or "") for t, s in self.texts
                                                         if self.generated(t) and t.custom_text]

    def check_function_order(self):
        """A trigger can only call functions that an earlier trigger defines: the script emits them in tree order,
        and re-sending a trigger used to move it to the end of its category."""
        from ..script.validate import is_vjass   # vJASS reorders libraries itself

        if self.ct is None or self.lua or self.script is None or is_vjass(self.script):
            return
        parts = [(where, code_only(text, False)) for where, text in self._emitted()]
        defined = {}
        for i, (_where, code) in enumerate(parts):
            for m in re.finditer(r"(?m)^[ \t]*function\s+(\w+)\b", code):
                defined.setdefault(m[1], i)
        for i, (where, code) in enumerate(parts):
            for name in sorted({n for n in re.findall(r"\b(\w+)\s*\(", code) if defined.get(n, i) > i}):
                later = parts[defined[name]][0]
                self.add(True, "function_order", "war3map.wct",
                         f"{where} calls {name}(), which trigger {later!r} defines further down the trigger tree: the "
                         f"script emits trigger functions in tree order, so this does not compile — move {later!r} "
                         f'above {where!r} ({{"op": "trigger", "name": "{later}", "after": ...}} or "index")')

    def _known_orders(self) -> tuple[set[str], dict[str, tuple[str, str, str]]]:
        """(every order string the game data and the editor know, disagreeing ones -> (ability, name, editor order))"""
        known, disagree = set(), {}
        mods = self._mods("ability")
        for rows in (self.catalog._order_presets.values()):
            known |= {r["order"].casefold() for r in rows}
        for oid, (base, fields, _custom) in mods.items():
            known |= {str(fields[f]).casefold() for f in ("aord", "aoro", "aorf") if fields.get(f)}
        for oid in self.catalog.ids("ability"):
            orders = self.catalog.ability_orders(oid)
            known |= {str(v).casefold() for v in orders["data"].values()}
            if orders.get("disagree") and oid not in mods:
                data = orders["data"]["aord"]
                disagree[data.casefold()] = (oid, self.catalog.name("ability", oid), orders["editor"][0]["order"])
        return known, disagree

    def check_reachable(self):
        """Ground a player cannot walk to: start locations cut off from each other, or a player's own preplaced unit
        the player cannot reach. Decoration (a forest, a wall of doodads) is the usual cause."""
        from . import pathing

        units = self.parse("war3mapUnits.doo", unitsdoo.parse)
        if units is None:
            return
        terrain = self.parse("war3map.w3e", w3e.parse)
        if terrain is None:
            return
        doodads = self.parse("war3map.doo", doo.parse)
        mods = {kind: self._mods(kind) for kind in ("unit", "doodad", "destructible")}
        ids = {kind: set(self.catalog.ids(kind)) | set(mods[kind]) for kind in mods}

        def value(kind, oid, field):
            base, fields, _ = mods[kind].get(oid, (oid, {}, False))
            return fields[field] if field in fields else self.catalog.field(kind, base, field)

        objects = []
        for o in doodads.doodads if doodads else ():
            t = o.id.decode("latin-1")
            objects.append(("destructible" if t in ids["destructible"] else "doodad", t, o.x, o.y, o.angle))
        starts, owned = {}, []
        for u in units.units:
            t = u.id.decode("latin-1")
            if t == "sloc":
                starts[u.owner] = (u.x, u.y)
            elif t in ids["unit"]:
                objects.append(("unit", t, u.x, u.y))
                if u.owner < 24:
                    owned.append((u.owner, t, u.x, u.y))
        if len(starts) < 1:
            return
        grid = pathing.walkable(terrain, self.catalog, objects, value)
        corners = {owner: pathing.corner_of(terrain, x, y) for owner, (x, y) in starts.items()}
        first = min(corners)
        seen = pathing.reachable(grid, [corners[first]])
        cut = [owner for owner, corner in corners.items() if owner != first and corner not in seen]
        if cut:
            free = sum(sum(row) for row in grid)
            self.add(False, "reachable", "war3map.w3e",
                     f"the start location(s) of player(s) {sorted(cut)} cannot be walked to from player {first}'s "
                     f"start, which reaches {len(seen)} of {free} walkable corners: cliffs, water or placed objects "
                     f"close the way — deliberate for a lobby or drop platform, a defect when decoration did it "
                     f"({pathing.NOTE})")
        stranded = sorted({(owner, t) for owner, t, x, y in owned
                           if owner in corners and corners[owner] in seen
                           and pathing.corner_of(terrain, x, y) not in seen})
        if stranded:
            names = ", ".join(f"player {o}'s {t}" for o, t in stranded[:5])
            self.add(False, "reachable", "war3mapUnits.doo",
                     f"{len(stranded)} preplaced unit type(s) stand where their own player cannot walk: {names}"
                     + ("..." if len(stranded) > 5 else ""))

    def check_ability_orders(self):
        """Two abilities on one unit with the same order string: ordering the unit to cast one is ambiguous, so
        copies of the same base (Channel, above all) need their own order id."""
        units, abilities = self._mods("unit"), self._mods("ability")
        if not units:
            return
        # only orders the editor itself lists as issuable: a passive ability's data order (a copy of Attribute Bonus
        # keeps attributemodskill) is never issued, so sharing one is not a defect
        orderable = {r["order"].casefold() for rows in self.catalog._order_presets.values() for r in rows}

        def value(kind: str, oid: str, rid: str):
            base, fields, _ = (units if kind == "unit" else abilities).get(oid, (oid, {}, False))
            return fields[rid] if rid in fields else self.catalog.field(kind, base, rid)

        for oid in units:
            carried = [a for field in ("uabi", "uhab") for a in str(value("unit", oid, field) or "").split(",")
                       if a.strip()]
            orders: dict[str, list[str]] = {}
            for ability in dict.fromkeys(carried):   # the same ability twice is a different defect
                for field in ("aord", "aoro", "aorf"):
                    order = str(value("ability", ability, field) or "").strip()
                    if order and order.casefold() in orderable:
                        orders.setdefault(order.casefold(), []).append(ability)
            for order, sharing in orders.items():
                if len(set(sharing)) > 1:
                    self.add(False, "ability_order", "war3map.w3u",
                             f"unit {oid}: {', '.join(sorted(set(sharing)))} all use the order {order!r}, so an "
                             "Issue*Order for one of them can run the other (copies of one base ability need their "
                             "own order: Channel's Ncl6, or the Order fields aord/aoro/aorf)")

    def check_heroes(self):
        """A copy of a hero is a hero only with a capital first letter; uhab holds 5; and a hero gets no more skill
        points than it has ranks to learn (SetHeroLevel 36 on a Paladin gave 10 points)."""
        from . import constants as constants_ops

        units, abilities = self._mods("unit"), self._mods("ability")
        if not units:
            return
        misc = constants_ops.defaults(self.catalog)
        data = self.get(constants_ops.MAP_FILE)
        mine = constants_ops._parse(data.decode("utf-8", "replace")) if data else {}
        try:
            cap = int(float(mine.get("MaxHeroLevel", misc.get("MaxHeroLevel", ("10", ""))[0])))
        except ValueError:
            cap = 10

        def value(kind, oid, rid):
            base, fields, _ = (units if kind == "unit" else abilities).get(oid, (oid, {}, False))
            return fields[rid] if rid in fields else self.catalog.field(kind, base, rid)

        for oid, (base, _fields, custom) in sorted(units.items()):
            if custom and base[:1].isupper() and not oid[:1].isupper():
                self.add(False, "hero_id_case", "war3map.w3u", f"unit {oid} copies the hero {base} but its id starts "
                         "with a lowercase letter, so the game creates it as an ordinary unit (no levels, attributes "
                         "or learn menu); recreate it with an id like H000")
            if not oid[:1].isupper():
                continue
            listed = [a for a in str(value("unit", oid, "uhab") or "").split(",") if a.strip()]
            if len(listed) > 5:
                self.add(False, "hero_ability_slots", "war3map.w3u", f"hero {oid} lists {len(listed)} abilities in "
                         "uhab; the game uses at most 5 and skips the rest (grant more with UnitAddAbility)")
            ranks = 0
            for a in listed[:5]:
                try:
                    ranks += int(float(value("ability", a, "alev") or 1))
                except ValueError:
                    ranks += 1
            if listed and ranks < cap:
                self.add(False, "hero_skill_points", "war3map.w3u", f"hero {oid} can learn {ranks} ability ranks, so "
                         f"it gets only {ranks} of the {cap} skill points MaxHeroLevel allows (the game hands out no "
                         "more points than there are ranks): raise alev of its abilities or add proxy abilities")

    def check_channel_targets(self):
        """A no-target Channel copy (Ncl2 0) needs an order the game can issue with no target, or the cast does
        nothing (frostarmor as no-target never fired in the game). Only Ncl2 0 is checked: working maps aim unit
        orders (doom, acidbomb, soulburn) at a point through Ncl2 2 and they cast, so the wider rule is folklore."""
        wanted = {0: {"immediate"}}
        data = self.catalog.table(OBJECT_KINDS["ability"].slks["AbilityData"]).rows
        targets: dict[str, set] = {}
        for rows in self.catalog._order_presets.values():
            for r in rows:
                targets.setdefault(r["order"].casefold(), set()).add(r["targets"])
        for oid, (base, fields, _custom) in sorted(self._mods("ability").items()):
            if data.get(base, {}).get("code", base) != "ANcl":
                continue
            kind = fields.get("Ncl2", self.catalog.field("ability", base, "Ncl2"))
            order = str(fields.get("Ncl6", self.catalog.field("ability", base, "Ncl6")) or "").casefold()
            try:
                need = wanted.get(int(float(kind)), set())
            except (TypeError, ValueError):
                continue
            entries = objdata_ops._entries([om for name, om in self.objects.items() if name.endswith(".w3a")], oid)
            hidden = objdata_ops.channel_hidden_ranks(self.catalog, base, objdata_ops._merged(entries))
            if hidden:
                self.add(False, "channel_levels", "war3map.w3a",
                         f"ability {oid}: Ncl3 (Options) has no visible bit at rank(s) {objdata_ops._ranks(hidden)} "
                         "while other ranks have it, so the ability has no button at those ranks (Channel's own "
                         "Ncl3 is 0 at every level: set every rank)")
            if order and orderids.resolves(order) is False:
                self.add(False, "channel_order", "war3map.w3a",
                         f"ability {oid}: its base order {order!r} (Ncl6) is not in the game's order table - OrderId "
                         "returns 0 for it in the game - so the ability can never be cast; pick an order data_search "
                         "kind=order marks resolves: true, or one a shipped ability uses (backed: true)")
            have = targets.get(order)
            if have and need and not (have & need):
                self.add(False, "channel_target", "war3map.w3a",
                         f"ability {oid}: Ncl2 asks for a {'/'.join(sorted(need))} target but its order {order!r} is "
                         f"a {'/'.join(sorted(have))} order, so casting it does nothing; pick an order of that "
                         "targeting (data_search kind=order)")

    def check_waygates(self):
        """A waygate whose destination region holds the gate itself sends a unit back onto the gate."""
        units = self.parse("war3mapUnits.doo", unitsdoo.parse)
        regions = self.parse("war3map.w3r", w3r.parse)
        if units is None or regions is None:
            return
        by_index = {r.index: r for r in regions.regions}
        for u in units.units:
            r = by_index.get(u.waygate)
            if r is not None and r.left <= u.x <= r.right and r.bottom <= u.y <= r.top:
                self.add(False, "waygate_self", "war3mapUnits.doo", f"the waygate at ({u.x:g}, {u.y:g}) leads into "
                         f"region {r.name!r}, which contains the gate itself")

    def check_shops(self):
        """What a shop's card offers that a player cannot use: an item whose Stock Maximum (isto) is 0 is never in
        stock (a playtest found every item of a map unbuyable that way, while every other check stayed quiet), and
        entries of one card on the same hotkey (a copied item keeps its base's). Only shops the map touches are read:
        its own, and any that sell one of its objects. Shared button positions are not reported: stock shops list
        items that all sit at (0, 0), and the card lays them out in list order."""
        mods = {kind: self._mods(kind) for kind in ("unit", "item")}
        if not mods["unit"] and not mods["item"]:
            return

        def value(kind, oid, rid, stock=False):
            base, fields, _ = mods[kind].get(oid, (oid, {}, False))
            return fields[rid] if rid in fields and not stock else self.catalog.field(kind, base, rid)

        def ids(kind, oid, rid, stock=False):
            return [x.strip() for x in str(value(kind, oid, rid, stock) or "").split(",") if x.strip()]

        def card(shop, stock):
            """The hotkey of every entry on a shop's card."""
            return {entry: str(value(kind, entry, "uhot", stock) or "").strip().upper()
                    for kind, field in (("item", "usei"), ("unit", "useu")) for entry in ids("unit", shop, field, stock)}

        touched = set(mods["item"]) | set(mods["unit"])
        shops = set(mods["unit"]) | set(self.catalog.ids("unit"))
        for shop in sorted(shops):
            sold = ids("unit", shop, "usei") + ids("unit", shop, "useu")
            if not sold or not (shop in mods["unit"] or touched & set(sold)):
                continue
            for item in ids("unit", shop, "usei"):
                stock_max = value("item", item, "isto")
                try:
                    empty = stock_max not in (None, "") and int(float(stock_max)) == 0
                except ValueError:
                    empty = False
                if empty and item in mods["item"]:
                    self.add(False, "shop_stock", "war3map.w3t", f"shop {shop} sells item {item}, whose isto (Stock "
                             "Maximum) is 0, so it is never in stock and the shop shows it greyed out: shipped items "
                             "use isto 1, isit 1, istr 120; a small stock that refills every second (isto 3, isit 3, "
                             "istr 1, isst 0) is the nearest to unlimited")
            keys, stock = card(shop, False), card(shop, True)
            groups: dict[str, list[str]] = {}
            for entry, key in keys.items():
                if key:
                    groups.setdefault(key, []).append(entry)
            for key, sharing in sorted(groups.items()):
                if len(sharing) < 2 or not touched & set(sharing):
                    continue
                if all(stock.get(e) == key for e in sharing):
                    continue   # the stock shop ships that clash
                self.add(False, "shop_hotkey", "war3map.w3t", f"shop {shop}: {', '.join(sharing)} all use the hotkey "
                         f"{key} on its card, so the key buys only one of them (a copy keeps its base's uhot: give "
                         "each entry its own, QWER/ASDF/ZXCV by card cell)")

    def check_icons(self):
        """An icon path the game cannot load draws a blank green square and nothing else says so."""
        fields = {"item": ("iico",), "ability": ("aart", "arar"), "unit": ("uico", "ussi")}
        files = {"item": "war3map.w3t", "ability": "war3map.w3a", "unit": "war3map.w3u"}
        for kind, rids in fields.items():
            for oid, (_base, values, _custom) in sorted(self._mods(kind).items()):
                for rid in rids:
                    path = str(values.get(rid) or "").strip()
                    if not path or TRIGSTR_ANY.fullmatch(path):
                        continue
                    stem = path.rsplit(".", 1)[0] if "." in path.rsplit("\\", 1)[-1] else path
                    if any(self.has_file(stem + ext) for ext in (".blp", ".dds", ".tga")) \
                            or self.catalog.icon_exists(path):
                        continue
                    self.add(False, "icon", files[kind], f"{kind} {oid}: {rid} {path!r} is neither in the game data "
                             "nor imported, so the game draws a blank green square (data_search kind=icon finds real "
                             "ones)")

    def check_order_strings(self):
        """Order strings a script issues: the ability data and the editor presets disagree for a few abilities, and
        only one of the two works (tested by issuing it); a string neither of them knows is always refused."""
        if self.ct is None:
            return
        issued: dict[str, list[str]] = {}
        for where, text in self._emitted():
            for call in re.finditer(r"\bIssue\w*Order\w*\s*\(([^)]*)\)", text):
                for order in re.findall(r'"([^"\n]+)"', call[1]):
                    issued.setdefault(order, []).append(where)
        if not issued:
            return
        known, disagree = self._known_orders()
        for order, wheres in issued.items():
            hit = disagree.get(order.casefold())
            if hit:
                self.add(False, "order_string", "war3map.wct",
                         f"{wheres[0]}: order {order!r} is the ability data's order of {hit[0]} ({hit[1]}), but the "
                         f"World Editor uses {hit[2]!r} for it and only one of the two works: check the boolean the "
                         "Issue*Order call returns, and fall back to the other string")
            elif order.casefold() not in known:
                self.add(False, "order_string", "war3map.wct",
                         f"{wheres[0]}: order {order!r} matches no ability order and no editor order preset, so "
                         "Issue*Order returns false and the unit does nothing (data_get kind=ability shows orders)")

    def check_command_cards(self):
        """Object data pitfalls no single edit shows: command-card buttons on one slot, a copied worker that keeps its
        build list, an ability locked behind a research nobody can get."""
        mods = {kind: self._mods(kind) for kind in ("unit", "ability", "upgrade")}
        if not mods["unit"]:
            return
        name = "war3map.w3u"

        def value(kind, oid, rid, stock=False):
            base, fields, _ = mods[kind].get(oid, (oid, {}, False))
            return fields[rid] if rid in fields and not stock else self.catalog.field(kind, base, rid)

        def ids(kind, oid, rid, stock=False):
            return [x for x in str(value(kind, oid, rid, stock) or "").split(",") if x.strip()]

        def slots(oid, stock):
            """(x, y) -> button labels on a building's command card."""
            card: dict[tuple, list[str]] = {}
            trains, researches = ids("unit", oid, "utra", stock), ids("unit", oid, "ures", stock)
            abilities = ids("unit", oid, "uabi", stock)
            buttons = [(u, "unit", "ubpx", "ubpy") for u in trains + ids("unit", oid, "uupt", stock)]
            buttons += [(r, "upgrade", "gbpx", "gbpy") for r in researches]
            buttons += [(a, "ability", "abpx", "abpy") for a in abilities]
            for obj, kind, fx, fy in buttons:
                x, y = value(kind, obj, fx), value(kind, obj, fy)
                if x not in (None, "") and y not in (None, ""):
                    card.setdefault((int(float(x)), int(float(y))), []).append(obj)
            if trains and "ARal" not in abilities:
                card.setdefault((3, 1), []).append("Rally")
            if trains or researches:
                card.setdefault((3, 2), []).append("Cancel")
            return card

        def learn_card(oid, stock):
            """("cell", x, y) and ("key", hotkey) -> the hero abilities (uhab) there on a hero's learn menu. Four
            proxies left on their defaults all sat on one cell with the hotkey B in a playtest."""
            card: dict[tuple, list[str]] = {}
            for a in ids("unit", oid, "uhab", stock):
                x, y = value("ability", a, "arpx", stock), value("ability", a, "arpy", stock)
                if x not in (None, "") and y not in (None, "") and float(x) >= 0 and float(y) >= 0:
                    card.setdefault(("cell", int(float(x)), int(float(y))), []).append(a)
                key = str(value("ability", a, "arhk", stock) or "").strip().upper()
                if key:
                    card.setdefault(("key", key), []).append(a)
            return card

        script = self.script or ""
        melee = "MeleeStartingUnits" in script
        units = self.parse("war3mapUnits.doo", unitsdoo.parse)
        present = set(mods["unit"]) | {u.id.decode("latin-1") for u in (units.units if units else ())}
        offered = {r for oid in present for r in ids("unit", oid, "ures")}
        upgrades = set(self.catalog.ids("upgrade")) | set(mods["upgrade"])
        locked: dict[str, list[str]] = {}
        for oid, (base, fields, custom) in sorted(mods["unit"].items()):
            card = slots(oid, False)
            if any(len(labels) > 1 for labels in card.values()):
                stock = slots(base, True)   # a clash the stock object has too is how the game ships it
                for (x, y), labels in sorted(card.items()):
                    if len(labels) > 1 and sorted(labels) != sorted(stock.get((x, y), [])):
                        self.add(False, "command_card", name, f"unit {oid}: {', '.join(labels)} share button position "
                                 f"({x}, {y}); only one of them can be clicked (set ubpx/ubpy, gbpx/gbpy or abpx/abpy)")
            if custom and "uabi" in fields and "ubui" not in fields:
                builds = ids("unit", base, "ubui", True)
                if builds:
                    self.add(False, "inherited_builds", name, f"unit {oid}: sets its abilities (uabi) but keeps the "
                             f"build list of {base} (ubui {','.join(builds)}), so it can still build those; set ubui "
                             'to "" if it must not build')
            learn = learn_card(oid, False)
            if any(len(v) > 1 for v in learn.values()):
                stock = learn_card(base, True)
                for key, labels in sorted(learn.items(), key=lambda kv: str(kv[0])):
                    if len(labels) > 1 and sorted(labels) != sorted(stock.get(key, [])):
                        what = f"learn-menu hotkey {key[1]}" if key[0] == "key" else f"learn-menu cell {key[1:]}"
                        self.add(False, "learn_card", name, f"hero {oid}: {', '.join(labels)} share the {what}, so "
                                 "only one of them can be learned that way (arpx/arpy and arhk are set per ability)")
            for ability in [] if melee else ids("unit", oid, "uabi") + ids("unit", oid, "uhab"):
                for research in ids("ability", ability, "areq"):   # melee races can build the research buildings
                    if research in upgrades and research not in offered and research not in script:
                        locked.setdefault(research, []).append(f"{oid} ({ability})")
        for research, users in sorted(locked.items()):
            self.add(False, "locked_ability", name, f"research {research} is required by {', '.join(users)}, but no "
                     "unit of the map researches it (ures) and the script never mentions it (SetPlayerTechResearched), "
                     "so those abilities may stay locked")

    def check_placed(self):
        doodads = self.parse("war3map.doo", doo.parse)
        units = self.parse("war3mapUnits.doo", unitsdoo.parse)
        if doodads is None and units is None:
            return
        art = {kind: self._art(kind) for kind in MODEL_FIELDS}
        ids = {kind: set(self.catalog.ids(kind)) | set(art[kind]) for kind in MODEL_FIELDS}
        placed = Counter()
        for o in doodads.doodads if doodads else ():
            kind = "destructible" if o.id.decode("latin-1") in ids["destructible"] else "doodad"
            placed[kind, o.id, o.skin, o.variation] += 1
        for u in units.units if units else ():
            if u.id.decode("latin-1") in ids["unit"]:
                placed["unit", u.id, u.skin, 0] += 1
        broken: dict[tuple, list] = {}
        for (kind, type_id, skin, variation), n in placed.items():
            t, look = type_id.decode("latin-1"), skin.decode("latin-1")
            look = look if look in ids[kind] else t
            base, fields = art[kind].get(look, (look, {}))
            file_field, count_field = MODEL_FIELDS[kind]
            if fields.get(file_field) or (count_field and fields.get(count_field)):   # the map's own model fields
                file = fields.get(file_field) or self.catalog.field(kind, base, file_field)
                if not file:
                    continue
                count = int(fields.get(count_field) or self.catalog.field(kind, base, count_field) or 1) if count_field else 1
                missing = [p for p in self.catalog.model_paths(file, count, variation) if not self.catalog.model_exists(p)]
            else:
                missing = (self.catalog.missing_models(kind, base, variation) or ([], []))[1]
            for path in missing:
                if not (self.has_file(path) or self.has_file(path[:-4] + ".mdx")):
                    entry = broken.setdefault((kind, t), [0, set()])
                    entry[0] += n
                    entry[1].add(path)
        for (kind, t), (n, paths) in sorted(broken.items()):
            self.add(False, "model", "war3map.doo" if kind != "unit" else "war3mapUnits.doo",
                     f"{n} placed {kind}(s) {t}: {', '.join(sorted(paths))} cannot be loaded from the game data "
                     "(HD or classic graphics, which the World Editor uses) or the map, so they render nothing there "
                     "(data_search shows model_ok and variations_ok per id)")
        if units is None or self.mi is None:
            return
        players = {p.id: p for p in self.mi.players}
        for u in units.units:
            p = players.get(u.owner) if u.id == b"sloc" else None
            if p is not None and (abs(p.start_x - u.x) > 1 or abs(p.start_y - u.y) > 1):
                self.add(False, "start_location", "war3map.w3i",
                         f"player {u.owner}: the start location marker is at ({u.x:g}, {u.y:g}) but war3map.w3i "
                         f"starts the player at ({p.start_x:g}, {p.start_y:g}); move it with placed_edit, which "
                         "updates both")


def validate(files: dict, catalog, has_file=None) -> dict:
    return _V(files, catalog, has_file).run()
