"""war3map.doo — placed doodads and destructibles, plus the cliff/terrain doodads the editor places itself.
Also the header, placement and item-drop helpers shared with war3mapUnits.doo."""
from dataclasses import dataclass, field

from .binary import FormatError, Reader, Writer

MAGIC = b"W3do"
VERSIONS = {(8, 11), (12, 11), (13, 11)}
ENTRY_SIZE = 36
ItemSet = list[tuple[bytes, int]]  # (item id, chance percent); b"\0\0\0\0" = no item


@dataclass
class Doodad:
    id: bytes
    variation: int
    x: float
    y: float
    z: float
    angle: float  # radians
    scale: list[float]
    skin: bytes
    flags: int  # 0 invisible non-solid, 1 visible non-solid, 2 visible solid
    life: int  # percent
    item_table: int = -1
    item_sets: list[ItemSet] = field(default_factory=list)
    editor_id: int = 0
    v12_value: int = -1
    v13_value: int = -1
    v12_ints: list[int] = field(default_factory=lambda: [0, 0])
    entries: list[bytes] = field(default_factory=list)  # v12+ 36-byte records; colour-bearing, meaning unknown


@dataclass
class SpecialDoodad:
    id: bytes
    z: int
    x: int  # terrain corner column
    y: int


@dataclass
class DoodadFile:
    version: int = 8
    subversion: int = 11
    doodads: list[Doodad] = field(default_factory=list)
    special_version: int = 0
    specials: list[SpecialDoodad] = field(default_factory=list)


def read_header(r: Reader, versions: set, what: str) -> tuple[int, int]:
    if r.raw(4) != MAGIC:
        raise FormatError(f"{what}: bad magic")
    version, subversion = r.i32(), r.i32()
    if (version, subversion) not in versions:
        raise FormatError(f"unsupported {what} version {version}/{subversion}")
    return version, subversion


def write_header(w: Writer, version: int, subversion: int, versions: set, what: str) -> None:
    if (version, subversion) not in versions:
        raise FormatError(f"unsupported {what} version {version}/{subversion}")
    w.raw(MAGIC)
    w.i32(version)
    w.i32(subversion)


def read_placement(r: Reader) -> tuple:
    """id, variation, x, y, z, angle, [scale x, y, z], skin"""
    return r.raw(4), r.i32(), r.f32(), r.f32(), r.f32(), r.f32(), [r.f32(), r.f32(), r.f32()], r.raw(4)


def write_placement(w: Writer, o) -> None:
    w.raw(o.id)
    w.i32(o.variation)
    for v in (o.x, o.y, o.z, o.angle, *o.scale):
        w.f32(v)
    w.raw(o.skin)


def read_item_sets(r: Reader) -> list[ItemSet]:
    return [[(r.raw(4), r.i32()) for _ in range(r.count(item_size=8))] for _ in range(r.count(item_size=4))]


def write_item_sets(w: Writer, sets: list[ItemSet]) -> None:
    w.i32(len(sets))
    for item_set in sets:
        w.i32(len(item_set))
        for item, chance in item_set:
            w.raw(item)
            w.i32(chance)


def parse(data: bytes) -> DoodadFile:
    r = Reader(data)
    df = DoodadFile(*read_header(r, VERSIONS, "doodads"))
    for _ in range(r.count(item_size=54)):
        d = Doodad(*read_placement(r), 0, 0)
        if df.version >= 12:
            d.v12_value = r.i32()
        d.flags, d.life, d.item_table = r.u8(), r.u8(), r.i32()
        d.item_sets = read_item_sets(r)
        if df.version >= 13:
            d.v13_value = r.i32()
        d.editor_id = r.i32()
        if df.version >= 12:
            d.v12_ints = [r.i32(), r.i32()]
            d.entries = [r.raw(ENTRY_SIZE) for _ in range(r.count(item_size=ENTRY_SIZE))]
        df.doodads.append(d)
    df.special_version = r.i32()
    df.specials = [SpecialDoodad(r.raw(4), r.i32(), r.i32(), r.i32()) for _ in range(r.count(item_size=16))]
    r.done()
    return df


def serialize(df: DoodadFile) -> bytes:
    w = Writer()
    write_header(w, df.version, df.subversion, VERSIONS, "doodads")
    w.i32(len(df.doodads))
    for d in df.doodads:
        if (df.version < 12 and (d.entries or d.v12_value != -1 or d.v12_ints != [0, 0])
                or df.version < 13 and d.v13_value != -1 or any(len(e) != ENTRY_SIZE for e in d.entries)):
            raise FormatError(f"doodad {d.editor_id}: data that doodad file version {df.version} cannot store")
        write_placement(w, d)
        if df.version >= 12:
            w.i32(d.v12_value)
        w.u8(d.flags)
        w.u8(d.life)
        w.i32(d.item_table)
        write_item_sets(w, d.item_sets)
        if df.version >= 13:
            w.i32(d.v13_value)
        w.i32(d.editor_id)
        if df.version >= 12:
            for v in (*d.v12_ints, len(d.entries)):
                w.i32(v)
            for e in d.entries:
                w.raw(e)
    w.i32(df.special_version)
    w.i32(len(df.specials))
    for s in df.specials:
        w.raw(s.id)
        for v in (s.z, s.x, s.y):
            w.i32(v)
    return w.getvalue()
