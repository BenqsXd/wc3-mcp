"""Scenery that looks placed rather than scattered: forests with a density that thins toward their edge, props in
even lines along a path, town blocks whose buildings face their street, clumps of rocks and flowers, and clearing an
area before building in it. Placed objects only; the ground under them is terrain_edit's job (paint a road along the
same path, and the town op returns its streets for exactly that).

The sampling is Bridson Poisson disk, not random darts: every object keeps its distance from its neighbours, which is
what makes a forest read as a forest instead of a rash. Everything takes a seed and is deterministic.
"""
import math
import random

from ..errors import ToolError
from .elements import _bad, _int, _num

# op -> the keys it takes besides its own placement fields (which go on every object it makes)
OP_KEYS = {
    "forest": {"op", "kind", "types", "rect", "x", "y", "radius", "path", "width", "density", "spacing", "edge",
               "clearings", "clearing_radius", "exclude", "on_tiles", "where", "seed", "count"},
    "line": {"op", "kind", "types", "path", "spacing", "offset", "sides", "jitter", "face", "exclude", "where",
             "seed", "skip_blocked"},
    "town": {"op", "kind", "types", "rect", "block", "street", "margin", "spacing", "fill", "props", "prop_spacing",
             "plaza", "exclude", "where", "seed"},
    "cluster": {"op", "kind", "types", "x", "y", "radius", "count", "spacing", "falloff", "scale_range", "exclude",
                "where", "seed"},
    "clear": {"op", "kinds", "rect", "x", "y", "radius", "path", "width", "types"},
}
MAX_OBJECTS = 20000
FACE_NOTE = {"path": "along the path", "out": "away from the path", "in": "toward the path"}


def _rect_of(op: dict, path: str, bounds: list[float]) -> tuple[float, float, float, float]:
    """The op's area as a rectangle, clamped to the map (a circle and a path give their bounding box)."""
    if "rect" in op:
        rect = op["rect"]
        if not isinstance(rect, list) or len(rect) != 4:
            raise _bad(f"{path}.rect", "expected [left, bottom, right, top]")
        left, bottom, right, top = (_num(v, f"{path}.rect[{i}]") for i, v in enumerate(rect))
    elif "radius" in op:
        cx, cy = _num(op.get("x"), f"{path}.x"), _num(op.get("y"), f"{path}.y")
        r = _num(op["radius"], f"{path}.radius")
        left, bottom, right, top = cx - r, cy - r, cx + r, cy + r
    elif "path" in op:
        points = _path(op, path)
        half = _num(op.get("width", 512), f"{path}.width") / 2
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        left, bottom, right, top = min(xs) - half, min(ys) - half, max(xs) + half, max(ys) + half
    else:
        left, bottom, right, top = bounds
    left, bottom = max(left, bounds[0]), max(bottom, bounds[1])
    right, top = min(right, bounds[2]), min(top, bounds[3])
    if left >= right or bottom >= top:
        raise _bad(path, f"the area does not overlap the playable area {bounds}")
    return left, bottom, right, top


def _path(op: dict, path: str) -> list[tuple[float, float]]:
    points = op.get("path")
    if not isinstance(points, list) or len(points) < 2:
        raise _bad(f"{path}.path", "expected [[x, y], [x, y], ...] with at least two points")
    out = []
    for i, p in enumerate(points):
        if not isinstance(p, list) or len(p) != 2:
            raise _bad(f"{path}.path[{i}]", "expected [x, y]")
        out.append((_num(p[0], f"{path}.path[{i}][0]"), _num(p[1], f"{path}.path[{i}][1]")))
    return out


def distance_to_path(points, x: float, y: float) -> float:
    best = float("inf")
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        dx, dy = bx - ax, by - ay
        length = dx * dx + dy * dy
        t = 0.0 if length == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / length))
        best = min(best, math.hypot(x - (ax + t * dx), y - (ay + t * dy)))
    return best


