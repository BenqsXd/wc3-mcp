"""Terrain of an open map (war3map.w3e): corner grid windows as JSON, all-or-nothing brush edits and a top-down
render. Heights are world units: a corner's ground z is height + (cliff_level - 2) * 128; water levels are the
water surface z, drawn only where it is above the ground."""
import io
import math
import random
from collections import Counter

import numpy as np
from PIL import Image, ImageDraw

from ..errors import ToolError
from ..formats import blp, doo, unitsdoo, w3e, w3i, w3r, wpm
from ..formats.binary import FormatError
from . import heightmap, symmetry, terrainart
from .elements import _bad, _bool, _int, _num, _out
from .triggers import _read

LAYERS = ("height", "texture", "cliff_level", "water", "flags", "pathing")
DEFAULT_LAYERS = ("height", "texture", "cliff_level", "water", "flags")
MAX_CORNERS = 65536
RAW_ZERO, RAW_MAX = 0x2000, 0x3FFF  # raw corner height of world height 0, highest raw height
WATER_OFFSET = -89.6  # the game draws water this far below its stored level (TerrainArt/Water.slk height -0.7 x 128)
# tilesets whose water sits at another height (Water.slk "height" x 128): Ashenvale, Underground, Dungeon, Outland
TILESET_WATER_OFFSET = {"A": -76.8, "G": -76.8, "D": -96.0, "O": -192.0}
IMPASSABLE_WATER = {"O"}   # Water.slk impassable=1: no ground unit walks in Outland water at any depth
# Water deeper than this is unwalkable. Measured on the editor-saved maps shipped with the game (war3map.wpm against
# the corner heights): flat water up to 51.95 deep is always walkable, from 56.4 always unwalkable, and cells in
# between flip around 52.5-55; a World Editor save read 47.9 walkable and 63.9 unwalkable.
# ponytail: one number for a fuzzy band; war3map.wpm after an editor save is the exact answer
DEEP_WATER = 53.0
VARIATIONS = (0, 4, 8, 12, 16, 17)  # ground variations the editor spreads when painting
DERIVED_WARNING = ("war3map.wpm (pathing), war3map.shd (shadows) and war3map.mmp (minimap) are recomputed by the World "
                   "Editor only, and placed doodads keep their z: editor_map open + save refreshes them")
_HINT = ('each op is {"op": <brush>, <area>, <settings>}. Areas: "x"/"y"/"radius" (circle), "rect": [left, bottom, '
         'right, top], "path": [[x, y], ...] with "width" (a stroke, e.g. a road), or none at all (the whole map). '
         'ops: {"op": "raise", "x": 0, "y": 0, "radius": 512, "amount": 128}, {"op": "plateau", "rect": [-512, -512, '
         '512, 512], "height": 0}, {"op": "paint", "tile": "Lgrs"}, {"op": "paint", "tile": "Ldrt", "path": [[0, 0], '
         '[512, 0], [512, 512]], "width": 192}, {"op": "cliff", "x": 0, "y": 0, "radius": 256, "level": 3}, '
         '{"op": "water", "rect": [0, 0, 1024, 1024], "level": -64}')
PAINT_WARN_CORNERS = 16   # painting fewer corners of an unbuildable tile is detail, not a zone
QUIET = {"tile_pathing", "derived_files"}   # warnings a caller can switch off per terrain_edit call
PATHING_EFFECTS = {"buildable": "players cannot build on it (CreateUnit still places structures)",
                   "walkable": "ground units cannot walk on it"}
DERIVED_PATHING = ("derived from the current tiles, cliffs, water and blight because war3map.wpm predates the last "
                   "terrain_edit (or is missing); doodad, destructible and building footprints are not included")
AREA_KEYS = {"x", "y", "radius", "rect", "path", "width"}
BRUSH_KEYS = {
    "raise": {"amount", "falloff"}, "lower": {"amount", "falloff"}, "plateau": {"height"}, "smooth": {"strength"},
    "noise": {"amount", "seed", "falloff"}, "paint": {"tile"}, "cliff": {"level", "cliff"}, "ramp": {"value"},
    "water": {"level"}, "blight": {"value"}, "boundary": {"value"},
    **terrainart.BRUSH_KEYS, **symmetry.TERRAIN_KEYS, **heightmap.KEYS,   # the landscape brushes
}


def tile_limit(t: w3e.Terrain) -> int:
    """Ground tiles a map can hold: the World Editor's 16, or fewer when the file version has fewer texture bits."""
    return min(1 << w3e._TEXTURE_BITS[t.version], 16)


