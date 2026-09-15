"""AI Editor data: .wai files and war3map.wai (format version 2). Conditions use the trigger file's parameter
encoding, so parsing needs each function's argument count (UI/TriggerData.txt plus UI/AIEditorData.txt).
Byte-exact on the game's 7 .wai files."""
from collections.abc import Callable
from dataclasses import dataclass, field

from . import objmods, wtg
from .binary import FormatError, Reader, Writer

VERSION = 2
CONDITION_KIND = 1                         # a condition's top function is a trigger condition (the editor rejects calls)
PRIORITY_BUILD, PRIORITY_HARVEST, PRIORITY_TARGET = 0, 1, 2
TARGET_CREEPS = 5
NO_CONDITION, CUSTOM_CONDITION = -1, -2    # condition_index of priorities and group units
OBJECT_DATA_KINDS = objmods.EXTENSIONS     # order of the embedded object data tables

ArgCount = Callable[[int, str], "int | None"]


@dataclass
class Condition:
    name: str = ""
    function: str | None = None            # None: no condition
    params: list[wtg.Param] = field(default_factory=list)
    has_params: int = 1
    unknown: int = 0


@dataclass
class NamedCondition:
    index: int
    condition: Condition


@dataclass
class BuildPriority:
    kind: int                              # 0 unit, 1 upgrade, 2 expansion town (id XEIA)
    id: bytes
    town: int                              # 0 main, 1-9 expansion, -3..-11 mine, -1 any
    condition_index: int = NO_CONDITION
    condition: Condition = field(default_factory=Condition)


@dataclass
class HarvestPriority:
    resource: int                          # 0 gold, 1 lumber
    town: int
    workers: int                           # count, -1 all, -2 all not attacking
    condition_index: int = NO_CONDITION
    condition: Condition = field(default_factory=Condition)


@dataclass
class TargetPriority:
    target: int                            # 0 ally target .. 5 creep camp, 6 zeppelin
    creep_min: int = 0
    creep_max: int = 0
    flyers: int = 0
    condition_index: int = NO_CONDITION
    condition: Condition = field(default_factory=Condition)


@dataclass
class GroupUnit:
    id: bytes                              # unit id, or 1HIA / 2HIA / 3HIA for the heroes
    quantity: int                          # -1 all
    maximum: int
    condition_index: int = NO_CONDITION
    condition: Condition = field(default_factory=Condition)


@dataclass
class AttackGroup:
    index: int
    name: str
    units: list[GroupUnit] = field(default_factory=list)


@dataclass
class Wave:
    group: int
    delay: int


@dataclass
class Player:
    index: int
    team: int
    race: int
    color: int
    handicap: int
    ai: int
    difficulty: int
    script: str = ""


@dataclass
class ObjectData:
    path: str
    date: str
    version: int = 1
    tables: list[objmods.ObjectMods | None] = field(default_factory=lambda: [None] * len(OBJECT_DATA_KINDS))


@dataclass
class AIData:
    version: int = VERSION
    name: str = ""
    race: int = 0
    options: int = 0
    workers: list[bytes] = field(default_factory=list)   # gold worker, lumber worker, base building, mine building
    condition_marker: int = 7
    conditions: list[NamedCondition] = field(default_factory=list)
    heroes: list[bytes] = field(default_factory=lambda: [b"\0\0\0\0"] * 3)
    hero_orders: list[int] = field(default_factory=lambda: [0] * 6)
    skills: list[list[bytes]] = field(default_factory=lambda: [[b"\0\0\0\0"] * 10 for _ in range(9)])
    build: list = field(default_factory=list)            # priorities of any type, in file order per list
    harvest: list = field(default_factory=list)
    targets: list = field(default_factory=list)
    repeat_waves: int = 0
    minimum_group: int = 0
    initial_delay: int = 0
    groups: list[AttackGroup] = field(default_factory=list)
    waves: list[Wave] = field(default_factory=list)
    test_marker: int = 1
    test_flags: int = 0
    test_speed: int = 0
    test_map: str = ""
    players: list[Player] = field(default_factory=list)
    object_data: ObjectData | None = None


# ---- reading ---------------------------------------------------------------------------------------------------
def _condition(r: Reader, count: ArgCount) -> Condition:
    c = Condition(r.cstr())
    has = r.u32()
    if has == 0:
        return c
    if has != 1:
        raise FormatError(f"condition {c.name!r}: flag {has} at offset {r.pos - 4}")
    c.function = r.cstr()
    c.has_params = r.u32()
    n = count(CONDITION_KIND, c.function)
    if n is None:
        raise FormatError(f"unknown AI condition function {c.function!r}")
    c.params = [wtg._param(r, count) for _ in range(n)] if c.has_params else []
    c.unknown = r.u32()
    return c


def _priority(r: Reader, count: ArgCount):
    kind = r.i32()
    if kind == PRIORITY_BUILD:
        p = BuildPriority(r.i32(), r.raw(4), r.i32())
    elif kind == PRIORITY_HARVEST:
        p = HarvestPriority(r.i32(), r.i32(), r.i32())
    elif kind == PRIORITY_TARGET:
        p = TargetPriority(r.i32())
        if p.target == TARGET_CREEPS:
            p.creep_min, p.creep_max, p.flyers = r.i32(), r.i32(), r.i32()
    else:
        raise FormatError(f"unknown priority type {kind} at offset {r.pos - 4}")
    p.condition_index, p.condition = r.i32(), _condition(r, count)
    return p