def along_path(points, spacing: float) -> list[tuple[float, float, float]]:
    """(x, y, angle in degrees) every `spacing` units along the polyline, starting at its first point."""
    out, carry = [], 0.0
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        length = math.hypot(bx - ax, by - ay)
        if length == 0:
            continue
        angle = math.degrees(math.atan2(by - ay, bx - ax))
        step = carry
        while step <= length:
            out.append((ax + (bx - ax) * step / length, ay + (by - ay) * step / length, angle))
            step += spacing
        carry = step - length
    return out


def noise(seed: int, cell: float = 1024.0):
    """Smooth value noise in 0..1: a coarse random lattice with cosine interpolation. One call per (x, y)."""
    rng = random.Random(seed)
    base = rng.random() * 1000
    cache: dict[tuple[int, int], float] = {}

    def lattice(ix: int, iy: int) -> float:
        if (ix, iy) not in cache:
            cache[(ix, iy)] = random.Random((ix * 73856093) ^ (iy * 19349663) ^ int(base * 1000)).random()
        return cache[(ix, iy)]

    def at(x: float, y: float) -> float:
        fx, fy = x / cell, y / cell
        ix, iy = math.floor(fx), math.floor(fy)
        tx = (1 - math.cos((fx - ix) * math.pi)) / 2
        ty = (1 - math.cos((fy - iy) * math.pi)) / 2
        top = lattice(ix, iy) * (1 - tx) + lattice(ix + 1, iy) * tx
        bottom = lattice(ix, iy + 1) * (1 - tx) + lattice(ix + 1, iy + 1) * tx
        return top * (1 - ty) + bottom * ty

    return at


def poisson(rng: random.Random, rect, radius_at, limit: int, tries: int = 24) -> list[tuple[float, float]]:
    """Bridson Poisson-disk samples in `rect`, with the minimum distance given per point by radius_at(x, y);
    radius_at returns 0 or less where nothing may stand. Points come out in growth order, so a truncated list still
    covers the whole area."""
    left, bottom, right, top = rect
    # the grid cell follows the smallest distance that is actually used; a 0 means "nothing here", not "very dense",
    # and taking it for the cell size would make every neighbour check scan thousands of cells
    samples = [radius_at(left + (right - left) * i / 8, bottom + (top - bottom) * j / 8)
               for i in range(9) for j in range(9)]
    positive = [r for r in samples if r > 0]
    smallest = max(1.0, min(positive) if positive else (right - left + top - bottom) / 40)
    cell = smallest / math.sqrt(2)
    cols, rows = max(1, int((right - left) / cell) + 1), max(1, int((top - bottom) / cell) + 1)
    grid: dict[tuple[int, int], list[tuple[float, float]]] = {}
    out: list[tuple[float, float]] = []
    active: list[tuple[float, float]] = []

    def fits(x: float, y: float, r: float) -> bool:
        if not (left <= x <= right and bottom <= y <= top) or r <= 0:
            return False
        gx, gy = int((x - left) / cell), int((y - bottom) / cell)
        # ponytail: a candidate whose radius is more than a dozen grid cells only checks its 12-cell neighbourhood,
        # so a density range beyond about 8x can let two objects end up closer than the sparse one asked for
        reach = min(int(r / cell) + 1, 12)
        for ix in range(gx - reach, gx + reach + 1):
            for iy in range(gy - reach, gy + reach + 1):
                for px, py in grid.get((ix, iy), ()):
                    if (px - x) ** 2 + (py - y) ** 2 < r * r:
                        return False
        return True

    def add(x: float, y: float) -> None:
        out.append((x, y))
        active.append((x, y))
        grid.setdefault((int((x - left) / cell), int((y - bottom) / cell)), []).append((x, y))

    for _ in range(200):   # a first point somewhere the density allows
        x, y = rng.uniform(left, right), rng.uniform(bottom, top)
        if radius_at(x, y) > 0:
            add(x, y)
            break
    while active and len(out) < limit:
        i = rng.randrange(len(active))
        px, py = active[i]
        base = radius_at(px, py) or smallest
        for _ in range(tries):
            angle, distance = rng.uniform(0, math.tau), rng.uniform(base, base * 2)
            x, y = px + math.cos(angle) * distance, py + math.sin(angle) * distance
            if fits(x, y, radius_at(x, y)):
                add(x, y)
                break
        else:
            active.pop(i)
            if not active and len(out) < limit:   # the density map can leave islands: restart from a free spot
                for _ in range(60):
                    x, y = rng.uniform(left, right), rng.uniform(bottom, top)
                    if fits(x, y, radius_at(x, y)):
                        add(x, y)
                        break
    return out


