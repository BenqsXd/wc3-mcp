"""war3map.w3e — terrain: tileset, ground and cliff tile lists and the corner grid (height, water, texture, flags,
variations, cliff texture and layer). Corners are row-major from the bottom-left."""
import struct
from dataclasses import dataclass

from .binary import FormatError, Reader, Writer

MAGIC = b"W3E!"
VERSIONS = (11, 12)
_CORNER = {11: struct.Struct("<hHBBB"), 12: struct.Struct("<hHHBB")}
_TEXTURE_BITS = {11: 4, 12: 6}  # texture index width; the flags follow it
FLAG_NAMES = ("ramp", "blight", "water", "boundary")
LIMITS = {"water_level": 0x3FFF, "edge": 3, "ground_variation": 31, "cliff_variation": 7, "cliff_texture": 15,
          "layer": 15}


@dataclass
class Terrain:
    version: int
    tileset: str
    custom_tileset: int
    tiles: list[bytes]
    cliff_tiles: list[bytes]
    width: int
    height: int
    offset_x: float
    offset_y: float
    heights: list[int]
    water: list[int]
    textures: list[int]
    variations: list[int]
    cliffs: list[int]


def parse(data: bytes) -> Terrain:
    r = Reader(data)
    if r.raw(4) != MAGIC:
        raise FormatError("terrain: bad magic")
    version = r.i32()
    if version not in VERSIONS:
        raise FormatError(f"unsupported terrain version {version}")
    tileset, custom = chr(r.u8()), r.i32()
    tiles = [r.raw(4) for _ in range(r.count(item_size=4))]
    cliff_tiles = [r.raw(4) for _ in range(r.count(item_size=4))]
    width, height, offset_x, offset_y = r.i32(), r.i32(), r.f32(), r.f32()
    corner_struct = _CORNER[version]
    if width < 0 or height < 0:
        raise FormatError(f"terrain: bad size {width}x{height}")
    columns = list(zip(*corner_struct.iter_unpack(r.raw(corner_struct.size * width * height)))) or [()] * 5
    r.done()
    return Terrain(version, tileset, custom, tiles, cliff_tiles, width, height, offset_x, offset_y,
                   *(list(c) for c in columns))


def serialize(t: Terrain) -> bytes:
    if t.version not in VERSIONS:
        raise FormatError(f"unsupported terrain version {t.version}")
    n = t.width * t.height
    columns = (t.heights, t.water, t.textures, t.variations, t.cliffs)
    if any(len(c) != n for c in columns):
        raise FormatError(f"terrain of {t.width}x{t.height} needs {n} values in every corner list")
    w = Writer()
    w.raw(MAGIC)
    w.i32(t.version)
    w.u8(ord(t.tileset))
    w.i32(t.custom_tileset)
    for ids in (t.tiles, t.cliff_tiles):
        w.i32(len(ids))
        for tile in ids:
            w.raw(tile)
    w.i32(t.width)
    w.i32(t.height)
    w.f32(t.offset_x)
    w.f32(t.offset_y)
    try:
        w.raw(b"".join(map(_CORNER[t.version].pack, *columns)))
    except struct.error as e:
        raise FormatError(f"terrain corner value out of range: {e}") from e
    return w.getvalue()


def _index(t: Terrain, x: int, y: int) -> int:
    if not (0 <= x < t.width and 0 <= y < t.height):
        raise IndexError(f"corner ({x}, {y}) is outside the {t.width}x{t.height} terrain")
    return y * t.width + x


def corner(t: Terrain, x: int, y: int) -> dict:
    i = _index(t, x, y)
    bits = _TEXTURE_BITS[t.version]
    tex, var, cliff, water = t.textures[i], t.variations[i], t.cliffs[i], t.water[i]
    out = {"height": t.heights[i], "water_level": water & 0x3FFF, "edge": water >> 14,
           "texture": tex & ((1 << bits) - 1)}
    out.update({name: bool(tex >> (bits + k) & 1) for k, name in enumerate(FLAG_NAMES)})
    out.update({"ground_variation": var & 31, "cliff_variation": var >> 5, "cliff_texture": cliff >> 4,
                "layer": cliff & 15})
    return out


def _valid(name: str, value, bits: int) -> bool:
    if name in FLAG_NAMES:
        return isinstance(value, bool)
    if not isinstance(value, int) or isinstance(value, bool):
        return False
    if name == "height":
        return -32768 <= value <= 32767
    return 0 <= value <= ((1 << bits) - 1 if name == "texture" else LIMITS[name])


def set_corner(t: Terrain, x: int, y: int, **fields) -> None:
    """Change named corner fields; other bits (including unknown texture-word bits) are kept."""
    i = _index(t, x, y)
    bits = _TEXTURE_BITS[t.version]
    for name, value in fields.items():
        if name not in LIMITS and name not in FLAG_NAMES and name not in ("height", "texture"):
            raise FormatError(f"unknown corner field {name!r}")
        if not _valid(name, value, bits):
            raise FormatError(f"bad value {value!r} for corner field {name}")
    c = {**corner(t, x, y), **fields}
    flags = sum(1 << (bits + k) for k, name in enumerate(FLAG_NAMES) if c[name])
    t.heights[i] = c["height"]
    t.water[i] = c["water_level"] | c["edge"] << 14
    t.textures[i] = t.textures[i] & ~((1 << (bits + 4)) - 1) | c["texture"] | flags
    t.variations[i] = c["ground_variation"] | c["cliff_variation"] << 5
    t.cliffs[i] = c["cliff_texture"] << 4 | c["layer"]
