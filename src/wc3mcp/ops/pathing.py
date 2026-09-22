"""Where units can walk: the terrain's own pathing plus the footprints of placed objects, and what that leaves
reachable. The grid is the terrain corner grid (128 units), so a corner counts as blocked when any part of a footprint
covers it - a unit needs more room than one pathing cell anyway. Used by map_validate and layout_check.
"""
import math
from collections import deque

from .terrain import _corner_pathing

# pathing texture field per kind; "none" means the type has no footprint
FOOTPRINT_FIELDS = {"destructible": "bptx", "doodad": "dptx", "unit": "upat"}
CELL = 32          # world units per pathing texture pixel
CORNER = 128       # world units per terrain corner
NOTE = ("walkability from the terrain plus the pathing texture of every placed object, on the 128-unit corner grid "
        "(a corner any footprint touches counts blocked), without the game's own unit collision")


def _blocked_pixels(catalog, path: str, cache: dict) -> tuple[int, int, frozenset] | None:
    """(width, height, the pixels that stop walking) of a pathing texture, or None when there is none. The catalog
    keeps the cache (data_search reads the same textures), so `cache` is only the caller's own shortcut."""
    if path not in cache:
        cache[path] = catalog.pathing_pixels(path)
    return cache[path]


def footprint(catalog, kind: str, type_id: str, value, cache: dict) -> tuple[int, int, frozenset] | None:
    """The blocked pixels of a type's pathing texture; `value(kind, id, field)` gives the map's own field value."""
    field = FOOTPRINT_FIELDS.get(kind)
    return None if field is None else _blocked_pixels(catalog, str(value(kind, type_id, field) or ""), cache)


FIXED_ROTATION_FIELDS = {"doodad": "dfxr", "destructible": "bfxr"}


def fixed_rotation(value, kind: str, type_id: str) -> float | None:
    """The angle (degrees) a type always stands at, or None when it may turn: the editor rewrites any other angle,
    so an object stored at another one by an older version is pathed the way the game will see it."""
    field = FIXED_ROTATION_FIELDS.get(kind)
    try:
        angle = float(value(kind, type_id, field)) if field else -1.0
    except (TypeError, ValueError):
        return None
    return angle if angle >= 0 else None


def footprint_cells(found, kind: str, x: float, y: float, angle: float, terrain):
    """The 32-unit cells (column, row from the map's south-west corner) a footprint blocks. The texture's top row
    is north for a doodad facing 270 degrees, and it turns with the doodad in quarter turns (measured against the
    World Editor's war3map.wpm on the shipped maps); buildings keep theirs unturned."""
    w, h, blocked = found
    turn = 0 if kind == "unit" else (round(math.degrees(angle) / 90) * 90 + 90) % 360
    c, s = round(math.cos(math.radians(turn))), round(math.sin(math.radians(turn)))
    cx0, cy0 = (x - terrain.offset_x) / CELL, (y - terrain.offset_y) / CELL
    for px, py in blocked:
        dx, dy = px - w / 2 + 0.5, h / 2 - 0.5 - py
        yield math.floor(cx0 + dx * c - dy * s), math.floor(cy0 + dx * s + dy * c)


def walkable(terrain, catalog, objects, value=None) -> list[list[bool]]:
    """Grid[y][x] over the terrain corners: True where a unit can walk. `objects` is (kind, type id, x, y[, angle
    in radians])."""
    cache: dict = {}
    value = value or (lambda kind, oid, field: catalog.field(kind, oid, field))
    grid = [[("w" not in _corner_pathing(terrain, catalog, x, y, cache)) for x in range(terrain.width)]
            for y in range(terrain.height)]
    textures: dict = {}
    for kind, type_id, x, y, *rest in objects:
        found = footprint(catalog, kind, type_id, value, textures)
        if not found or not found[2]:
            continue
        fixed = fixed_rotation(value, kind, type_id)
        angle = math.radians(fixed) if fixed is not None else (rest[0] if rest else 4.712389)
        for gx, gy in footprint_cells(found, kind, x, y, angle, terrain):
            cx, cy = int(round((gx + 0.5) / 4)), int(round((gy + 0.5) / 4))   # the corner the cell touches
            if 0 <= cx < terrain.width and 0 <= cy < terrain.height:
                grid[cy][cx] = False
    return grid


def corner_of(terrain, x: float, y: float) -> tuple[int, int]:
    return (min(max(int(round((x - terrain.offset_x) / CORNER)), 0), terrain.width - 1),
            min(max(int(round((y - terrain.offset_y) / CORNER)), 0), terrain.height - 1))


