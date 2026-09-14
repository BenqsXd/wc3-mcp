"""Object modification files: war3map.w3u/.w3t/.w3b/.w3d/.w3a/.w3h/.w3q and their war3mapSkin.* twins.
Versions 2 and 3; byte-exact on every local map."""
from dataclasses import dataclass, field

from .binary import FormatError, Reader, Writer

INT, REAL, UNREAL, STRING = 0, 1, 2, 3
ZERO_ID = b"\0\0\0\0"
EXTENSIONS = ("w3u", "w3t", "w3b", "w3d", "w3a", "w3h", "w3q")
LEVEL_EXTENSIONS = frozenset({"w3d", "w3a", "w3q"})  # records carry a level (doodads: variation) and a data pointer


@dataclass
class Mod:
    id: bytes
    var_type: int
    value: int | float | str
    level: int = 0
    pointer: int = 0
    end: bytes = ZERO_ID


@dataclass
class ObjectEntry:
    base_id: bytes
    new_id: bytes = ZERO_ID
    mods: list[Mod] = field(default_factory=list)
    set_flag: int = 0  # v3: flag of the single modification set (always 0 locally)


@dataclass
class ObjectMods:
    version: int = 3
    levels: bool = False
    original: list[ObjectEntry] = field(default_factory=list)
    custom: list[ObjectEntry] = field(default_factory=list)
    trailing: bytes = b""


def parse(data: bytes, levels: bool) -> ObjectMods:
    r = Reader(data)
    version = r.i32()
    if version not in (2, 3):
        raise FormatError(f"unsupported object data version {version}")
    om = ObjectMods(version, levels)
    for table in (om.original, om.custom):
        for _ in range(r.count(item_size=12)):
            entry = ObjectEntry(r.raw(4), r.raw(4))
            if version >= 3:
                sets = r.i32()
                if sets != 1:
                    # ponytail: only single-set objects exist locally; add multi-set support when a real file has one
                    raise FormatError(f"object {entry.base_id!r}: {sets} modification sets are not supported")
                entry.set_flag = r.i32()
            for _ in range(r.count(item_size=12)):
                mod = Mod(r.raw(4), r.i32(), 0)
                if levels:
                    mod.level, mod.pointer = r.i32(), r.i32()
                if mod.var_type == INT:
                    mod.value = r.i32()
                elif mod.var_type in (REAL, UNREAL):
                    mod.value = r.f32()
                elif mod.var_type == STRING:
                    mod.value = r.cstr()
                else:
                    raise FormatError(f"unknown value type {mod.var_type} at offset {r.pos - 4}")
                mod.end = r.raw(4)
                entry.mods.append(mod)
            table.append(entry)
    om.trailing = r.rest()
    return om


def _four(b: bytes, what: str) -> bytes:
    if len(b) != 4:
        raise FormatError(f"{what} must be exactly 4 bytes")
    return b


def serialize(om: ObjectMods) -> bytes:
    w = Writer()
    w.i32(om.version)
    for table in (om.original, om.custom):
        w.i32(len(table))
        for entry in table:
            w.raw(_four(entry.base_id, "base id"))
            w.raw(_four(entry.new_id, "new id"))
            if om.version >= 3:
                w.i32(1)
                w.i32(entry.set_flag)
            w.i32(len(entry.mods))
            for mod in entry.mods:
                w.raw(_four(mod.id, "modification id"))
                w.i32(mod.var_type)
                if om.levels:
                    w.i32(mod.level)
                    w.i32(mod.pointer)
                if mod.var_type == INT:
                    w.i32(mod.value)
                elif mod.var_type in (REAL, UNREAL):
                    w.f32(mod.value)
                elif mod.var_type == STRING:
                    w.cstr(mod.value)
                else:
                    raise FormatError(f"unknown value type {mod.var_type}")
                w.raw(_four(mod.end, "end token"))
    w.raw(om.trailing)
    return w.getvalue()
