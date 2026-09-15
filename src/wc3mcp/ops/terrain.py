"""Terrain of an open map (war3map.w3e): corner grid windows as JSON, all-or-nothing brush edits and a top-down
render. Heights are world units: a corner's ground z is height + (cliff_level - 2) * 128; water levels are the
water surface z, drawn only where it is above the ground."""
import io
import math
import random

import numpy as np
from PIL import Image, ImageDraw

from ..errors import ToolError
from ..formats import unitsdoo, w3e, w3r, wpm
from ..formats.binary import FormatError
from .elements import _bad, _bool, _int, _num, _out
from .triggers import _read

LAYERS = ("height", "texture", "cliff_level", "water", "flags", "pathing")
DEFAULT_LAYERS = ("height", "texture", "cliff_level", "water", "flags")
MAX_CORNERS = 65536
RAW_ZERO, RAW_MAX = 0x2000, 0x3FFF  # raw corner height of world height 0, highest raw height
WATER_OFFSET = -89.6  # the game draws water this far below its level
VARIATIONS = (0, 4, 8, 12, 16, 17)  # ground variations the editor spreads when painting
DERIVED_WARNING = ("war3map.wpm (pathing), war3map.shd (shadows) and war3map.mmp (minimap) are recomputed by the World "
                   "Editor only, and placed doodads keep their z: editor_map open + save refreshes them")
_HINT = ('ops: {"op": "raise", "x": 0, "y": 0, "radius": 512, "amount": 128}, {"op": "plateau", "x": 0, "y": 0, '
         '"radius": 256, "height": 0}, {"op": "paint", "tile": "Lgrs", "x": 0, "y": 0, "radius": 384}, {"op": "cliff", '
         '"x": 0, "y": 0, "radius": 256, "level": 3}, {"op": "water", "x": 0, "y": 0, "radius": 512, "level": -64}')
BRUSH_KEYS = {
    "raise": {"amount", "falloff"}, "lower": {"amount", "falloff"}, "plateau": {"height"}, "smooth": {"strength"},
    "noise": {"amount", "seed", "falloff"}, "paint": {"tile"}, "cliff": {"level", "cliff"}, "ramp": {"value"},
    "water": {"level"}, "blight": {"value"}, "boundary": {"value"},
}


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


def _raw(height: float) -> int:
    return int(min(max(round(height * 4 + RAW_ZERO), 0), RAW_MAX))


def _bounds(t: w3e.Terrain) -> list[float]:
    return [t.offset_x, t.offset_y, *_xy(t, t.width - 1, t.height - 1)]


# ---- get -----------------------------------------------------------------------------------------------------
def terrain_get(project, area: list | None = None, layers: list | None = None, step: int = 1) -> dict:
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
    columns, rows = range(c0, c1 + 1, step), range(r0, r1 + 1, step)
    if not columns or not rows:
        raise _bad("area", f"no terrain corners inside {area}; the map spans {_bounds(t)}")
    if len(columns) * len(rows) > MAX_CORNERS:
        raise ToolError("too_large", f"{len(columns)}x{len(rows)} corners is more than {MAX_CORNERS}",
                        hint="pass a smaller area or a larger step")
    pathing = None
    if "pathing" in layers:
        data = _read(project, "war3map.wpm")
        try:
            pathing = wpm.parse(data) if data is not None else None
        except FormatError:
            pathing = None
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
                line["water"].append(_out(_height(c["water_level"]) + WATER_OFFSET) if c["water"] else None)
            if "flags" in line:
                line["flags"].append("".join(k for k, name in (("r", "ramp"), ("b", "blight"), ("w", "water"),
                                                                 ("x", "boundary")) if c[name]))
            if "pathing" in line:
                cell = None
                if pathing is not None:
                    px, py = min(cx * 4, pathing.width - 1), min(cy * 4, pathing.height - 1)
                    cell = pathing.cells[py * pathing.width + px]
                line["pathing"].append(None if cell is None else "".join(
                    k for k, bit in (("w", 2), ("f", 4), ("b", 8), ("B", 0x20)) if cell & bit))
        for name in layers:
            grids[name].append(line[name])
    return {"version": t.version, "tileset": t.tileset, "tiles": [x.decode("latin-1") for x in t.tiles],
            "cliff_tiles": [x.decode("latin-1") for x in t.cliff_tiles], "corners": [t.width, t.height],
            "bounds": _bounds(t),
            "window": {"left": _xy(t, c0, r0)[0], "bottom": _xy(t, c0, r0)[1], "step": step, "columns": len(columns),
                       "rows": len(rows), "note": "rows run south to north; row j, column i is at (left + i * step * "
                                                  "128, bottom + j * step * 128)"},
            "layers": grids}


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


