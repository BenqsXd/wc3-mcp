"""AI Editor data as editable JSON (.wai files, or war3map.wai in an open map), and the AI Editor's exported .ai
script written to a file or imported into a map with a trigger that starts it."""
import base64
import copy
import itertools
from pathlib import Path

from ..errors import ToolError
from ..formats import wai
from ..formats.binary import FormatError
from ..formats.wtg import ECA
from ..gamedata.triggerdata import CONDITION
from ..project.workspace import MapProject, write_file
from ..script import ai as aigen
from ..script.validate import validate_ai
from .edits import apply_ops
from .gui import Checker, eca_json, ecas_from_json, script_name
from .imports import imports_edit
from .objdata import EXTENSIONS

MAP_FILE = "war3map.wai"
RACES = {0: "custom", 1: "human", 2: "orc", 3: "undead", 4: "night_elf"}
OPTIONS = {"melee": 0x1, "target_heroes": 0x2, "repair_structures": 0x4, "heroes_flee": 0x8, "units_flee": 0x10,
           "groups_flee": 0x20, "have_no_mercy": 0x40, "ignore_injured": 0x80, "take_items": 0x100,
           "slow_harvesting": 0x200, "allow_home_changes": 0x400, "smart_artillery": 0x800, "remove_injuries": 0x1000,
           "set_player_name": 0x2000, "random_paths": 0x4000, "defend_users": 0x8000, "buy_items": 0x10000}
BUILD_TYPES = {0: "unit", 1: "upgrade", 2: "expansion"}
RESOURCES = {0: "gold", 1: "lumber"}
TARGETS = {0: "alliance_target", 1: "expansion", 2: "assault", 3: "enemy_expansion", 4: "enemy_town", 5: "creeps",
           6: "zeppelin"}
HEROES = {b"1HIA": "hero1", b"2HIA": "hero2", b"3HIA": "hero3"}
ORDERS = ["order_" + "_".join(str(i + 1) for i in perm) for perm in itertools.permutations(range(3))]
WORKERS = ("gold", "lumber", "base", "mine")
EMPTY = b"\0\0\0\0"
READ_ONLY = ("object_data",)
_HINT = ('ops on the ai_get document: {"op": "set", "path": "name", "value": "Raiders"}, {"op": "append", "path": '
         '"build", "value": {"type": "unit", "id": "hfoo", "town": "any", "condition": null}}, {"op": "remove", '
         '"path": "targets[2]"}; conditions are {"fn": "OperatorCompareInteger", "args": [{"call": "GetGold"}, '
         '{"preset": "OperatorGreater"}, 500]} as in triggers_edit')


def _bad(path: str, message: str) -> ToolError:
    return ToolError("bad_value", f"{path}: {message}", hint=_HINT, path=path)


# ---- storage ---------------------------------------------------------------------------------------------------
def load(source, td) -> wai.AIData | None:
    """The AI data of a .wai file or of an open map's war3map.wai; None when there is none yet."""
    try:
        if isinstance(source, MapProject):
            data = source.read(MAP_FILE) if any(f["name"].lower() == MAP_FILE for f in source.list_files()) else None
        else:
            data = Path(source).read_bytes() if Path(source).is_file() else None
        return None if data is None else wai.parse(data, td.arg_count)
    except FormatError as e:
        raise ToolError("bad_file", f"{source}: {e}", hint="re-save it in the AI Editor") from e


def new_ai(name: str = "New AI") -> wai.AIData:
    """A starting point like the AI Editor's new AI data: human workers, standard targets and one attack group."""
    return wai.AIData(name=name, race=1, options=0x10CE, workers=[b"hpea", b"hpea", b"htow", b"htow"],
                      targets=[wai.TargetPriority(t) for t in range(5)] + [wai.TargetPriority(5, 0, 9, 0)],
                      repeat_waves=1, groups=[wai.AttackGroup(0, "All Units")], waves=[wai.Wave(0, 0)],
                      test_flags=2, test_speed=1)


# ---- JSON view -------------------------------------------------------------------------------------------------
def _id_out(raw: bytes):
    return None if raw == EMPTY else HEROES.get(raw) or raw.decode("latin-1")


def _id_in(value, path: str, heroes: bool = False, empty: bool = False) -> bytes:
    if value is None and empty:
        return EMPTY
    if heroes and value in HEROES.values():
        return next(k for k, v in HEROES.items() if v == value)
    if isinstance(value, str) and len(value.encode("latin-1", "replace")) == 4:
        return value.encode("latin-1")
    raise _bad(path, "expected a 4-character id" + (" or hero1 / hero2 / hero3" if heroes else ""))