def reachable(grid: list[list[bool]], starts, spread: int = 2) -> set[tuple[int, int]]:
    """Corners a unit can walk to from any start corner. `spread` also starts from the free corners around a start,
    so a start that sits on a building or a tree still reports the area around it."""
    height, width = len(grid), len(grid[0])
    queue = deque()
    seen: set[tuple[int, int]] = set()
    for sx, sy in starts:
        for dx in range(-spread, spread + 1):
            for dy in range(-spread, spread + 1):
                x, y = sx + dx, sy + dy
                if 0 <= x < width and 0 <= y < height and grid[y][x] and (x, y) not in seen:
                    seen.add((x, y))
                    queue.append((x, y))
    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < width and 0 <= ny < height and grid[ny][nx] and (nx, ny) not in seen:
                seen.add((nx, ny))
                queue.append((nx, ny))
    return seen


def world_of(terrain, cx: int, cy: int) -> tuple[float, float]:
    return terrain.offset_x + cx * CORNER, terrain.offset_y + cy * CORNER


# ---- the 32-unit cell grid: the resolution the game paths on ---------------------------------------------------
CELL_NOTE = ("walkability on the game's own 32-unit pathing cells: the terrain (war3map.wpm when the World Editor "
             "saved it after the last terrain and doodad edit, else derived from tiles, cliffs, water depth and the boundary) "
             "plus the pathing texture of every placed object, destructibles included; steps are orthogonal, so a "
             "gap must be at least one whole cell wide (units with a collision size above 16 need wider)")


