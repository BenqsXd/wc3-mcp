"""Terrain brushes that shape a landscape rather than a patch: a river with banks, a coastline, a ridge, erosion,
terraces, a softened tile seam, and stamping one patch of terrain somewhere else. The plain brushes (raise, noise,
cliff, paint) are the tools; these are the shapes a map actually needs, and doing them by hand costs a dozen ops each.

ops/terrain.py owns the dispatch and the result; this module only does the work, so it takes the live _Brush and
writes through the same corner helpers the other brushes use.
"""
import math
import random

from ..errors import ToolError
from ..formats import w3e
from .elements import _bad, _bool, _int, _num

# op -> the keys it takes besides "op" and the area keys ops/terrain.py already allows
BRUSH_KEYS = {
    "river": {"depth", "bed", "bank", "water", "shallows", "seed"},
    "coast": {"water_level", "beach", "shallow", "slope", "seed"},
    "ridge": {"height", "roughness", "seed", "cliff", "cliff_tile"},
    "erosion": {"passes", "strength", "talus"},
    "terrace": {"step", "strength"},
    "blend": {"tiles", "amount", "seed"},
    "stamp": {"from", "to", "rotate", "mirror", "layers"},
}
STAMP_LAYERS = ("height", "texture", "cliff", "water", "flags")
FLAG_FIELDS = ("ramp", "blight", "boundary")


def apply(brush, op: dict, path: str) -> bool:
    """Run one of this module's brushes on `brush` (an ops.terrain._Brush). False when the op belongs elsewhere."""
    kind = op.get("op")
    if kind not in BRUSH_KEYS:
        return False
    if kind == "stamp":
        _stamp(brush, op, path)
    else:
        corners, reach = brush.corners(op, path)
        globals()["_" + kind](brush, op, path, corners, reach)
    return True


# ---- helpers ---------------------------------------------------------------------------------------------------
def _height_at(brush, cx: int, cy: int) -> float:
    from .terrain import _height

    return _height(brush.t.heights[cy * brush.t.width + cx])


def _set_height(brush, cx: int, cy: int, value: float) -> None:
    from .terrain import _raw

    brush.t.heights[cy * brush.t.width + cx] = _raw(value)


def _paint(brush, cx: int, cy: int, tile: str, path: str) -> None:
    """Paint one corner through the same palette bookkeeping the paint brush uses."""
    brush.apply({"op": "paint", "tile": tile, "rect": _corner_rect(brush, cx, cy)}, path)


def _corner_rect(brush, cx: int, cy: int) -> list[float]:
    from .terrain import _xy

    x, y = _xy(brush.t, cx, cy)
    return [x - 1, y - 1, x + 1, y + 1]


def _tile(brush, op: dict, key: str, path: str) -> str | None:
    value = op.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 4:
        raise _bad(f"{path}.{key}", "expected a tile id, e.g. \"Ldrt\" (data_search kind=tile)")
    return value


def _water(brush, cx: int, cy: int, level: float | None) -> None:
    from .terrain import _raw

    if level is None:
        w3e.set_corner(brush.t, cx, cy, water=False)
        return
    w3e.set_corner(brush.t, cx, cy, water=True, water_level=max(0, _raw(level)))


def _distance_to_path(points, x: float, y: float) -> float:
    from .terrain import _distance_to_segment

    return min(_distance_to_segment(x, y, *a, *b) for a, b in zip(points, points[1:]))


def _path_points(op: dict, path: str):
    points = op.get("path")
    if not isinstance(points, list) or len(points) < 2:
        raise _bad(f"{path}.path", "expected [[x, y], [x, y], ...] with at least two points")
    return [(_num(p[0], f"{path}.path"), _num(p[1], f"{path}.path")) for p in points]


# ---- brushes ---------------------------------------------------------------------------------------------------
def _river(brush, op: dict, path: str, corners, reach) -> None:
    """A bed that is deepest in the middle, water in it, and a dry bank on either side."""
    if "path" not in op:
        raise _bad(path, 'river runs along a "path" with a "width"')
    depth = _num(op.get("depth", 192), f"{path}.depth")
    shallows = _num(op.get("shallows", 0), f"{path}.shallows")
    bed, bank = _tile(brush, op, "bed", path), _tile(brush, op, "bank", path)
    wet = _bool(op.get("water", True), f"{path}.water")
    half = reach                                   # the path brush hands over half the width as its reach
    surface = min(_height_at(brush, cx, cy) for cx, cy, _d in corners) - depth * 0.25
    for cx, cy, d in corners:
        share = math.cos(min(d / half, 1.0) * math.pi / 2)      # 1 in the middle of the stream, 0 at its edge
        _set_height(brush, cx, cy, _height_at(brush, cx, cy) - depth * share)
        if bed and share > 0.35:
            _paint(brush, cx, cy, bed, path)
        elif bank and share <= 0.35:
            _paint(brush, cx, cy, bank, path)
        if wet:
            _water(brush, cx, cy, surface)
    if shallows > 0:                              # a wider, gentler band, so the bank is not a step into the water
        wide = dict(op, width=half * 2 + shallows * 2, depth=depth * 0.35, shallows=0, bed=None, water=False)
        _river(brush, wide, path, *brush.corners(wide, path))