def blocks(rect, block_w: float, block_h: float, street: float):
    """(lot rectangles, street segments) of a town grid filling `rect`: streets run between the blocks."""
    left, bottom, right, top = rect
    lots, streets = [], []
    x = left
    while x + block_w <= right + 1:
        y = bottom
        while y + block_h <= top + 1:
            lots.append((x, y, x + block_w, y + block_h))
            y += block_h + street
        x += block_w + street
    x = left - street / 2
    while x <= right + 1:
        streets.append([[x, bottom - street / 2], [x, top + street / 2]])
        x += block_w + street
    y = bottom - street / 2
    while y <= top + 1:
        streets.append([[left - street / 2, y], [right + street / 2, y]])
        y += block_h + street
    return lots, streets


def facing(dx: float, dy: float) -> float:
    return round(math.degrees(math.atan2(dy, dx)) % 360, 1)


def pick(rng: random.Random, weights: dict[str, float]) -> str:
    total, roll = sum(weights.values()), None
    roll = rng.uniform(0, total)
    for key, weight in weights.items():
        roll -= weight
        if roll <= 0:
            return key
    return next(iter(weights))


class LayoutOps:
    """placed_edit ops that build scenery. Mixed into _Edit, which supplies op_add, the terrain and the type checks."""

    # ---- shared parts ------------------------------------------------------------------------------------------
    def _layout_common(self, op: dict, path: str, kind_default: str = "destructible"):
        kind = op.get("kind", kind_default)
        if kind not in ("unit", "item", "doodad", "destructible"):
            raise ToolError("bad_kind", f"{path}: kind must be unit, item, doodad or destructible")
        weights = self._weights(op, kind, path)
        fields = {k: v for k, v in op.items() if k not in OP_KEYS[op["op"]]}
        extra = (set(fields) - self._fields(kind)) | ({"type"} & set(fields))
        if extra:
            raise ToolError("bad_op", f"{path}: {op['op']} has no fields {sorted(extra)}")
        zones = self._zones(op, path)
        return kind, weights, fields, zones, random.Random(op.get("seed"))

    def _weights(self, op: dict, kind: str, path: str) -> dict[str, float]:
        types = op.get("types")
        if isinstance(types, str):
            types = [types]
        if isinstance(types, list):
            types = {t: 1 for t in types}
        if not isinstance(types, dict) or not types:
            raise _bad(f"{path}.types", 'expected {"type id": weight, ...}, a list of ids, or one id')
        out = {}
        for t, w in types.items():
            self._type(kind, t, f"{path}.types.{t}")
            out[t] = _num(w, f"{path}.types.{t}")
            if out[t] <= 0:
                raise _bad(f"{path}.types.{t}", "weights are > 0")
        return out

    def _place(self, kind: str, type_id: str, x: float, y: float, fields: dict, rng: random.Random,
               path: str, angle=None, scale=None) -> None:
        add = {"op": "add", "kind": kind, "type": type_id, "x": round(x, 1), "y": round(y, 1), **fields}
        if kind in ("doodad", "destructible"):
            if "variation" not in fields:
                found = self._variations(kind, type_id)
                add["variation"] = rng.choice(found) if found else 0
            if "angle" not in fields:
                add["angle"] = round(angle if angle is not None else rng.uniform(0, 360), 1)
            if scale is not None and "scale" not in fields:
                add["scale"] = round(scale, 3)
        elif angle is not None and "angle" not in fields:
            add["angle"] = round(angle, 1)
        self.op_add(add, path)

    def _tile_at(self, x: float, y: float) -> str | None:
        from ..formats import w3e

        t = self.terrain
        if t is None:
            return None
        cx = min(max(round((x - t.offset_x) / 128), 0), t.width - 1)
        cy = min(max(round((y - t.offset_y) / 128), 0), t.height - 1)
        c = w3e.corner(t, cx, cy)
        return t.tiles[c["texture"]].decode("latin-1") if c["texture"] < len(t.tiles) else None

    def _ok_here(self, x: float, y: float, where: str, zones, tiles) -> bool:
        if not self._ground_ok(x, y, where):
            return False
        if any(_zone_hit(z, x, y) for z in zones):
            return False
        return not tiles or (self._tile_at(x, y) in tiles)

    def _on_tiles(self, op: dict, path: str) -> set[str]:
        wanted = op.get("on_tiles")
        if wanted is None:
            return set()
        if isinstance(wanted, str):
            wanted = [wanted]
        if not isinstance(wanted, list) or not all(isinstance(t, str) for t in wanted):
            raise _bad(f"{path}.on_tiles", 'expected a list of tile ids, e.g. ["Lgrs", "Ldrg"]')
        return set(wanted)

    # ---- ops ---------------------------------------------------------------------------------------------------
    def op_forest(self, op: dict, path: str) -> None:
        """Trees (or any type) at a Poisson-disk spacing, thinner toward the edge of the area and around clearings,
        so the wood has a canopy and a rim instead of one flat density."""
        kind, weights, fields, zones, rng = self._layout_common(op, path)
        bounds = self.playable() or self.whole() or [-4096.0, -4096.0, 4096.0, 4096.0]
        rect = _rect_of(op, path, bounds)
        tiles = self._on_tiles(op, path)
        where = op.get("where", "land")
        spacing = _num(op.get("spacing", 160), f"{path}.spacing")
        density = _num(op.get("density", 1.0), f"{path}.density")
        if not 0 < density <= 1:
            raise _bad(f"{path}.density", "expected a share of the full density, 0 < density <= 1")
        edge = _num(op.get("edge", 384), f"{path}.edge")
        limit = _int(op.get("count", MAX_OBJECTS), f"{path}.count", 1, MAX_OBJECTS)
        points = _path(op, path) if "path" in op else None
        half = _num(op.get("width", 512), f"{path}.width") / 2 if points else 0.0
        circle = None
        if "radius" in op and "rect" not in op:
            circle = (_num(op["x"], f"{path}.x"), _num(op["y"], f"{path}.y"), _num(op["radius"], f"{path}.radius"))
        clearings = []
        for _ in range(_int(op.get("clearings", 0), f"{path}.clearings", 0, 50)):
            radius = _num(op.get("clearing_radius", 384), f"{path}.clearing_radius")
            clearings.append((rng.uniform(rect[0], rect[2]), rng.uniform(rect[1], rect[3]), radius))
        thin = noise(rng.randrange(1 << 30), cell=max(spacing * 8, 768))

        def inside(x: float, y: float) -> float:
            """0 at the edge of the area, 1 well inside it."""
            if circle:
                room = circle[2] - math.hypot(x - circle[0], y - circle[1])
            elif points:
                room = half - distance_to_path(points, x, y)
            else:
                room = min(x - rect[0], rect[2] - x, y - rect[1], rect[3] - y)
            for cx, cy, r in clearings:
                room = min(room, math.hypot(x - cx, y - cy) - r)
            return max(0.0, min(1.0, room / edge)) if edge > 0 else (1.0 if room > 0 else 0.0)

        def radius_at(x: float, y: float) -> float:
            share = inside(x, y)
            if share <= 0 or not self._ok_here(x, y, where, zones, tiles):
                return 0.0
            # thin the wood with noise and toward its rim: a bigger minimum distance means fewer trees
            local = density * (0.35 + 0.65 * share) * (0.55 + 0.45 * thin(x, y))
            return spacing / max(local, 0.05)

        placed = poisson(rng, rect, radius_at, limit)
        for i, (x, y) in enumerate(placed):
            self._place(kind, pick(rng, weights), x, y, fields, rng, f"{path}[{i}]")
        self.notes.append(f"{path}: {len(placed)} {kind}(s) in the wood"
                          + (f", {len(clearings)} clearing(s)" if clearings else ""))

    def op_line(self, op: dict, path: str) -> None:
        """Objects at an even spacing along a path: fences, lamp rows, docks, the props along a road."""
        kind, weights, fields, zones, rng = self._layout_common(op, path, kind_default="doodad")
        points = _path(op, path)
        spacing = _num(op.get("spacing", 256), f"{path}.spacing")
        if spacing <= 0:
            raise _bad(f"{path}.spacing", "expected a spacing above 0")
        offset = _num(op.get("offset", 0), f"{path}.offset")
        jitter = _num(op.get("jitter", 0), f"{path}.jitter")
        sides = op.get("sides", "both" if offset else "center")
        if sides not in ("both", "left", "right", "alternate", "center"):
            raise _bad(f"{path}.sides", 'expected "both", "left", "right", "alternate" or "center"')
        face = op.get("face", "path")
        if not (isinstance(face, (int, float)) or face in FACE_NOTE):
            raise _bad(f"{path}.face", 'expected "path", "out", "in" or an angle in degrees')
        where, skipped, n = op.get("where", "land"), 0, 0
        for i, (x, y, angle) in enumerate(along_path(points, spacing)):
            for side in ({"both": (1, -1), "left": (1,), "right": (-1,), "center": (0,),
                          "alternate": (1 if i % 2 == 0 else -1,)}[sides]):
                nx, ny = -math.sin(math.radians(angle)), math.cos(math.radians(angle))
                px = x + nx * offset * side + (rng.uniform(-jitter, jitter) if jitter else 0)
                py = y + ny * offset * side + (rng.uniform(-jitter, jitter) if jitter else 0)
                if not self._ok_here(px, py, where, zones, set()):
                    skipped += 1
                    continue
                if isinstance(face, (int, float)):
                    heading = float(face)
                elif face == "path":
                    heading = angle
                else:
                    heading = facing(nx * side, ny * side) + (180 if face == "in" else 0)
                self._place(kind, pick(rng, weights), px, py, fields, rng, f"{path}[{n}]", angle=heading % 360)
                n += 1
        self.notes.append(f"{path}: {n} {kind}(s) along the path"
                          + (f", {skipped} skipped where the ground did not allow one" if skipped else ""))

    def op_town(self, op: dict, path: str) -> None:
        """Blocks of buildings along a street grid: every building stands one row in from its street and faces it,
        with props between the buildings on the street side. The block middles stay free (yards), and the streets
        come back in the result for terrain_edit to pave."""
        kind, weights, fields, zones, rng = self._layout_common(op, path, kind_default="unit")
        bounds = self.playable() or self.whole() or [-4096.0, -4096.0, 4096.0, 4096.0]
        rect = _rect_of(op, path, bounds)
        block = op.get("block", [768, 768])
        if not isinstance(block, list) or len(block) != 2:
            raise _bad(f"{path}.block", "expected [width, height] of one block in world units")
        block_w, block_h = (_num(v, f"{path}.block") for v in block)
        street = _num(op.get("street", 384), f"{path}.street")
        margin = _num(op.get("margin", 128), f"{path}.margin")
        spacing = _num(op.get("spacing", 256), f"{path}.spacing")
        fill = _num(op.get("fill", 1.0), f"{path}.fill")
        plaza = op.get("plaza")
        if plaza is not None and (not isinstance(plaza, list) or len(plaza) != 4):
            raise _bad(f"{path}.plaza", "expected [left, bottom, right, top] of an area to leave open")
        prop_weights = self._weights({"types": op["props"]}, "doodad", f"{path}.props") if op.get("props") else {}
        prop_spacing = _num(op.get("prop_spacing", 256), f"{path}.prop_spacing")
        where = op.get("where", "land")
        lots, streets = blocks(rect, block_w, block_h, street)
        built, props, skipped = 0, 0, 0
        for lot in lots:
            lx, ly, rx, ry = lot
            # one row of buildings per block side, set back by margin, all facing the street outside it
            for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                if dy:   # a side along x
                    y = (ly + margin) if dy < 0 else (ry - margin)
                    slots = [(x, y) for x, _ in _steps(lx + margin, rx - margin, spacing)]
                else:
                    x = (lx + margin) if dx < 0 else (rx - margin)
                    slots = [(x, y) for y, _ in _steps(ly + margin, ry - margin, spacing)]
                for i, (bx, by) in enumerate(slots):
                    if plaza and _zone_hit(("rect", *plaza), bx, by):
                        continue
                    if rng.random() > fill:
                        if prop_weights and self._ok_here(bx + dx * margin, by + dy * margin, where, zones, set()):
                            self._place("doodad", pick(rng, prop_weights), bx + dx * margin, by + dy * margin, {},
                                        rng, f"{path}.props[{props}]", angle=facing(dx, dy))
                            props += 1
                        continue
                    if not self._ok_here(bx, by, where, zones, set()):
                        skipped += 1
                        continue
                    self._place(kind, pick(rng, weights), bx, by, fields, rng, f"{path}[{built}]",
                                angle=facing(dx, dy))
                    built += 1
                    if prop_weights and prop_spacing > 0 and i < len(slots) - 1:   # between two buildings
                        px = bx + (dx * margin if dx else spacing / 2)
                        py = by + (dy * margin if dy else spacing / 2)
                        if self._ok_here(px, py, where, zones, set()):
                            self._place("doodad", pick(rng, prop_weights), px, py, {}, rng,
                                        f"{path}.props[{props}]", angle=facing(dx, dy))
                            props += 1
        self.streets += streets
        self.notes.append(f"{path}: {built} building(s) around {len(lots)} block(s)"
                          + (f", {props} prop(s)" if props else "")
                          + (f", {skipped} spot(s) skipped where the ground did not allow a building" if skipped else "")
                          + "; streets are in the result for terrain_edit to pave")

    def op_cluster(self, op: dict, path: str) -> None:
        """A clump: dense in the middle, thinning out, and the objects shrink toward the rim when scale_range is
        given. Rocks, rubble, flower beds."""
        kind, weights, fields, zones, rng = self._layout_common(op, path, kind_default="doodad")
        cx, cy = _num(op.get("x"), f"{path}.x"), _num(op.get("y"), f"{path}.y")
        radius = _num(op.get("radius", 384), f"{path}.radius")
        spacing = _num(op.get("spacing", 128), f"{path}.spacing")
        falloff = _num(op.get("falloff", 1.0), f"{path}.falloff")
        count = _int(op.get("count", 24), f"{path}.count", 1, MAX_OBJECTS)
        scale_range = op.get("scale_range")
        if scale_range is not None and (not isinstance(scale_range, list) or len(scale_range) != 2):
            raise _bad(f"{path}.scale_range", "expected [smallest, biggest] scale")
        where = op.get("where", "land")

        def radius_at(x: float, y: float) -> float:
            share = math.hypot(x - cx, y - cy) / radius
            if share > 1 or not self._ok_here(x, y, where, zones, set()):
                return 0.0
            return spacing * (1 + falloff * share * 2)   # the rim spreads out

        placed = poisson(rng, (cx - radius, cy - radius, cx + radius, cy + radius), radius_at, count)
        for i, (x, y) in enumerate(placed):
            scale = None
            if scale_range:
                near = 1 - math.hypot(x - cx, y - cy) / radius
                scale = float(scale_range[0]) + (float(scale_range[1]) - float(scale_range[0])) * near
            self._place(kind, pick(rng, weights), x, y, fields, rng, f"{path}[{i}]", scale=scale)
        self.notes.append(f"{path}: {len(placed)} {kind}(s) in the clump")

    def op_clear(self, op: dict, path: str) -> None:
        """Delete the placed objects in an area: what a road, a plaza or a building site needs before it is built."""
        kinds = op.get("kinds", ["doodad", "destructible"])
        if isinstance(kinds, str):
            kinds = [kinds]
        if not isinstance(kinds, list) or any(k not in KINDS_CLEARABLE for k in kinds):
            raise _bad(f"{path}.kinds", "expected any of: " + ", ".join(KINDS_CLEARABLE))
        types = op.get("types")
        if isinstance(types, str):
            types = [types]
        wanted = set(types) if types else None
        points = _path(op, path) if "path" in op else None
        half = _num(op.get("width", 384), f"{path}.width") / 2 if points else 0.0
        circle = None
        if "radius" in op:
            circle = (_num(op["x"], f"{path}.x"), _num(op["y"], f"{path}.y"), _num(op["radius"], f"{path}.radius"))
        rect = None
        if "rect" in op:
            rect = tuple(_num(v, f"{path}.rect") for v in op["rect"])
        if not (points or circle or rect):
            raise _bad(path, 'clear needs an area: "rect", "x"/"y"/"radius" or "path" with "width"')

        def hit(x: float, y: float) -> bool:
            if circle and math.hypot(x - circle[0], y - circle[1]) <= circle[2]:
                return True
            if rect and rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]:
                return True
            return bool(points and distance_to_path(points, x, y) <= half)

        removed = 0
        for kind in kinds:
            for ref in self._refs_in(kind, hit, wanted):
                self.op_delete({"op": "delete", "ref": ref}, path)
                removed += 1
        self.notes.append(f"{path}: {removed} object(s) removed from the area")