def _palette(t: w3e.Terrain) -> dict:
    """The map's tile slots: what is in them and how many are left (painting an unlisted tile takes one)."""
    return {"tiles": [x.decode("latin-1") for x in t.tiles], "cliff_tiles": [x.decode("latin-1") for x in t.cliff_tiles],
            "free": tile_limit(t) - len(t.tiles), "limit": tile_limit(t)}


def _load(project) -> tuple[w3e.Terrain, bytes]:
    data = _read(project, "war3map.w3e")
    if data is None:
        raise ToolError("no_terrain", "this map has no war3map.w3e", hint="create the map in the World Editor first")
    try:
        return w3e.parse(data), data
    except FormatError as e:
        raise ToolError("bad_file", f"war3map.w3e: {e}", hint="map_file_write can replace a damaged file") from e


def _xy(t: w3e.Terrain, cx: int, cy: int) -> tuple[float, float]:
    return t.offset_x + cx * 128, t.offset_y + cy * 128


def _height(raw: int) -> float:
    return (raw - RAW_ZERO) / 4


def water_offset(t: w3e.Terrain) -> float:
    """How far below its stored level the game draws this map's water."""
    return TILESET_WATER_OFFSET.get(t.tileset, WATER_OFFSET)


def water_z(t: w3e.Terrain, raw: int) -> float:
    """The water surface z the game draws for a corner's stored water level."""
    return _height(raw) + water_offset(t)


def water_raw(t: w3e.Terrain, z: float) -> int:
    """The stored water level that draws the surface at z (quarter units, so -40 reads back as about -40.1)."""
    return _raw(z - water_offset(t))


def ground_z(c: dict) -> float:
    """A corner's ground z: its height plus its cliff level."""
    return _height(c["height"]) + (c["layer"] - 2) * 128


def water_depth(t: w3e.Terrain, c: dict) -> float | None:
    """How deep the water over a corner is, or None when the corner is dry."""
    if not c["water"]:
        return None
    depth = water_z(t, c["water_level"]) - ground_z(c)
    return depth if depth > 0 else None


def deep(t: w3e.Terrain, depth: float | None) -> bool:
    """True when water this deep stops ground units."""
    return depth is not None and (depth > DEEP_WATER or t.tileset in IMPASSABLE_WATER)


def _raw(height: float) -> int:
    return int(min(max(round(height * 4 + RAW_ZERO), 0), RAW_MAX))


def _bounds(t: w3e.Terrain) -> list[float]:
    return [t.offset_x, t.offset_y, *_xy(t, t.width - 1, t.height - 1)]


# ---- get -----------------------------------------------------------------------------------------------------
def _corner_pathing(t: w3e.Terrain, catalog, cx: int, cy: int, cache: dict) -> str:
    """wpm-style letters for a corner from the terrain alone: w unwalkable, f unflyable, b unbuildable, B blight."""
    c = w3e.corner(t, cx, cy)
    tile = t.tiles[c["texture"]].decode("latin-1") if c["texture"] < len(t.tiles) else None
    if tile not in cache:
        cache[tile] = catalog.tile_pathing(tile) if tile and catalog is not None else {}
    flags = cache[tile]
    letters = {k for k, name in (("w", "walkable"), ("f", "flyable"), ("b", "buildable")) if not flags.get(name, True)}
    near = [(nx, ny) for nx in (cx - 1, cx, cx + 1) for ny in (cy - 1, cy, cy + 1)
            if 0 <= nx < t.width and 0 <= ny < t.height]
    if not c["ramp"] and any(w3e.corner(t, nx, ny)["layer"] != c["layer"] for nx, ny in near):
        letters |= {"w", "b"}   # a cliff edge
    depth = water_depth(t, c)
    if depth is not None:
        letters.add("b")
        if deep(t, depth):
            letters.add("w")
    if c["blight"]:
        letters.add("B")
    return "".join(k for k in "wfbB" if k in letters)


def _runs(row: list) -> list:
    """A row as [value, count] pairs: terrain repeats, so this is usually a fraction of the cells."""
    out = []
    for value in row:
        if out and out[-1][0] == value:
            out[-1][1] += 1
        else:
            out.append([value, 1])
    return out