def terrain_cells(terrain, catalog):
    """numpy bool array [row][column] of 32-unit cells a ground unit may stand on, from the terrain alone: cliff tiles,
    unwalkable tiles, water deeper than DEEP_WATER at the cell's shallowest point, and the boundary block."""
    import numpy as np

    from .terrain import DEEP_WATER, IMPASSABLE_WATER, RAW_ZERO, water_offset
    from ..formats import w3e

    grid = lambda values: np.asarray(values, dtype=np.int32).reshape(terrain.height, terrain.width)  # noqa: E731
    heights, tex, cliffs, water = grid(terrain.heights), grid(terrain.textures), grid(terrain.cliffs), grid(terrain.water)
    bits = w3e._TEXTURE_BITS[terrain.version]
    layer = cliffs & 15
    flag = lambda k: ((tex >> (bits + k)) & 1).astype(bool)  # noqa: E731
    ramp, wet_flag, boundary = flag(0), flag(2), flag(3)
    ground = (heights - RAW_ZERO) / 4 + (layer - 2) * 128
    surface = ((water & 0x3FFF) - RAW_ZERO) / 4 + water_offset(terrain)
    tiles = tex & ((1 << bits) - 1)
    walk = np.array([catalog.tile_pathing(x.decode("latin-1")).get("walkable", True) if catalog else True
                     for x in terrain.tiles] or [True])
    h, w = terrain.height - 1, terrain.width - 1
    j, i = np.mgrid[0:h * 4, 0:w * 4]
    ty, tx = j // 4, i // 4
    qy, qx = ty + (j % 4 >= 2), tx + (i % 4 >= 2)      # the corner whose quarter of the tile the cell is in
    quad = np.stack([layer[:-1, :-1], layer[1:, :-1], layer[:-1, 1:], layer[1:, 1:]])
    ramps = ramp[:-1, :-1] | ramp[1:, :-1] | ramp[:-1, 1:] | ramp[1:, 1:]
    cliff = ((quad.max(axis=0) != quad.min(axis=0)) & ~ramps)[ty, tx]
    # A cell is judged by its SHALLOWEST point, not its centre: measured against an editor-saved war3map.wpm, the
    # editor lets a unit stand on a cell whose shallow side is wadeable, so a sloping shore stays walkable about one
    # cell further out than a centre sample says (that one sampling change took the disagreement over a calibration
    # map from 0.58% of the cells to 0.05%). Depth is bilinear over a tile, so its minimum over a cell is the
    # smallest of the cell's four corner values. On flat water every sample is equal, which is where DEEP_WATER
    # itself was calibrated.
    below = surface - ground
    ny, nx = np.mgrid[0:h * 4 + 1, 0:w * 4 + 1]
    nty, ntx = np.minimum(ny // 4, h - 1), np.minimum(nx // 4, w - 1)
    nv, nu = (ny - nty * 4) / 4, (nx - ntx * 4) / 4
    node = (below[nty, ntx] * (1 - nu) * (1 - nv) + below[nty, ntx + 1] * nu * (1 - nv)
            + below[nty + 1, ntx] * (1 - nu) * nv + below[nty + 1, ntx + 1] * nu * nv)
    depth = np.minimum(np.minimum(node[:-1, :-1], node[:-1, 1:]), np.minimum(node[1:, :-1], node[1:, 1:]))
    deep = wet_flag[qy, qx] & (depth > 0) & ((depth > DEEP_WATER) | (terrain.tileset in IMPASSABLE_WATER))
    unwalkable_tile = ~walk[np.minimum(tiles[qy, qx], len(walk) - 1)]
    return ~(cliff | deep | unwalkable_tile | boundary[qy, qx])


def _margins(project) -> tuple[int, int, int, int] | None:
    """The tiles between the map edge and the playable area (left, right, bottom, top), from war3map.w3i."""
    from ..formats import w3i
    from .triggers import _read

    try:
        margins = tuple(w3i.parse(_read(project, "war3map.w3i") or b"").camera_complements)
    except Exception:   # noqa: BLE001 - no readable map info: no margins
        return None
    return margins if len(margins) == 4 and min(margins) >= 0 else None


def cells(project, terrain, catalog, objects, value=None) -> tuple[bytearray, int, int, str]:
    """(free cells as a flat bytearray, row-major from the south-west, columns, rows, where the terrain part came
    from). `objects` is (kind, type id, x, y) as for walkable()."""
    from ..formats import wpm
    from .triggers import _read

    width, height = (terrain.width - 1) * 4, (terrain.height - 1) * 4
    source = "derived"
    free = None
    notes = project.notes()
    if not notes.get("terrain_edited") and not notes.get("objects_edited"):   # the editor's pathing is still true
        data = _read(project, "war3map.wpm")
        try:
            saved = wpm.parse(data) if data else None
        except Exception:   # noqa: BLE001 - a damaged pathing map is just not used
            saved = None
        if saved is not None and (saved.width, saved.height) == (width, height):
            free = bytearray(0 if c & 2 else 1 for c in saved.cells)
            source = "war3map.wpm"
    if free is None:
        walk = terrain_cells(terrain, catalog)
        margins = _margins(project)
        if margins:   # outside the playable area nothing walks (the editor's pathing map marks it so)
            left, right, bottom, top = (4 * m for m in margins)
            walk[:bottom, :] = walk[height - top:, :] = False
            walk[:, :left] = walk[:, width - right:] = False
        free = bytearray(walk.astype("uint8").tobytes())
    value = value or (lambda kind, oid, field: catalog.field(kind, oid, field))
    textures: dict = {}
    for kind, type_id, x, y, *rest in objects:
        found = footprint(catalog, kind, type_id, value, textures)
        if not found or not found[2]:
            continue
        fixed = fixed_rotation(value, kind, type_id)
        angle = math.radians(fixed) if fixed is not None else (rest[0] if rest else 4.712389)
        for cx, cy in footprint_cells(found, kind, x, y, angle, terrain):
            if 0 <= cx < width and 0 <= cy < height:
                free[cy * width + cx] = 0
    return free, width, height, source


def flood(free: bytearray, width: int, height: int, seeds) -> "array":
    """Walking distance in cells from any seed cell to every cell (-1 where no walk leads)."""
    from array import array

    dist = array("i", [-1]) * (width * height)
    queue = deque()
    for s in seeds:
        if 0 <= s < len(free) and free[s] and dist[s] < 0:
            dist[s] = 0
            queue.append(s)
    while queue:
        s = queue.popleft()
        d = dist[s] + 1
        x = s % width
        for n in ((s - 1) if x > 0 else -1, (s + 1) if x < width - 1 else -1, s - width, s + width):
            if 0 <= n < len(free) and free[n] and dist[n] < 0:
                dist[n] = d
                queue.append(n)
    return dist


def cell_route(dist, width: int, goal: int) -> list[int]:
    """One shortest walk from the seeds to `goal`, seed first, following the distance field downhill."""
    if dist[goal] < 0:
        return []
    path, here = [goal], goal
    while dist[here] > 0:
        x = here % width
        here = next(n for n in ((here - 1) if x > 0 else -1, (here + 1) if x < width - 1 else -1,
                                here - width, here + width)
                    if 0 <= n < len(dist) and dist[n] == dist[here] - 1)
        path.append(here)
    return path[::-1]


def cell_gap(free: bytearray, width: int, route: list[int]) -> tuple[int, int | None]:
    """The narrowest free span across the route (cells) and the cell where it is: the gap a walk has to squeeze
    through."""
    height = len(free) // width
    narrowest, at = None, None
    for k, s in enumerate(route):
        n = route[min(k + 1, len(route) - 1)] if k + 1 < len(route) else route[max(k - 1, 0)]
        across = width if abs(n - s) == 1 else 1        # moving east-west: measure north-south, and the other way
        span = 1
        for sign in (1, -1):
            c = s + across * sign
            while 0 <= c < len(free) and free[c] and (across == width or c // width == s // width) \
                    and span < height + width:
                span += 1
                c += across * sign
        if narrowest is None or span < narrowest:
            narrowest, at = span, s
    return (narrowest or 0), at
