"""war3map.wpm — the pathing map the World Editor computes on save: 4 × 4 cells per terrain tile."""
from dataclasses import dataclass

from .binary import FormatError, Reader, Writer

MAGIC = b"MP3W"
VERSIONS = (0,)


@dataclass
class PathingMap:
    version: int
    width: int
    height: int
    cells: bytearray  # row-major from the bottom-left; 0x02 unwalkable, 0x04 unflyable, 0x08 unbuildable, 0x20 blight


def parse(data: bytes) -> PathingMap:
    r = Reader(data)
    if r.raw(4) != MAGIC:
        raise FormatError("pathing map: bad magic")
    pm = PathingMap(r.i32(), r.i32(), r.i32(), bytearray())
    if pm.version not in VERSIONS or pm.width < 0 or pm.height < 0:
        raise FormatError(f"unsupported pathing map version {pm.version} or size {pm.width}x{pm.height}")
    pm.cells = bytearray(r.raw(pm.width * pm.height))
    r.done()
    return pm


def serialize(pm: PathingMap) -> bytes:
    if pm.version not in VERSIONS or len(pm.cells) != pm.width * pm.height:
        raise FormatError(f"pathing map version {pm.version} with {len(pm.cells)} cells for {pm.width}x{pm.height}")
    w = Writer()
    w.raw(MAGIC)
    for v in (pm.version, pm.width, pm.height):
        w.i32(v)
    w.raw(bytes(pm.cells))
    return w.getvalue()