def parse(data: bytes, count: ArgCount) -> AIData:
    r = Reader(data)
    ai = AIData(r.i32())
    if ai.version != VERSION:
        raise FormatError(f"AI data version {ai.version} is not supported (only {VERSION})")
    ai.name, ai.race, ai.options = r.cstr(), r.i32(), r.u32()
    ai.workers = [r.raw(4) for _ in range(r.count(item_size=4))]
    n = r.count(item_size=9)
    ai.condition_marker = r.i32()
    ai.conditions = [NamedCondition(r.i32(), _condition(r, count)) for _ in range(n)]
    ai.heroes = [r.raw(4) for _ in range(3)]
    ai.hero_orders = [r.i32() for _ in range(6)]
    ai.skills = [[r.raw(4) for _ in range(10)] for _ in range(9)]
    for name in ("build", "harvest", "targets"):
        setattr(ai, name, [_priority(r, count) for _ in range(r.count(item_size=13))])
    ai.repeat_waves, ai.minimum_group, ai.initial_delay = r.i32(), r.i32(), r.i32()
    for _ in range(r.count(item_size=9)):
        group = AttackGroup(r.i32(), r.cstr())
        for _ in range(r.count(item_size=21)):
            group.units.append(GroupUnit(r.raw(4), r.i32(), r.i32(), r.i32(), _condition(r, count)))
        ai.groups.append(group)
    ai.waves = [Wave(r.i32(), r.i32()) for _ in range(r.count(item_size=8))]
    ai.test_marker, ai.test_flags, ai.test_speed, ai.test_map = r.i32(), r.i32(), r.i32(), r.cstr()
    ai.players = [Player(*(r.i32() for _ in range(7)), r.cstr()) for _ in range(r.count(item_size=29))]
    has_objects = r.i32()
    if has_objects:
        ai.object_data = ObjectData(r.cstr(), r.cstr(), r.i32())
        for i, ext in enumerate(OBJECT_DATA_KINDS):
            if r.i32():
                ai.object_data.tables[i] = objmods.read(r, ext in objmods.LEVEL_EXTENSIONS)
    r.done()
    return ai


# ---- writing ---------------------------------------------------------------------------------------------------
def _write_condition(w: Writer, c: Condition) -> None:
    w.cstr(c.name)
    w.u32(c.function is not None)
    if c.function is None:
        return
    w.cstr(c.function)
    w.u32(c.has_params)
    for p in c.params:
        wtg._write_param(w, p)
    w.u32(c.unknown)


def _four(b: bytes, what: str) -> bytes:
    if len(b) != 4:
        raise FormatError(f"{what} must be exactly 4 bytes")
    return b


def _write_priority(w: Writer, p) -> None:
    if isinstance(p, BuildPriority):
        w.i32(PRIORITY_BUILD)
        w.i32(p.kind)
        w.raw(_four(p.id, "build priority id"))
        w.i32(p.town)
    elif isinstance(p, HarvestPriority):
        for v in (PRIORITY_HARVEST, p.resource, p.town, p.workers):
            w.i32(v)
    else:
        w.i32(PRIORITY_TARGET)
        w.i32(p.target)
        if p.target == TARGET_CREEPS:
            for v in (p.creep_min, p.creep_max, p.flyers):
                w.i32(v)
    w.i32(p.condition_index)
    _write_condition(w, p.condition)


def serialize(ai: AIData) -> bytes:
    if ai.version != VERSION:
        raise FormatError(f"AI data version {ai.version} cannot be written (only {VERSION})")
    if len(ai.heroes) != 3 or len(ai.hero_orders) != 6 or len(ai.skills) != 9 or any(len(s) != 10 for s in ai.skills):
        raise FormatError("AI data needs 3 heroes, 6 hero orders and 9 rows of 10 skills")
    w = Writer()
    w.i32(ai.version)
    w.cstr(ai.name)
    w.i32(ai.race)
    w.u32(ai.options)
    w.i32(len(ai.workers))
    for b in ai.workers:
        w.raw(_four(b, "worker id"))
    w.i32(len(ai.conditions))
    w.i32(ai.condition_marker)
    for nc in ai.conditions:
        w.i32(nc.index)
        _write_condition(w, nc.condition)
    for b in ai.heroes:
        w.raw(_four(b, "hero id"))
    for v in ai.hero_orders:
        w.i32(v)
    for row in ai.skills:
        for b in row:
            w.raw(_four(b, "skill id"))
    for entries in (ai.build, ai.harvest, ai.targets):
        w.i32(len(entries))
        for p in entries:
            _write_priority(w, p)
    for v in (ai.repeat_waves, ai.minimum_group, ai.initial_delay, len(ai.groups)):
        w.i32(v)
    for g in ai.groups:
        w.i32(g.index)
        w.cstr(g.name)
        w.i32(len(g.units))
        for u in g.units:
            w.raw(_four(u.id, "group unit id"))
            for v in (u.quantity, u.maximum, u.condition_index):
                w.i32(v)
            _write_condition(w, u.condition)
    w.i32(len(ai.waves))
    for wave in ai.waves:
        w.i32(wave.group)
        w.i32(wave.delay)
    for v in (ai.test_marker, ai.test_flags, ai.test_speed):
        w.i32(v)
    w.cstr(ai.test_map)
    w.i32(len(ai.players))
    for p in ai.players:
        for v in (p.index, p.team, p.race, p.color, p.handicap, p.ai, p.difficulty):
            w.i32(v)
        w.cstr(p.script)
    w.i32(ai.object_data is not None)
    if ai.object_data is not None:
        od = ai.object_data
        if len(od.tables) != len(OBJECT_DATA_KINDS):
            raise FormatError(f"object data needs {len(OBJECT_DATA_KINDS)} tables (None for absent ones)")
        w.cstr(od.path)
        w.cstr(od.date)
        w.i32(od.version)
        for table in od.tables:
            w.i32(table is not None)
            if table is not None:
                objmods.write(w, table)
    return w.getvalue()
