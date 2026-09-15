"""war3map.mmp — minimap icons the World Editor computes on save."""
from dataclasses import dataclass, field

from .binary import FormatError, Reader, Writer

VERSIONS = (0,)


@dataclass
class Icon:
    kind: int  # 0 gold mine, 1 neutral building, 2 start location
    x: int  # minimap pixels
    y: int
    color: bytes  # b, g, r, a


@dataclass
class Minimap:
    version: int = 0
    icons: list[Icon] = field(default_factory=list)


def parse(data: bytes) -> Minimap:
    r = Reader(data)
    mm = Minimap(r.i32())
    if mm.version not in VERSIONS:
        raise FormatError(f"unsupported minimap icons version {mm.version}")
    mm.icons = [Icon(r.i32(), r.i32(), r.i32(), r.raw(4)) for _ in range(r.count(item_size=16))]
    r.done()
    return mm


def serialize(mm: Minimap) -> bytes:
    if mm.version not in VERSIONS:
        raise FormatError(f"unsupported minimap icons version {mm.version}")
    w = Writer()
    w.i32(mm.version)
    w.i32(len(mm.icons))
    for icon in mm.icons:
        for v in (icon.kind, icon.x, icon.y):
            w.i32(v)
        w.raw(icon.color)
    return w.getvalue()