def _summary(grids: dict) -> dict:
    """What a caller usually wants to know about an area without reading every corner."""
    from collections import Counter

    out = {}
    for name, rows in grids.items():
        values = [v for row in rows for v in row]
        if not values:
            continue
        if name in ("height", "water"):
            numbers = [v for v in values if isinstance(v, (int, float))]
            if numbers:
                out[name] = {"min": round(min(numbers), 1), "max": round(max(numbers), 1),
                             "mean": round(sum(numbers) / len(numbers), 1),
                             "share": round(len(numbers) / len(values), 3)}
        else:
            counts = Counter("" if v is None else v for v in values)
            out[name] = {"counts": dict(counts.most_common(12)), "kinds": len(counts)}
    out["corners"] = sum(len(row) for row in next(iter(grids.values()), []))
    return out


def terrain_get(project, area: list | None = None, layers: list | None = None, step: int = 1, catalog=None,
                format: str = "grid") -> dict:
    t, _ = _load(project)
    layers = list(DEFAULT_LAYERS if layers is None else layers)
    unknown = [x for x in layers if x not in LAYERS]
    if unknown:
        raise _bad("layers", f"unknown layers {unknown}; choose from {', '.join(LAYERS)}")
    step = _int(step, "step", 1, 256)
    left, bottom, right, top = _bounds(t) if area is None else _area(area)
    c0 = max(0, math.ceil((left - t.offset_x) / 128))
    r0 = max(0, math.ceil((bottom - t.offset_y) / 128))
    c1 = min(t.width - 1, math.floor((right - t.offset_x) / 128))
    r1 = min(t.height - 1, math.floor((top - t.offset_y) / 128))
    snapped = []
    if c0 > c1 and right >= t.offset_x and left <= t.offset_x + (t.width - 1) * 128:   # between two corner lines
        c0 = c1 = min(t.width - 1, max(0, round(((left + right) / 2 - t.offset_x) / 128)))
        snapped.append("x")
    if r0 > r1 and top >= t.offset_y and bottom <= t.offset_y + (t.height - 1) * 128:
        r0 = r1 = min(t.height - 1, max(0, round(((bottom + top) / 2 - t.offset_y) / 128)))
        snapped.append("y")
    columns, rows = range(c0, c1 + 1, step), range(r0, r1 + 1, step)
    if not columns or not rows:
        raise _bad("area", f"no terrain corners inside {area}; the map spans {_bounds(t)}")
    if len(columns) * len(rows) > MAX_CORNERS:
        raise ToolError("too_large", f"{len(columns)}x{len(rows)} corners is more than {MAX_CORNERS}",
                        hint="pass a smaller area or a larger step")
    pathing, derived, cache = None, False, {}
    if "pathing" in layers:
        data = _read(project, "war3map.wpm")
        try:
            pathing = wpm.parse(data) if data is not None else None
        except FormatError:
            pathing = None
        derived = pathing is None or bool(project.notes().get("terrain_edited"))
    grids = {name: [] for name in layers}
    for cy in rows:
        line = {name: [] for name in layers}
        for cx in columns:
            c = w3e.corner(t, cx, cy)
            if "height" in line:
                line["height"].append(_out(_height(c["height"])))
            if "texture" in line:
                line["texture"].append(t.tiles[c["texture"]].decode("latin-1") if c["texture"] < len(t.tiles) else None)
            if "cliff_level" in line:
                line["cliff_level"].append(c["layer"])
            if "water" in line:
                line["water"].append(_out(water_z(t, c["water_level"])) if c["water"] else None)
            if "flags" in line:
                line["flags"].append("".join(k for k, name in (("r", "ramp"), ("b", "blight"), ("w", "water"),
                                                                 ("x", "boundary")) if c[name]))
            if "pathing" in line and derived:
                line["pathing"].append(_corner_pathing(t, catalog, cx, cy, cache))
            elif "pathing" in line:
                cell = None
                if pathing is not None:
                    px, py = min(cx * 4, pathing.width - 1), min(cy * 4, pathing.height - 1)
                    cell = pathing.cells[py * pathing.width + px]
                line["pathing"].append(None if cell is None else "".join(
                    k for k, bit in (("w", 2), ("f", 4), ("b", 8), ("B", 0x20)) if cell & bit))
        for name in layers:
            grids[name].append(line[name])
    if format not in ("grid", "runs", "summary"):
        raise _bad("format", 'expected "grid", "runs" or "summary"')
    shown: dict = {"layers": grids}
    if format == "runs":
        shown = {"runs": {name: [_runs(row) for row in rows] for name, rows in grids.items()},
                 "runs_note": "each row is [value, count] pairs, left to right; the grid is the same data unpacked"}
    elif format == "summary":
        shown = {"summary": _summary(grids),
                 "summary_note": "counts are corners per value; height and water give their range and mean, and "
                                 "water share is the part of the area that is under water"}
    return {"version": t.version, "tileset": t.tileset, "tiles": [x.decode("latin-1") for x in t.tiles],
            "cliff_tiles": [x.decode("latin-1") for x in t.cliff_tiles], "palette": _palette(t),
            "corners": [t.width, t.height],
            "bounds": _bounds(t),
            "window": {"left": _xy(t, c0, r0)[0], "bottom": _xy(t, c0, r0)[1], "step": step, "columns": len(columns),
                       "rows": len(rows), "note": "rows run south to north; row j, column i is at (left + i * step * "
                                                  "128, bottom + j * step * 128)",
                       **({"snapped": f"the area held no corner line in {' and '.join(snapped)}, so the nearest one "
                                      "is used (corners lie 128 apart from the map edge)"} if snapped else {})},
            **shown,
            **({"pathing_source": DERIVED_PATHING if derived else "war3map.wpm from the last World Editor save"}
               if "pathing" in layers else {})}