def _coast(brush, op: dict, path: str, corners, reach) -> None:
    """Everything under the water level floods, the band above it becomes beach, and the shore slopes into it."""
    level = _num(op.get("water_level", 0), f"{path}.water_level")
    slope = _num(op.get("slope", 256), f"{path}.slope")
    beach, shallow = _tile(brush, op, "beach", path), _tile(brush, op, "shallow", path)
    for cx, cy, _d in corners:
        height = _height_at(brush, cx, cy)
        if height <= level:
            _water(brush, cx, cy, level)
            # the sea floor falls away from the shore instead of standing flat under the water
            _set_height(brush, cx, cy, height - min(level - height, slope) * 0.5)
            if shallow and level - height < slope * 0.5:
                _paint(brush, cx, cy, shallow, path)
            elif beach and shallow is None:
                _paint(brush, cx, cy, beach, path)
        elif beach and height - level <= slope:
            _paint(brush, cx, cy, beach, path)


def _ridge(brush, op: dict, path: str, corners, reach) -> None:
    """A raised spine with noise on it, optionally stepped into cliff levels so it reads as rock."""
    height = _num(op.get("height", 256), f"{path}.height")
    roughness = _num(op.get("roughness", 0.35), f"{path}.roughness")
    rng = random.Random(_int(op.get("seed", 0), f"{path}.seed"))
    cliff = op.get("cliff")
    points = _path_points(op, path) if "path" in op else None
    for cx, cy, d in corners:
        share = math.cos(min(d / max(reach, 1.0), 1.0) * math.pi / 2) ** 2
        rise = height * share * (1 - roughness + roughness * rng.uniform(0.6, 1.4))
        _set_height(brush, cx, cy, _height_at(brush, cx, cy) + rise)
        if cliff and share > 0.5:
            level = _int(cliff, f"{path}.cliff") if not isinstance(cliff, bool) else 3
            brush.apply({"op": "cliff", "level": level, "rect": _corner_rect(brush, cx, cy),
                         **({"cliff": op["cliff_tile"]} if op.get("cliff_tile") else {})}, path)
    if points is None and "rect" not in op and "radius" not in op:
        raise _bad(path, 'ridge takes a "path" with a "width", a "rect" or a circle')


def _erosion(brush, op: dict, path: str, corners, reach) -> None:
    """Thermal erosion: whatever is steeper than the talus angle slides downhill, so hand-made hills lose their cones."""
    passes = _int(op.get("passes", 3), f"{path}.passes", 1, 50)
    strength = _num(op.get("strength", 0.5), f"{path}.strength")
    talus = _num(op.get("talus", 64), f"{path}.talus")
    if not 0 < strength <= 1:
        raise _bad(f"{path}.strength", "expected a share between 0 and 1")
    inside = {(cx, cy) for cx, cy, _d in corners}
    for _ in range(passes):
        moved = {}
        for cx, cy in inside:
            here = _height_at(brush, cx, cy)
            lower = [(nx, ny, here - _height_at(brush, nx, ny))
                     for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1))
                     if (nx, ny) in inside and here - _height_at(brush, nx, ny) > talus]
            for nx, ny, drop in lower:
                share = (drop - talus) * strength / (2 * len(lower))
                moved[(cx, cy)] = moved.get((cx, cy), 0.0) - share
                moved[(nx, ny)] = moved.get((nx, ny), 0.0) + share
        for (cx, cy), delta in moved.items():
            _set_height(brush, cx, cy, _height_at(brush, cx, cy) + delta)


def _terrace(brush, op: dict, path: str, corners, reach) -> None:
    """Quantise the height into steps: fields, quarries and rice paddies read as made by hand."""
    step = _num(op.get("step", 128), f"{path}.step")
    strength = _num(op.get("strength", 1.0), f"{path}.strength")
    if step <= 0:
        raise _bad(f"{path}.step", "expected a step above 0")
    if not 0 < strength <= 1:
        raise _bad(f"{path}.strength", "expected a share between 0 and 1")
    for cx, cy, _d in corners:
        here = _height_at(brush, cx, cy)
        _set_height(brush, cx, cy, here + (round(here / step) * step - here) * strength)