KINDS_CLEARABLE = ("doodad", "destructible", "unit", "item")
# what the spacing spread says about a layout: a machine grid is far too even, a rash of darts far too uneven
CV_NOTE = ("spread is the spacing's coefficient of variation: below 0.1 the objects sit on a grid, 0.15-0.45 reads "
           "as placed by hand, above 0.6 as random clumps with holes")


def layout_check(project, catalog, area=None, kinds=None, min_distance: float | None = None) -> dict:
    """Numbers a top-down render cannot show: how evenly the placed objects are spaced, how many stand on ground
    they do not belong on, and how much of the map a player can still walk to."""
    from .pathing import CORNER, NOTE, corner_of, reachable, walkable
    from .placed import _Map, _id

    scene = _Map(project, catalog)
    terrain = scene.terrain
    if terrain is None:
        raise ToolError("no_terrain", "the map has no war3map.w3e", hint="terrain_get shows the terrain")
    wanted = set(kinds or ("doodad", "destructible", "unit", "item"))
    box = tuple(area) if area else tuple(scene.whole() or (-4096, -4096, 4096, 4096))
    playable = scene.playable()
    rows, starts, blockers = [], {}, []
    for o in list(scene.doodads.doodads) + list(scene.units.units):
        kind = scene.kind_of(o)
        type_id = _id(o.id)
        if kind == "start_location":
            starts[o.owner] = (o.x, o.y)
            continue
        blockers.append((kind, type_id, o.x, o.y, o.angle))
        if kind in wanted and box[0] <= o.x <= box[2] and box[1] <= o.y <= box[3]:
            rows.append((kind, type_id, o.x, o.y))
    out: dict = {"area": list(box), "count": len(rows), "by_kind": {}, "by_type": {}}
    for kind, type_id, _x, _y in rows:
        out["by_kind"][kind] = out["by_kind"].get(kind, 0) + 1
        out["by_type"][type_id] = out["by_type"].get(type_id, 0) + 1
    out["by_type"] = dict(sorted(out["by_type"].items(), key=lambda kv: -kv[1])[:20])
    if rows:
        out["spacing"] = _spacing([(x, y) for _k, _t, x, y in rows], min_distance)
        out["spacing"]["note"] = CV_NOTE
        out["ground"] = _ground(scene, terrain, rows, playable)
    if starts:
        grid = walkable(terrain, catalog, blockers)
        free = sum(sum(row) for row in grid)
        seen = reachable(grid, [corner_of(terrain, x, y) for x, y in starts.values()])
        out["reach"] = {"walkable_corners": free, "reachable_from_starts": len(seen),
                        "share": round(len(seen) / free, 3) if free else 0.0,
                        "corner_units": CORNER, "note": NOTE}
    return out