def _area(area) -> list[float]:
    if not isinstance(area, list) or len(area) != 4:
        raise _bad("area", "expected [left, bottom, right, top]")
    values = [_num(v, f"area[{i}]") for i, v in enumerate(area)]
    if values[0] > values[2] or values[1] > values[3]:
        raise _bad("area", "left/bottom must not be greater than right/top")
    return values


# ---- edit ----------------------------------------------------------------------------------------------------
def _falloff(kind: str, d: float, r: float) -> float:
    if kind == "flat":
        return 1.0
    if kind == "linear":
        return max(0.0, 1 - d / r)
    return 0.5 * (1 + math.cos(math.pi * min(d / r, 1.0)))


def _distance_to_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.dist((px, py), (ax, ay))
    along = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.dist((px, py), (ax + along * dx, ay + along * dy))


class _Brush:
    """Brush operations on a parsed terrain; raise ToolError("bad_value") on bad input."""

    def __init__(self, t: w3e.Terrain, catalog=None):
        self.t, self.catalog, self.added = t, catalog, {"tiles": [], "cliff_tiles": []}
        self.painted: dict[tuple[int, int], int] = {}   # corner -> tile index painted by this batch
        self.info: list[dict] = []   # what water ops ended up with: the stored level and the depths it made

    def tell(self, path: str, **fields) -> None:
        self.info.append({"op": path, **fields})

    def depths(self, corners) -> dict:
        """The depth range of the wet corners among `corners`, and how many of them no ground unit can cross."""
        found = [d for d in (water_depth(self.t, w3e.corner(self.t, cx, cy)) for cx, cy, *_ in corners)
                 if d is not None]
        if not found:
            return {"wet_corners": 0}
        return {"wet_corners": len(found), "depth": {"min": _out(min(found)), "max": _out(max(found))},
                "deep_corners": sum(deep(self.t, d) for d in found)}

    def _window(self, left: float, bottom: float, right: float, top: float):
        t = self.t
        return ((cx, cy)
                for cy in range(max(0, math.ceil((bottom - t.offset_y) / 128)),
                                min(t.height - 1, math.floor((top - t.offset_y) / 128)) + 1)
                for cx in range(max(0, math.ceil((left - t.offset_x) / 128)),
                                min(t.width - 1, math.floor((right - t.offset_x) / 128)) + 1))

    def corners(self, op: dict, path: str):
        """[(column, row, distance from the brush centre)] and the falloff scale, for a circle, a rectangle, a path
        stroke or (no area given) the whole map."""
        t = self.t
        if "rect" in op:
            left, bottom, right, top = _area(op["rect"])
            out, scale, what = [(cx, cy, 0.0) for cx, cy in self._window(left, bottom, right, top)], 1.0, "rectangle"
        elif "path" in op:
            points = op["path"]
            if not isinstance(points, list) or len(points) < 2 or any(
                    not isinstance(p, list) or len(p) != 2 for p in points):
                raise _bad(f"{path}.path", "expected [[x, y], [x, y], ...] with at least two points")
            line = [(_num(p[0], f"{path}.path"), _num(p[1], f"{path}.path")) for p in points]
            half = _num(op.get("width", 128), f"{path}.width") / 2
            if not 0 < half <= 32768:
                raise _bad(f"{path}.width", "expected a width greater than 0")
            xs, ys = [p[0] for p in line], [p[1] for p in line]
            out = []
            for cx, cy in self._window(min(xs) - half, min(ys) - half, max(xs) + half, max(ys) + half):
                wx, wy = _xy(t, cx, cy)
                d = min(_distance_to_segment(wx, wy, *a, *b) for a, b in zip(line, line[1:]))
                if d <= half:
                    out.append((cx, cy, d))
            scale, what = half, "path"
        elif AREA_KEYS & set(op):
            x, y = _num(op.get("x"), f"{path}.x"), _num(op.get("y"), f"{path}.y")
            r = _num(op.get("radius"), f"{path}.radius")
            if not 0 < r <= 65536:
                raise _bad(f"{path}.radius", "expected a radius greater than 0")
            out = [(cx, cy, math.dist((x, y), _xy(t, cx, cy)))
                   for cx, cy in self._window(x - r, y - r, x + r, y + r)]
            out = [c for c in out if c[2] <= r]
            scale, what = r, f"circle at ({x}, {y}) radius {r}"
        else:
            out, scale, what = [(cx, cy, 0.0) for cx, cy in self._window(*_bounds(t))], 1.0, "whole map"
        if not out:
            raise _bad(path, f"the {what} covers no terrain corner; the map spans {_bounds(t)}")
        return out, scale

    def _flag(self, op: dict, path: str) -> bool:
        return _bool(op.get("value", True), f"{path}.value")

    def apply(self, op: dict, path: str) -> None:
        kind = op.get("op")
        extra = set(op) - {"op"} - AREA_KEYS - BRUSH_KEYS[kind]
        if extra:
            raise ToolError("bad_op", f"{path}: unknown keys {sorted(extra)} for {kind}", hint=_HINT)
        # the landscape brushes live in their own modules; they write through the same corner helpers
        if terrainart.apply(self, op, path) or symmetry.terrain_apply(self, op, path)                 or heightmap.apply(self, op, path):
            return
        corners, r = self.corners(op, path)
        t = self.t
        if kind in ("raise", "lower", "noise"):
            amount = _num(op.get("amount", 64 if kind != "noise" else 32), f"{path}.amount")
            falloff = op.get("falloff", "smooth")
            if falloff not in ("smooth", "linear", "flat"):
                raise _bad(f"{path}.falloff", "expected smooth, linear or flat")
            rng = random.Random(_int(op.get("seed", 0), f"{path}.seed"))
            for cx, cy, d in corners:
                delta = amount * _falloff(falloff, d, r) * (-1 if kind == "lower" else 1)
                if kind == "noise":
                    delta *= rng.uniform(-1, 1)
                i = cy * t.width + cx
                t.heights[i] = _raw(_height(t.heights[i]) + delta)
        elif kind == "plateau":
            ci = min(corners, key=lambda c: c[2])
            target = _num(op["height"], f"{path}.height") if "height" in op else _height(t.heights[ci[1] * t.width + ci[0]])
            for cx, cy, _ in corners:
                t.heights[cy * t.width + cx] = _raw(target)
        elif kind == "smooth":
            strength = _num(op.get("strength", 1.0), f"{path}.strength")
            if not 0 <= strength <= 1:
                raise _bad(f"{path}.strength", "expected 0..1")
            before = list(t.heights)
            for cx, cy, _ in corners:
                near = [before[ny * t.width + nx] for nx in range(cx - 1, cx + 2) for ny in range(cy - 1, cy + 2)
                        if 0 <= nx < t.width and 0 <= ny < t.height]
                i = cy * t.width + cx
                t.heights[i] = round(before[i] + (sum(near) / len(near) - before[i]) * strength)
        elif kind == "paint":
            index = self._tile_index(op.get("tile"), f"{path}.tile")
            for cx, cy, _ in corners:
                w3e.set_corner(t, cx, cy, texture=index, ground_variation=VARIATIONS[(cx * 7 + cy * 13) % len(VARIATIONS)])
                self.painted[(cx, cy)] = index
        elif kind == "cliff":
            level = _int(op.get("level"), f"{path}.level", 0, 15)
            fields = {"layer": level}
            if "cliff" in op:
                fields["cliff_texture"] = self._cliff_index(op["cliff"], f"{path}.cliff")
            for cx, cy, _ in corners:
                w3e.set_corner(t, cx, cy, **fields)
        elif kind == "water":
            level = op.get("level")
            if level is None:
                for cx, cy, _ in corners:
                    w3e.set_corner(t, cx, cy, water=False)
            else:
                raw = water_raw(t, _num(level, f"{path}.level"))
                for cx, cy, _ in corners:
                    w3e.set_corner(t, cx, cy, water=True, water_level=raw)
                self.tell(path, level=_out(water_z(t, raw)), **self.depths(corners))
        else:  # ramp, blight, boundary
            value = self._flag(op, path)
            for cx, cy, _ in corners:
                w3e.set_corner(t, cx, cy, **{kind: value})

    def _catalog_id(self, kind: str, value, path: str) -> bytes:
        if not isinstance(value, str) or len(value) != 4 or not value.isascii():
            raise _bad(path, f"expected a 4-character {kind} id (data_search kind={kind})")
        if self.catalog is not None:
            try:
                self.catalog.get(kind, value)
            except ToolError as e:
                if e.code != "not_found":
                    raise
                raise _bad(path, f"no {kind} {value!r} (data_search kind={kind})") from e
        return value.encode("latin-1")

    def _tile_index(self, value, path: str) -> int:
        tile = self._catalog_id("tile", value, path)
        if tile not in self.t.tiles:
            if len(self.t.tiles) >= tile_limit(self.t):
                raise _bad(path, f"the map already uses {len(self.t.tiles)} ground tiles, the most the World Editor "
                                 "allows; paint with one of terrain_get's tiles")
            self.t.tiles.append(tile)
            self.added["tiles"].append(tile.decode("latin-1"))
            self.t.custom_tileset = 1  # without it the World Editor resets the list to the tileset's own tiles
        return self.t.tiles.index(tile)

    def _cliff_index(self, value, path: str) -> int:
        cliff = self._catalog_id("cliff", value, path)
        if cliff not in self.t.cliff_tiles:
            if len(self.t.cliff_tiles) >= 2:
                raise _bad(path, "the map already uses 2 cliff tiles, the most the World Editor allows")
            self.t.cliff_tiles.append(cliff)
            self.added["cliff_tiles"].append(cliff.decode("latin-1"))
            self.t.custom_tileset = 1
        return self.t.cliff_tiles.index(cliff)