def _town_out(town: int):
    return {-1: "any", 0: "main"}.get(town) or (f"mine{-3 - town}" if town <= -3 else f"expansion{town}")


def _town_in(value, path: str) -> int:
    if value in ("any", "main"):
        return -1 if value == "any" else 0
    for prefix, sign in (("mine", -1), ("expansion", 1)):
        if isinstance(value, str) and value.startswith(prefix) and value[len(prefix):].isdigit():
            n = int(value[len(prefix):])
            return -3 - n if sign < 0 else n
    raise _bad(path, 'expected "any", "main", "expansion<n>" or "mine<n>" (0 = the town with the main mine)')


def _count_out(n: int, all_value: str = "all"):
    return {-1: all_value, -2: "all_not_attacking"}.get(n, n)


def _count_in(value, path: str, names: dict) -> int:
    if value in names:
        return names[value]
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 90:
        return value
    raise _bad(path, f"expected 0-90 or one of {', '.join(names)}")


def _enum_in(value, names: dict, path: str) -> int:
    for k, v in names.items():
        if value == v:
            return k
    raise _bad(path, f"expected one of {', '.join(names.values())}")


class _View:
    def __init__(self, td):
        self.td = td

    def condition_out(self, c: wai.Condition):
        return None if c.function is None else eca_json(ECA(CONDITION, c.function, 1, c.params))

    def condition_in(self, value, name: str, path: str) -> wai.Condition:
        if value is None:
            return wai.Condition(name)
        [e] = ecas_from_json([value], CONDITION, self.td, {}, path)
        checker = Checker(self.td, {}, set())
        checker.ecas([e], path)
        if checker.errors:
            raise ToolError("invalid_condition", checker.errors[0], hint="data_get kind=trigger_function shows argument "
                            "types; AI functions come from UI/AIEditorData.txt", errors=checker.errors[:20], path=path)
        return wai.Condition(name, e.name, e.params)

    def reference_out(self, index: int, condition: wai.Condition, names: dict):
        if index == wai.NO_CONDITION:
            return None
        if index == wai.CUSTOM_CONDITION:
            return {"custom": self.condition_out(condition)}
        return names.get(index, index)

    def reference_in(self, value, path: str, by_name: dict, indexes: set) -> tuple[int, wai.Condition]:
        if value is None:
            return wai.NO_CONDITION, wai.Condition()
        if isinstance(value, dict) and set(value) == {"custom"}:
            return wai.CUSTOM_CONDITION, self.condition_in(value["custom"], "", path + ".custom")
        if isinstance(value, str) and value in by_name:
            return by_name[value], wai.Condition()
        if isinstance(value, int) and not isinstance(value, bool) and value in indexes:
            return value, wai.Condition()
        raise _bad(path, 'expected null, a condition name or index from conditions, or {"custom": {...}}')

    def to_json(self, ai: wai.AIData) -> dict:
        names = {c.index: c.condition.name for c in ai.conditions}
        ref = self.reference_out
        doc = {
            "name": ai.name, "race": RACES.get(ai.race, ai.race),
            "options": {k: bool(ai.options & bit) for k, bit in OPTIONS.items()},
            "workers": dict(zip(WORKERS, (_id_out(w) for w in ai.workers))),
            "conditions": [{"index": c.index, "name": c.condition.name, "condition": self.condition_out(c.condition)}
                           for c in ai.conditions],
            "heroes": [None if h == EMPTY else {"id": _id_out(h), "skills": [[_id_out(s) for s in ai.skills[i * 3 + o]]
                                                                             for o in range(3)]}
                       for i, h in enumerate(ai.heroes)],
            "hero_orders": dict(zip(ORDERS, ai.hero_orders)),
            "build": [{"type": BUILD_TYPES.get(p.kind, p.kind), "id": _id_out(p.id), "town": _town_out(p.town),
                       "condition": ref(p.condition_index, p.condition, names)} for p in ai.build],
            "harvest": [{"resource": RESOURCES.get(p.resource, p.resource), "town": _town_out(p.town),
                         "workers": _count_out(p.workers), "condition": ref(p.condition_index, p.condition, names)}
                        for p in ai.harvest],
            "targets": [{"target": TARGETS.get(p.target, p.target),
                         **({"creep_min": p.creep_min, "creep_max": p.creep_max, "flyers": bool(p.flyers)}
                            if p.target == wai.TARGET_CREEPS else {}),
                         "condition": ref(p.condition_index, p.condition, names)} for p in ai.targets],
            "attack": {"repeat_waves": ai.repeat_waves,
                       "minimum_group": "first_hero_only" if ai.minimum_group == aigen.FIRST_HERO_ONLY else ai.minimum_group,
                       "initial_delay": ai.initial_delay,
                       "waves": [{"group": w.group, "delay": w.delay} for w in ai.waves]},
            "groups": [{"index": g.index, "name": g.name,
                        "units": [{"id": _id_out(u.id), "quantity": _count_out(u.quantity),
                                   "maximum": _count_out(u.maximum), "condition": ref(u.condition_index, u.condition, names)}
                                  for u in g.units]} for g in ai.groups],
            "test_game": {"flags": ai.test_flags, "speed": ai.test_speed, "map": ai.test_map,
                          "players": [vars(p).copy() for p in ai.players]},
            "object_data": None if ai.object_data is None else {
                "path": ai.object_data.path, "date": ai.object_data.date,
                "kinds": [kind for kind, t in zip(EXTENSIONS, ai.object_data.tables) if t is not None]},
        }
        return doc

    def from_json(self, doc: dict, original: wai.AIData) -> wai.AIData:
        ai = copy.deepcopy(original)
        name = doc.get("name")
        if not isinstance(name, str) or not name or any(ch in name for ch in '"\\\r\n'):
            raise _bad("name", "expected a name without quotes, backslashes or line breaks (the export does not escape it)")
        ai.name, ai.race = name, _enum_in(doc.get("race"), RACES, "race")
        options = doc.get("options")
        if not isinstance(options, dict) or set(options) - set(OPTIONS) or not all(isinstance(v, bool) for v in options.values()):
            raise _bad("options", f"expected true/false for {', '.join(OPTIONS)}")
        known = sum(OPTIONS.values())
        ai.options = (original.options & ~known) | sum(bit for k, bit in OPTIONS.items() if options.get(k))
        workers = doc.get("workers")
        if not isinstance(workers, dict) or set(workers) != set(WORKERS):
            raise _bad("workers", f"expected {', '.join(WORKERS)}")
        ai.workers = [_id_in(workers[k], f"workers.{k}") for k in WORKERS]

        conditions, by_name, scripts = doc.get("conditions"), {}, set()
        if not isinstance(conditions, list):
            raise _bad("conditions", "expected a list")
        ai.conditions = []
        for i, c in enumerate(conditions):
            path = f"conditions[{i}]"
            if not isinstance(c, dict) or not isinstance(c.get("name"), str) or not c["name"]:
                raise _bad(path, "expected {index?, name, condition}")
            index = c.get("index", max([x.index for x in ai.conditions] + [-1]) + 1)
            if not isinstance(index, int) or index < 0 or any(x.index == index for x in ai.conditions):
                raise _bad(path + ".index", "expected a new non-negative index (omit it to allocate one)")
            if c["name"] in by_name or script_name(c["name"]) in scripts:
                raise _bad(path + ".name", "condition names must differ (they become gCond_ globals)")
            by_name[c["name"]] = index
            scripts.add(script_name(c["name"]))
            ai.conditions.append(wai.NamedCondition(index, self.condition_in(c.get("condition"), c["name"], path + ".condition")))
        indexes = {c.index for c in ai.conditions}

        def ref(value, path):
            return self.reference_in(value, path, by_name, indexes)

        heroes = doc.get("heroes")
        if not isinstance(heroes, list) or len(heroes) != 3:
            raise _bad("heroes", "expected 3 entries (null for none)")
        ai.heroes = []
        for i, h in enumerate(heroes):
            if h is None:
                ai.heroes.append(EMPTY)
                continue
            skills = h.get("skills") if isinstance(h, dict) else None
            if not isinstance(skills, list) or len(skills) != 3 or not all(isinstance(r, list) and len(r) == 10 for r in skills):
                raise _bad(f"heroes[{i}].skills", "expected 3 lists (hero orders 1-3) of 10 skill ids (null for none)")
            ai.heroes.append(_id_in(h.get("id"), f"heroes[{i}].id"))
            for o in range(3):
                ai.skills[i * 3 + o] = [_id_in(s, f"heroes[{i}].skills[{o}][{k}]", empty=True) for k, s in enumerate(skills[o])]
        orders = doc.get("hero_orders")
        if (not isinstance(orders, dict) or set(orders) != set(ORDERS)
                or not all(isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 100 for v in orders.values())
                or sum(orders.values()) not in (0, 100)):
            raise _bad("hero_orders", f"expected percentages 0-100 adding up to 100 for {', '.join(ORDERS)}")
        ai.hero_orders = [orders[k] for k in ORDERS]

        def entries(key, make):
            items = doc.get(key)
            if not isinstance(items, list):
                raise _bad(key, "expected a list")
            out = []
            for i, item in enumerate(items):
                if not isinstance(item, dict):
                    raise _bad(f"{key}[{i}]", "expected an object")
                out.append(make(item, f"{key}[{i}]"))
            return out

        def build(item, path):
            kind = _enum_in(item.get("type"), BUILD_TYPES, path + ".type")
            p = wai.BuildPriority(kind, b"XEIA" if kind == 2 else _id_in(item.get("id"), path + ".id", heroes=True),
                                  _town_in(item.get("town", "any"), path + ".town"))
            p.condition_index, p.condition = ref(item.get("condition"), path + ".condition")
            return p

        def harvest(item, path):
            p = wai.HarvestPriority(_enum_in(item.get("resource"), RESOURCES, path + ".resource"),
                                    _town_in(item.get("town", "any"), path + ".town"),
                                    _count_in(item.get("workers"), path + ".workers", {"all": -1, "all_not_attacking": -2}))
            p.condition_index, p.condition = ref(item.get("condition"), path + ".condition")
            return p

        def target(item, path):
            p = wai.TargetPriority(_enum_in(item.get("target"), TARGETS, path + ".target"))
            if p.target == wai.TARGET_CREEPS:
                values = [item.get(k) for k in ("creep_min", "creep_max")]
                if not all(isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 100 for v in values) or values[0] > values[1]:
                    raise _bad(path, "creeps need creep_min <= creep_max (0-100)")
                p.creep_min, p.creep_max, p.flyers = values[0], values[1], int(bool(item.get("flyers")))
            p.condition_index, p.condition = ref(item.get("condition"), path + ".condition")
            return p

        ai.build, ai.harvest, ai.targets = entries("build", build), entries("harvest", harvest), entries("targets", target)

        groups = doc.get("groups")
        if not isinstance(groups, list):
            raise _bad("groups", "expected a list")
        ai.groups = []
        for i, g in enumerate(groups):
            path = f"groups[{i}]"
            if not isinstance(g, dict) or not isinstance(g.get("name"), str) or not isinstance(g.get("units", []), list):
                raise _bad(path, "expected {index?, name, units}")
            index = g.get("index", max([x.index for x in ai.groups] + [-1]) + 1)
            if not isinstance(index, int) or index < 0 or any(x.index == index for x in ai.groups):
                raise _bad(path + ".index", "expected a new non-negative index (omit it to allocate one)")
            group = wai.AttackGroup(index, g["name"])
            for k, u in enumerate(g.get("units", [])):
                where = f"{path}.units[{k}]"
                if not isinstance(u, dict):
                    raise _bad(where, "expected {id, quantity, maximum, condition}")
                unit = wai.GroupUnit(_id_in(u.get("id"), where + ".id", heroes=True),
                                     _count_in(u.get("quantity"), where + ".quantity", {"all": -1}),
                                     _count_in(u.get("maximum", u.get("quantity")), where + ".maximum", {"all": -1}))
                unit.condition_index, unit.condition = ref(u.get("condition"), where + ".condition")
                group.units.append(unit)
            ai.groups.append(group)
        group_indexes = {g.index for g in ai.groups}

        attack = doc.get("attack")
        if not isinstance(attack, dict):
            raise _bad("attack", "expected {repeat_waves, minimum_group, initial_delay, waves}")
        for key in ("repeat_waves", "initial_delay"):
            if not isinstance(attack.get(key), int) or isinstance(attack.get(key), bool) or attack[key] < 0:
                raise _bad(f"attack.{key}", "expected a non-negative number")
        ai.repeat_waves, ai.initial_delay = attack["repeat_waves"], attack["initial_delay"]
        minimum = attack.get("minimum_group")
        if minimum == "first_hero_only":
            ai.minimum_group = aigen.FIRST_HERO_ONLY
        elif minimum in group_indexes:
            ai.minimum_group = minimum
        else:
            raise _bad("attack.minimum_group", 'expected a group index or "first_hero_only"')
        waves = attack.get("waves")
        if not isinstance(waves, list):
            raise _bad("attack.waves", "expected a list of {group, delay}")
        ai.waves = []
        for i, w in enumerate(waves):
            if not isinstance(w, dict) or w.get("group") not in group_indexes or not isinstance(w.get("delay", 0), int) \
                    or w.get("delay", 0) < 0:
                raise _bad(f"attack.waves[{i}]", "expected {group: a group index, delay: seconds}")
            ai.waves.append(wai.Wave(w["group"], w.get("delay", 0)))
        if ai.repeat_waves > len(ai.waves):
            raise _bad("attack.repeat_waves", "cannot repeat more waves than there are")

        test = doc.get("test_game")
        if not isinstance(test, dict) or not isinstance(test.get("map", ""), str):
            raise _bad("test_game", "expected {flags, speed, map, players}")
        try:
            ai.test_flags, ai.test_speed, ai.test_map = int(test["flags"]), int(test["speed"]), test["map"]
            ai.players = [wai.Player(**p) for p in test["players"]]
        except (KeyError, TypeError, ValueError) as e:
            raise _bad("test_game", f"expected flags, speed, map and players with index, team, race, color, handicap, ai, "
                                    f"difficulty, script ({e})") from e
        return ai