def _spacing(points, min_distance: float | None) -> dict:
    """Nearest-neighbour distance statistics, through a grid so a few thousand objects stay cheap."""
    step = max(min_distance or 0, 256.0)
    grid: dict[tuple[int, int], list] = {}
    for x, y in points:
        grid.setdefault((int(x // step), int(y // step)), []).append((x, y))
    nearest = []
    for (gx, gy), cell in grid.items():
        near = [p for dx in (-1, 0, 1) for dy in (-1, 0, 1) for p in grid.get((gx + dx, gy + dy), ())]
        for x, y in cell:
            best = min((math.hypot(px - x, py - y) for px, py in near if (px, py) != (x, y)), default=None)
            if best is not None:
                nearest.append(best)
    if not nearest:
        return {"pairs": 0}
    nearest.sort()
    mean = sum(nearest) / len(nearest)
    spread = (sum((d - mean) ** 2 for d in nearest) / len(nearest)) ** 0.5 / mean if mean else 0.0
    out = {"pairs": len(nearest), "min": round(nearest[0]), "p10": round(nearest[len(nearest) // 10]),
           "median": round(nearest[len(nearest) // 2]), "mean": round(mean), "spread": round(spread, 2)}
    if min_distance:
        out["closer_than_min"] = sum(1 for d in nearest if d < min_distance)
    return out


def _ground(scene, terrain, rows, playable) -> dict:
    from ..formats import w3e
    from .terrain import deep, water_depth

    out = {"on_water": 0, "unwalkable": 0, "outside_playable": 0, "by_tile": {}, "reasons": {}}
    walk: dict = {}
    for kind, _type_id, x, y in rows:
        cx = min(max(round((x - terrain.offset_x) / 128), 0), terrain.width - 1)
        cy = min(max(round((y - terrain.offset_y) / 128), 0), terrain.height - 1)
        c = w3e.corner(terrain, cx, cy)
        tile = terrain.tiles[c["texture"]].decode("latin-1") if c["texture"] < len(terrain.tiles) else "?"
        depth = water_depth(terrain, c)
        near = [w3e.corner(terrain, nx, ny)["layer"] for nx in (cx - 1, cx, cx + 1) for ny in (cy - 1, cy, cy + 1)
                if 0 <= nx < terrain.width and 0 <= ny < terrain.height]
        if tile not in walk:
            walk[tile] = scene.catalog.tile_pathing(tile).get("walkable", True) if tile != "?" else True
        why = [name for name, hit in (
            ("deep_water", deep(terrain, depth)), ("shallow_water", depth is not None and not deep(terrain, depth)),
            ("cliff", not c["ramp"] and any(v != c["layer"] for v in near)), ("boundary", c["boundary"]),
            ("unwalkable_tile", not walk[tile]),
            ("outside_playable", bool(playable) and not (playable[0] <= x <= playable[2]
                                                         and playable[1] <= y <= playable[3]))) if hit]
        if depth is not None:
            out["on_water"] += 1
        if not scene._ground_ok(x, y, "land"):
            out["unwalkable"] += 1
        if "outside_playable" in why:
            out["outside_playable"] += 1
        for name in why:
            out["reasons"].setdefault(kind, {})[name] = out["reasons"].get(kind, {}).get(name, 0) + 1
        out["by_tile"][tile] = out["by_tile"].get(tile, 0) + 1
    out["by_tile"] = dict(sorted(out["by_tile"].items(), key=lambda kv: -kv[1]))
    out["note"] = ("unwalkable counts objects on water, a cliff edge or the map boundary, where the game will not "
                   "let a unit stand; reasons splits every such object by kind and cause (shallow_water is wadeable, "
                   "deep_water is not; trees in shallow water on purpose show up there); by_tile shows which ground "
                   "they ended up on")
    return out


def _steps(start: float, end: float, step: float):
    value = start
    while value <= end:
        yield value, 1
        value += step


def _zone_hit(zone, x: float, y: float) -> bool:
    if zone[0] == "rect":
        return zone[1] <= x <= zone[3] and zone[2] <= y <= zone[4]
    return (x - zone[1]) ** 2 + (y - zone[2]) ** 2 <= zone[3] ** 2