def terrain_edit(project, catalog, ops: list, quiet: list | None = None) -> dict:
    t, before = _load(project)
    quiet = set(quiet or [])
    if quiet - QUIET:
        raise _bad("quiet", f"expected any of {sorted(QUIET)}")
    brush = _Brush(t, catalog)
    for i, op in enumerate(ops):
        path = f"ops[{i}]"
        try:
            if not isinstance(op, dict) or op.get("op") not in BRUSH_KEYS:
                raise ToolError("bad_op", f"{path}: unknown op {op.get('op') if isinstance(op, dict) else op!r}",
                                hint=_HINT)
            brush.apply(op, path)
        except ToolError as e:
            e.details.setdefault("op_index", i)
            if e.code == "bad_value" and not e.hint:
                e.hint = _HINT
            raise
    data = w3e.serialize(t)
    changed = data != before
    if changed:
        project.write("war3map.w3e", data)
        project.note("terrain_edited")   # map_validate warns until the World Editor recomputes the derived files
    warnings = [DERIVED_WARNING] if changed and "derived_files" not in quiet else []
    for index, count in sorted(Counter(brush.painted.values()).items()):
        tile = t.tiles[index].decode("latin-1")
        flags = catalog.tile_pathing(tile) if catalog is not None else {}
        effects = [effect for name, effect in PATHING_EFFECTS.items() if not flags.get(name, True)]
        if count >= PAINT_WARN_CORNERS and effects and "tile_pathing" not in quiet:
            warnings.append(f"painted {count} corners with {tile} ({catalog.name('tile', tile)}): "
                            + " and ".join(effects))
    out = {"changed": changed, "palette": _palette(t), "palette_added": brush.added, "warnings": warnings}
    if brush.info:
        out["water"] = brush.info
        out["water_note"] = (f"level is the stored surface z (kept in quarter units, so it can differ from the one asked "
                             f"for by 0.1); water deeper than {DEEP_WATER:g} stops ground units (deep_corners)")
    return out


