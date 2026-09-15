"""war3mapUnits.doo — placed units, items and start locations."""
from dataclasses import dataclass, field

from .binary import FormatError, Reader, Writer
from .doo import ItemSet, read_header, read_item_sets, read_placement, write_header, write_item_sets, write_placement

VERSIONS = {(8, 9), (8, 11), (12, 9), (12, 11), (13, 9), (13, 11)}
RANDOM_DATA_SIZE = {0: 4, 1: 8}  # 0: 3-byte level + item class; 1: random group index + position


@dataclass
class Unit:
    id: bytes
    variation: int
    x: float
    y: float
    z: float
    angle: float  # radians
    scale: list[float]
    skin: bytes
    flags: int
    owner: int
    unknown_a: int = 0
    unknown_b: int = 0
    hp: int = -1  # -1 default
    mp: int = -1
    item_table: int = -1  # subversion 11+
    item_sets: list[ItemSet] = field(default_factory=list)
    gold: int = 12500
    target_acquisition: float = -1.0  # -1 normal, -2 camp
    hero_level: int = 1
    strength: int = 0  # subversion 11+
    agility: int = 0
    intelligence: int = 0
    inventory: list[tuple[int, bytes]] = field(default_factory=list)  # (slot, item id)
    abilities: list[tuple[bytes, int, int]] = field(default_factory=list)  # (id, autocast on, level)
    random_flag: int = -1  # 0/1 carry random_data, 2 random_units, other values nothing
    random_data: bytes = b""
    random_units: list[tuple[bytes, int]] = field(default_factory=list)  # (unit id, chance)
    color: int = -1
    waygate: int = -1  # region index
    editor_id: int = 0
    v12_value: int = -1
    v12_ints: list[int] = field(default_factory=lambda: [0, 0])


@dataclass
class UnitFile:
    version: int = 8
    subversion: int = 11
    units: list[Unit] = field(default_factory=list)


def parse(data: bytes) -> UnitFile:
    r = Reader(data)
    uf = UnitFile(*read_header(r, VERSIONS, "units"))
    for _ in range(r.count(item_size=95)):
        u = Unit(*read_placement(r), 0, 0)
        if uf.version >= 12:
            u.v12_value = r.i32()
        u.flags, u.owner, u.unknown_a, u.unknown_b, u.hp, u.mp = r.u8(), r.i32(), r.u8(), r.u8(), r.i32(), r.i32()
        if uf.subversion >= 11:
            u.item_table = r.i32()
        u.item_sets = read_item_sets(r)
        u.gold, u.target_acquisition, u.hero_level = r.i32(), r.f32(), r.i32()
        if uf.subversion >= 11:
            u.strength, u.agility, u.intelligence = r.i32(), r.i32(), r.i32()
        u.inventory = [(r.i32(), r.raw(4)) for _ in range(r.count(item_size=8))]
        u.abilities = [(r.raw(4), r.i32(), r.i32()) for _ in range(r.count(item_size=12))]
        u.random_flag = r.i32()
        if u.random_flag == 2:
            u.random_units = [(r.raw(4), r.i32()) for _ in range(r.count(item_size=8))]
        else:
            u.random_data = r.raw(RANDOM_DATA_SIZE.get(u.random_flag, 0))
        u.color, u.waygate, u.editor_id = r.i32(), r.i32(), r.i32()
        if uf.version >= 12:
            u.v12_ints = [r.i32(), r.i32()]
            if r.i32() != 0:
                raise FormatError(f"unit {u.editor_id}: extra records after the unit are not supported")
        uf.units.append(u)
    r.done()
    return uf


def _check(uf: UnitFile, u: Unit) -> None:
    lost = []
    if uf.subversion < 11 and (u.item_table != -1 or u.strength or u.agility or u.intelligence):
        lost.append("item table and hero attributes need subversion 11")
    if uf.version < 12 and (u.v12_value != -1 or u.v12_ints != [0, 0]):
        lost.append(f"version 12 fields in a version {uf.version} file")
    size = 0 if u.random_flag == 2 else RANDOM_DATA_SIZE.get(u.random_flag, 0)
    if len(u.random_data) != size or (u.random_units and u.random_flag != 2):
        lost.append(f"random flag {u.random_flag} takes {size} data bytes" + ("" if u.random_flag == 2 else
                                                                               " and no unit list"))
    if lost:
        raise FormatError(f"unit {u.editor_id}: " + "; ".join(lost))


def serialize(uf: UnitFile) -> bytes:
    w = Writer()
    write_header(w, uf.version, uf.subversion, VERSIONS, "units")
    w.i32(len(uf.units))
    for u in uf.units:
        _check(uf, u)
        write_placement(w, u)
        if uf.version >= 12:
            w.i32(u.v12_value)
        w.u8(u.flags)
        w.i32(u.owner)
        w.u8(u.unknown_a)
        w.u8(u.unknown_b)
        w.i32(u.hp)
        w.i32(u.mp)
        if uf.subversion >= 11:
            w.i32(u.item_table)
        write_item_sets(w, u.item_sets)
        w.i32(u.gold)
        w.f32(u.target_acquisition)
        w.i32(u.hero_level)
        if uf.subversion >= 11:
            for v in (u.strength, u.agility, u.intelligence):
                w.i32(v)
        w.i32(len(u.inventory))
        for slot, item in u.inventory:
            w.i32(slot)
            w.raw(item)
        w.i32(len(u.abilities))
        for ability, autocast, level in u.abilities:
            w.raw(ability)
            w.i32(autocast)
            w.i32(level)
        w.i32(u.random_flag)
        if u.random_flag == 2:
            w.i32(len(u.random_units))
            for unit_id, chance in u.random_units:
                w.raw(unit_id)
                w.i32(chance)
        else:
            w.raw(u.random_data)
        for v in (u.color, u.waygate, u.editor_id):
            w.i32(v)
        if uf.version >= 12:
            for v in (*u.v12_ints, 0):
                w.i32(v)
    return w.getvalue()