def _blend(brush, op: dict, path: str, corners, reach) -> None:
    """Speckle the corners along a seam between two tiles with the other tile, so the boundary reads as a transition
    instead of a line. The game blends the textures themselves; this breaks up the shape of the seam."""
    tiles = op.get("tiles")
    if not isinstance(tiles, list) or len(tiles) != 2 or not all(isinstance(t, str) for t in tiles):
        raise _bad(f"{path}.tiles", 'expected the two tiles that meet, e.g. ["Lgrs", "Ldrt"]')
    amount = _num(op.get("amount", 0.5), f"{path}.amount")
    if not 0 <= amount <= 1:
        raise _bad(f"{path}.amount", "expected a share between 0 and 1")
    rng = random.Random(_int(op.get("seed", 0), f"{path}.seed"))
    t = brush.t
    names = [tile.decode("latin-1") for tile in t.tiles]
    if not set(tiles) <= set(names):
        raise ToolError("bad_value", f"{path}: the map's tile palette holds {names}, not both of {tiles}",
                        hint="paint both tiles first; a map holds at most 16", path=f"{path}.tiles")
    index = {name: names.index(name) for name in tiles}
    seam = []
    for cx, cy, _d in corners:
        mine = w3e.corner(t, cx, cy)["texture"]
        if mine not in index.values():
            continue
        other = index[tiles[1]] if mine == index[tiles[0]] else index[tiles[0]]
        near = [(nx, ny) for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1))
                if 0 <= nx < t.width and 0 <= ny < t.height and w3e.corner(t, nx, ny)["texture"] == other]
        if near and rng.random() < amount:
            seam.append((cx, cy, other))
    for cx, cy, other in seam:
        w3e.set_corner(t, cx, cy, texture=other)
        brush.painted[(cx, cy)] = other


def _stamp(brush, op: dict, path: str) -> None:
    """Copy a patch of terrain somewhere else, optionally rotated or mirrored: build one good corner of a map, then
    reuse it."""
    from .terrain import _area, _xy

    source = op.get("from")
    if not isinstance(source, list) or len(source) != 4:
        raise _bad(f"{path}.from", "expected the source area [left, bottom, right, top]")
    left, bottom, right, top = _area(source)
    to = op.get("to")
    if not isinstance(to, list) or len(to) != 2:
        raise _bad(f"{path}.to", "expected [x, y], where the middle of the patch lands")
    rotate = _int(op.get("rotate", 0), f"{path}.rotate")
    if rotate not in (0, 90, 180, 270):
        raise _bad(f"{path}.rotate", "expected 0, 90, 180 or 270")
    mirror = op.get("mirror")
    if mirror not in (None, "x", "y"):
        raise _bad(f"{path}.mirror", 'expected "x", "y" or null')
    layers = op.get("layers", list(STAMP_LAYERS))
    if not isinstance(layers, list) or not set(layers) <= set(STAMP_LAYERS):
        raise _bad(f"{path}.layers", "expected any of: " + ", ".join(STAMP_LAYERS))
    t = brush.t
    src = [(cx, cy) for cx, cy in brush._window(left, bottom, right, top)]
    if not src:
        raise _bad(f"{path}.from", f"the source area covers no terrain corner; the map spans {_area(source)}")
    cols, rows = {c for c, _r in src}, {r for _c, r in src}
    x0, y0 = min(cols), min(rows)
    width, height = max(cols) - x0 + 1, max(rows) - y0 + 1
    if rotate in (90, 270) and width != height:
        raise ToolError("bad_value", f"{path}: rotating by {rotate} degrees needs a square source area "
                                     f"({width} by {height} corners)", hint="use 0 or 180, or square the area")
    patch = {(c - x0, r - y0): dict(w3e.corner(t, c, r)) for c, r in src}
    cx0 = int(round((_num(to[0], f"{path}.to") - t.offset_x) / 128)) - width // 2
    cy0 = int(round((_num(to[1], f"{path}.to") - t.offset_y) / 128)) - height // 2
    written = 0
    for (dx, dy), values in patch.items():
        sx, sy = dx, dy
        if mirror == "x":
            sx = width - 1 - dx
        elif mirror == "y":
            sy = height - 1 - dy
        if rotate == 90:
            sx, sy = sy, width - 1 - sx
        elif rotate == 180:
            sx, sy = width - 1 - sx, height - 1 - sy
        elif rotate == 270:
            sx, sy = height - 1 - sy, sx
        tx, ty = cx0 + sx, cy0 + sy
        if not (0 <= tx < t.width and 0 <= ty < t.height):
            continue
        fields = {}
        if "height" in layers:
            fields["height"] = values["height"]
        if "texture" in layers:
            fields["texture"] = values["texture"]
        if "cliff" in layers:
            fields["layer"] = values["layer"]
            fields["cliff_texture"] = values["cliff_texture"]
        if "water" in layers:
            fields["water"] = values["water"]
            fields["water_level"] = values["water_level"]
        if "flags" in layers:
            for flag in FLAG_FIELDS:
                fields[flag] = values[flag]
        w3e.set_corner(t, tx, ty, **fields)
        if "texture" in layers:
            brush.painted[(tx, ty)] = values["texture"]
        written += 1
    if not written:
        raise ToolError("bad_value", f"{path}: the patch lands outside the map ({_xy(t, 0, 0)} to "
                                     f"{_xy(t, t.width - 1, t.height - 1)})", hint="move \"to\" inside the map")