# ---- render --------------------------------------------------------------------------------------------------
def _tile_color(catalog, tile: str, cache: dict) -> tuple[int, int, int]:
    if tile not in cache:
        color = None
        try:
            fields = catalog.get("tile", tile)["fields"]
            stem = fields["dir"].replace("\\", "/") + "/" + fields["file"]
            for ext in (".dds", ".blp", ".tga"):
                full = catalog.storage.resolve(stem + ext, **catalog.layer)
                if full:
                    im = Image.open(io.BytesIO(catalog.storage.read(full))).convert("RGB")
                    cell = im.crop((0, 0, im.height // 4, im.height // 4)) if im.height >= 4 else im
                    color = tuple(int(v) for v in np.asarray(cell).reshape(-1, 3).mean(axis=0))
                    break
        except (ToolError, KeyError, OSError, ValueError):
            color = None
        if color is None:
            h = sum(tile.encode()) * 2654435761 & 0xFFFFFF
            color = (h >> 16 & 255, h >> 8 & 255, h & 255)
        cache[tile] = color
    return cache[tile]


def render_window(t: w3e.Terrain, area) -> tuple[int, int, int, int]:
    """The tiles (first column, first row from the south, columns, rows) an area covers, whole tiles only."""
    w, h = t.width - 1, t.height - 1
    if area is None:
        return 0, 0, w, h
    left, bottom, right, top = _area(area)
    c0 = min(max(math.floor((left - t.offset_x) / 128), 0), w - 1)
    r0 = min(max(math.floor((bottom - t.offset_y) / 128), 0), h - 1)
    c1 = min(max(math.ceil((right - t.offset_x) / 128), c0 + 1), w)
    r1 = min(max(math.ceil((top - t.offset_y) / 128), r0 + 1), h)
    return c0, r0, c1 - c0, r1 - r0


def render_area(project, area) -> dict:
    """The world rectangle terrain_render draws for `area`: the tiles it touches, clipped to the map."""
    t, _ = _load(project)
    c0, r0, cols, rows = render_window(t, area)
    return {"drawn": [t.offset_x + c0 * 128, t.offset_y + r0 * 128, t.offset_x + (c0 + cols) * 128,
                      t.offset_y + (r0 + rows) * 128], "tiles": [cols, rows]}


def terrain_render(project, catalog, scale: int | None = None, objects: bool = True, doodads: bool = True,
                   pathing: bool = False, area=None) -> bytes:
    """PNG of the map from above, north up: tile colours, height shading, cliffs, water, blight, boundary, and
    optionally regions (cyan), start locations (white), units (red) and items (yellow), with doodads (magenta), trees
    (dark green) and other destructibles (orange) under them. pathing tints ground whose tile is unbuildable red and
    unwalkable black, from the current tiles, and deep water black. area draws only the tiles that rectangle
    touches."""
    t, _ = _load(project)
    w, h = t.width - 1, t.height - 1
    c0, r0, cols, rows = render_window(t, area)
    scale = scale or max(1, min(8 if area is None else 16, 1024 // max(cols, rows, 1)))
    scale = _int(scale, "scale", 1, 16)
    grid = lambda values: np.asarray(values, dtype=np.int32).reshape(t.height, t.width)  # noqa: E731
    heights, tex, cliffs, water = grid(t.heights), grid(t.textures), grid(t.cliffs), grid(t.water)
    bits = w3e._TEXTURE_BITS[t.version]
    layer = cliffs & 15
    z = (heights - RAW_ZERO) / 4 + (layer - 2) * 128
    cache = {}
    palette = np.array([_tile_color(catalog, x.decode("latin-1"), cache) for x in t.tiles] or [(128, 128, 128)],
                       dtype=np.float32)
    index = np.minimum(tex[:-1, :-1] & ((1 << bits) - 1), len(palette) - 1)
    rgb = palette[index]
    dzdx = (z[:-1, 1:] + z[1:, 1:] - z[:-1, :-1] - z[1:, :-1]) / 2
    dzdy = (z[1:, :-1] + z[1:, 1:] - z[:-1, :-1] - z[:-1, 1:]) / 2
    shade = np.clip(1 + (-dzdx + dzdy) / 256, 0.55, 1.35)[..., None]
    rgb = rgb * shade
    quad = np.stack([layer[:-1, :-1], layer[1:, :-1], layer[:-1, 1:], layer[1:, 1:]])
    rgb[quad.max(axis=0) != quad.min(axis=0)] *= 0.6
    flag = lambda k: (tex[:-1, :-1] >> (bits + k)) & 1  # noqa: E731
    rgb[flag(1) == 1] = rgb[flag(1) == 1] * 0.5 + np.array([90, 60, 110]) * 0.5
    depth = ((water[:-1, :-1] & 0x3FFF) - RAW_ZERO) / 4 + water_offset(t) - z[:-1, :-1]
    wet = (flag(2) == 1) & (depth > 0)
    rgb[wet] = rgb[wet] * 0.25 + (np.array([40, 90, 160]) * (1 - np.clip(depth[wet], 0, 512) / 1024)[:, None]) * 0.75
    rgb[flag(3) == 1] *= 0.35
    if pathing:
        flags = [catalog.tile_pathing(x.decode("latin-1")) for x in t.tiles] or [{}]
        for name, tint in (("buildable", (220, 30, 30)), ("walkable", (0, 0, 0))):
            bad = np.array([not f.get(name, True) for f in flags])[index]
            if name == "walkable":   # water too deep to wade counts as unwalkable ground here
                bad = bad | (wet & ((depth > DEEP_WATER) | (t.tileset in IMPASSABLE_WATER)))
            rgb[bad] = rgb[bad] * 0.4 + np.array(tint) * 0.6
    rgb = rgb[r0:r0 + rows, c0:c0 + cols]
    image = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8)[::-1], "RGB")
    image = image.resize((cols * scale, rows * scale), Image.NEAREST)
    if objects:
        draw = ImageDraw.Draw(image)

        def px(x: float, y: float) -> tuple[float, float]:
            return ((x - t.offset_x) / 128 - c0) * scale, (r0 + rows - (y - t.offset_y) / 128) * scale

        rdata = _read(project, "war3map.w3r")
        try:
            regions = w3r.parse(rdata).regions if rdata else []
        except FormatError:
            regions = []
        for g in regions:
            (x0, y0), (x1, y1) = px(g.left, g.top), px(g.right, g.bottom)
            draw.rectangle([x0, y0, x1, y1], outline=(0, 230, 230))
        ddata = _read(project, "war3map.doo") if doodads else None
        try:
            placed = doo.parse(ddata).doodads if ddata else []
        except FormatError:
            placed = []
        destructibles = catalog.table("Units/DestructableData.slk").rows
        mark = max(0.5, scale / 4)
        for d in placed:
            row = destructibles.get(d.id.decode("latin-1"))
            tree = row is not None and "tree" in (row.get("targType") or "")
            color = (200, 0, 200) if row is None else (0, 90, 0) if tree else (255, 140, 0)
            x, y = px(d.x, d.y)
            # a light rim keeps dark tree marks visible on dark grass
            rim = (210, 255, 170) if tree and mark >= 1.5 else None
            draw.ellipse([x - mark, y - mark, x + mark, y + mark], fill=color, outline=rim)
        udata = _read(project, "war3mapUnits.doo")
        try:
            units = unitsdoo.parse(udata).units if udata else []
        except FormatError:
            units = []
        items = set(catalog.ids("item"))
        dot = max(1, scale // 2)
        for u in units:
            kind = u.id.decode("latin-1")
            color = (255, 255, 255) if kind == "sloc" else (255, 220, 0) if kind in items else (230, 40, 40)
            x, y = px(u.x, u.y)
            size = dot * 3 if kind == "sloc" else dot
            draw.ellipse([x - size, y - size, x + size, y + size], fill=color)
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def minimap(project, catalog) -> bytes:
    """war3mapMap.blp as the World Editor saves it: the playable area from above as a 256x256 JPEG BLP without
    mipmaps. The game quits right after login on a map without one."""
    image = Image.open(io.BytesIO(terrain_render(project, catalog, scale=1, objects=False)))
    try:
        left, right, bottom, top = w3i.parse(project.read("war3map.w3i")).camera_complements
        if min(left, right, bottom, top) >= 0 and left + right < image.width and bottom + top < image.height:
            image = image.crop((left, top, image.width - right, image.height - bottom))
    except (ToolError, FormatError, ValueError):
        pass  # no readable map info: the whole terrain
    return blp.encode(image.resize((256, 256), Image.Resampling.BILINEAR), mipmaps=False)


def preview(project, catalog, size: int = 256) -> bytes:
    """war3mapPreview.tga: the picture the map list shows instead of the minimap. Same view as the minimap, written
    as an uncompressed TGA, which is what the game reads there."""
    image = Image.open(io.BytesIO(terrain_render(project, catalog, scale=1, objects=True, doodads=False)))
    out = io.BytesIO()
    image.convert("RGB").resize((size, size), Image.Resampling.BILINEAR).save(out, format="TGA")
    return out.getvalue()