class _Brush:
    """Brush operations on a parsed terrain; raise ToolError("bad_value") on bad input."""

    def __init__(self, t: w3e.Terrain, catalog=None):
        self.t, self.catalog = t, catalog

    def corners(self, op: dict, path: str):
        x, y = _num(op.get("x"), f"{path}.x"), _num(op.get("y"), f"{path}.y")
        r = _num(op.get("radius"), f"{path}.radius")
        if not 0 < r <= 65536:
            raise _bad(f"{path}.radius", "expected a radius greater than 0")
        t = self.t
        out = []
        for cy in range(max(0, math.ceil((y - r - t.offset_y) / 128)), min(t.height - 1, math.floor((y + r - t.offset_y) / 128)) + 1):
            for cx in range(max(0, math.ceil((x - r - t.offset_x) / 128)), min(t.width - 1, math.floor((x + r - t.offset_x) / 128)) + 1):
                d = math.dist((x, y), _xy(t, cx, cy))
                if d <= r:
                    out.append((cx, cy, d))
        if not out:
            raise _bad(path, f"the brush at ({x}, {y}) radius {r} covers no terrain corner; the map spans {_bounds(t)}")
        return out, x, y, r

    def _flag(self, op: dict, path: str) -> bool:
        return _bool(op.get("value", True), f"{path}.value")

    def apply(self, op: dict, path: str) -> None:
        kind = op.get("op")
        extra = set(op) - {"op", "x", "y", "radius"} - BRUSH_KEYS[kind]
        if extra:
            raise ToolError("bad_op", f"{path}: unknown keys {sorted(extra)} for {kind}", hint=_HINT)
        corners, x, y, r = self.corners(op, path)
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
                raw = _raw(_num(level, f"{path}.level") - WATER_OFFSET)
                for cx, cy, _ in corners:
                    w3e.set_corner(t, cx, cy, water=True, water_level=raw)
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
            limit = 1 << w3e._TEXTURE_BITS[self.t.version]
            if len(self.t.tiles) >= min(limit, 16):
                raise _bad(path, f"the map already uses {len(self.t.tiles)} ground tiles, the most the World Editor "
                                 "allows; paint with one of terrain_get's tiles")
            self.t.tiles.append(tile)
        return self.t.tiles.index(tile)

    def _cliff_index(self, value, path: str) -> int:
        cliff = self._catalog_id("cliff", value, path)
        if cliff not in self.t.cliff_tiles:
            if len(self.t.cliff_tiles) >= 2:
                raise _bad(path, "the map already uses 2 cliff tiles, the most the World Editor allows")
            self.t.cliff_tiles.append(cliff)
        return self.t.cliff_tiles.index(cliff)


def terrain_edit(project, catalog, ops: list) -> dict:
    t, before = _load(project)
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
    return {"changed": changed, "warnings": [DERIVED_WARNING] if changed else []}


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


def terrain_render(project, catalog, scale: int | None = None, objects: bool = True) -> bytes:
    """PNG of the map from above, north up: tile colours, height shading, cliffs, water, blight, boundary, and
    optionally regions (cyan), start locations (white), units (red) and items (yellow)."""
    t, _ = _load(project)
    w, h = t.width - 1, t.height - 1
    scale = scale or max(1, min(8, 1024 // max(w, h, 1)))
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
    depth = ((water[:-1, :-1] & 0x3FFF) - RAW_ZERO) / 4 + WATER_OFFSET - z[:-1, :-1]
    wet = (flag(2) == 1) & (depth > 0)
    rgb[wet] = rgb[wet] * 0.25 + (np.array([40, 90, 160]) * (1 - np.clip(depth[wet], 0, 512) / 1024)[:, None]) * 0.75
    rgb[flag(3) == 1] *= 0.35
    image = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8)[::-1], "RGB")
    image = image.resize((w * scale, h * scale), Image.NEAREST)
    if objects:
        draw = ImageDraw.Draw(image)

        def px(x: float, y: float) -> tuple[float, float]:
            return (x - t.offset_x) / 128 * scale, (h - (y - t.offset_y) / 128) * scale

        rdata = _read(project, "war3map.w3r")
        try:
            regions = w3r.parse(rdata).regions if rdata else []
        except FormatError:
            regions = []
        for g in regions:
            (x0, y0), (x1, y1) = px(g.left, g.top), px(g.right, g.bottom)
            draw.rectangle([x0, y0, x1, y1], outline=(0, 230, 230))
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