# ---- tools -----------------------------------------------------------------------------------------------------
def ai_get(source, catalog) -> dict:
    td = aigen.ai_trigger_data(catalog)
    ai = load(source, td)
    if ai is None:
        raise ToolError("no_ai", f"{source} has no AI data", hint="ai_edit creates it")
    return _View(td).to_json(ai)


def ai_edit(source, catalog, ops: list) -> dict:
    td = aigen.ai_trigger_data(catalog)
    before = load(source, td)
    original = before or new_ai(Path(str(getattr(source, "source", source))).stem)
    view = _View(td)
    doc = view.to_json(original)
    for i, op in enumerate(ops):
        root = str(op.get("path", "") if isinstance(op, dict) else "").split(".")[0].split("[")[0]
        if root in READ_ONLY:
            raise ToolError("bad_op", f"ops[{i}]: {root} is read-only", hint=_HINT, op_index=i)
    after = view.from_json(apply_ops(doc, ops), original)
    data = wai.serialize(after)
    old = wai.serialize(before) if before is not None else None
    result = {"changed": data != old, "created": before is None, "warnings": []}
    if data != old:
        if isinstance(source, MapProject):
            source.write(MAP_FILE, data)
        else:
            result["backup"] = write_file(Path(source), data)
    return result


def ai_export(source, catalog, dest=None, project: MapProject | None = None, player: int | None = None,
              import_path: str | None = None) -> dict:
    td = aigen.ai_trigger_data(catalog)
    ai = load(source, td)
    if ai is None:
        raise ToolError("no_ai", f"{source} has no AI data", hint="ai_edit creates it")
    script = aigen.export(ai, td)
    text = script.encode("utf-8")
    check = validate_ai(script, catalog)   # the AI Editor compiles its export too
    result = {"size": len(text), "validation": {"ok": check["ok"], "errors": check["errors"][:20]}, "warnings": []}
    if project is None:
        if dest is None and isinstance(source, MapProject):
            raise ToolError("bad_value", "dest: give a file path, or map to import the script into a map", path="dest")
        target = Path(dest) if dest else Path(source).with_suffix(".ai")
        result["backup"], result["file"] = write_file(target, text), str(target)
        return result
    stem = script_name(Path(str(source)).stem if not isinstance(source, MapProject) else ai.name) or "ai"
    import_path = import_path or f"war3mapImported\\{stem}.ai"
    imports_edit(project, [{"op": "add", "path": import_path, "content_base64": base64.b64encode(text).decode()}])
    result["import"] = import_path
    if player is not None:
        from .triggers import triggers_edit

        if not isinstance(player, int) or isinstance(player, bool) or not 0 <= player <= 23:
            raise _bad("player", "expected a player number 0-23 (0 = Player 1)")
        action = "StartMeleeAI" if ai.options & OPTIONS["melee"] else "StartCampaignAI"
        name = f"Start AI {stem}"
        triggers_edit(project, catalog, [{"op": "trigger", "name": name, "events": [{"fn": "MapInitializationEvent"}],
                                          "actions": [{"fn": action, "args": [{"preset": f"Player{player:02d}"},
                                                                              import_path]}]}])
        result["trigger"] = name
        result["warnings"].append("map_save rebuilds the map script with the new trigger")
    return result
