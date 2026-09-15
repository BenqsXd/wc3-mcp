"""war3map.w3r — regions placed in the editor (rects with optional weather and ambient sound)."""
from dataclasses import dataclass, field

from .binary import FormatError, Reader, Writer

VERSIONS = (5, 7)
NO_ID = b"\0\0\0\0"


@dataclass
class Region:
    left: float
    bottom: float
    right: float
    top: float
    name: str
    index: int
    weather: bytes = NO_ID
    ambient_sound: str = ""
    color: bytes = b"\xff\xff\xff\xff"  # b, g, r, 0xFF
    extra: bytes = bytes(8)  # v7+; zero in every local map


@dataclass
class RegionFile:
    version: int = 5
    regions: list[Region] = field(default_factory=list)


def _check(version: int) -> None:
    if version not in VERSIONS:
        raise FormatError(f"unsupported regions version {version}")


def parse(data: bytes) -> RegionFile:
    r = Reader(data)
    rf = RegionFile(r.i32())
    _check(rf.version)
    for _ in range(r.count(item_size=30)):
        left, bottom, right, top = r.f32(), r.f32(), r.f32(), r.f32()
        rf.regions.append(Region(left, bottom, right, top, r.cstr(), r.i32(), r.raw(4), r.cstr(), r.raw(4),
                                 r.raw(8) if rf.version >= 7 else bytes(8)))
    r.done()
    return rf


def serialize(rf: RegionFile) -> bytes:
    _check(rf.version)
    w = Writer()
    w.i32(rf.version)
    w.i32(len(rf.regions))
    for g in rf.regions:
        for v in (g.left, g.bottom, g.right, g.top):
            w.f32(v)
        w.cstr(g.name)
        w.i32(g.index)
        w.raw(g.weather)
        w.cstr(g.ambient_sound)
        w.raw(g.color)
        if rf.version >= 7:
            w.raw(g.extra)
    return w.getvalue()
