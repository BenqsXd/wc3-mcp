"""Where units can walk: the terrain's own pathing plus the footprints of placed objects, and what that leaves
reachable. The grid is the terrain corner grid (128 units), so a corner counts as blocked when any part of a footprint
covers it - a unit needs more room than one pathing cell anyway. Used by map_validate and layout_check.
"""
from collections import deque

from ..formats import texture
from .terrain import _corner_pathing

# pathing texture field per kind; "none" means the type has no footprint
FOOTPRINT_FIELDS = {"destructible": "bptx", "doodad": "dptx", "unit": "upat"}
CELL = 32          # world units per pathing texture pixel
CORNER = 128       # world units per terrain corner
NOTE = ("walkability from the terrain plus the pathing texture of every placed object, on the 128-unit corner grid "
        "(a corner any footprint touches counts blocked), without the game's own unit collision")


def _blocked_pixels(catalog, path: str, cache: dict) -> tuple[int, int, frozenset] | None:
    """(width, height, the pixels that stop walking) of a pathing texture, or None when there is none."""
    if path not in cache:
        cache[path] = None
        if path and path.lower() != "none":
            full = catalog.storage.resolve(path.replace("\\", "/"), **catalog.layer)
            data = catalog.storage.read(full) if full else None
            if data is not None:
                image = texture.decode(data, path).convert("RGB")
                w, h = image.size
                pixels = image.tobytes()
                # red marks ground a unit cannot walk on (blue is build-only, green is flying)
                blocked = frozenset((i % w, i // w) for i in range(w * h) if pixels[i * 3] > 127)
                cache[path] = (w, h, blocked)
    return cache[path]


def footprint(catalog, kind: str, type_id: str, value, cache: dict) -> tuple[int, int, frozenset] | None:
    """The blocked pixels of a type's pathing texture; `value(kind, id, field)` gives the map's own field value."""
    field = FOOTPRINT_FIELDS.get(kind)
    return None if field is None else _blocked_pixels(catalog, str(value(kind, type_id, field) or ""), cache)


def walkable(terrain, catalog, objects, value=None) -> list[list[bool]]:
    """Grid[y][x] over the terrain corners: True where a unit can walk. `objects` is (kind, type id, x, y)."""
    cache: dict = {}
    value = value or (lambda kind, oid, field: catalog.field(kind, oid, field))
    grid = [[("w" not in _corner_pathing(terrain, catalog, x, y, cache)) for x in range(terrain.width)]
            for y in range(terrain.height)]
    textures: dict = {}
    for kind, type_id, x, y in objects:
        found = footprint(catalog, kind, type_id, value, textures)
        if not found or not found[2]:
            continue
        w, h, blocked = found
        for px, py in blocked:   # pixel centres in world units, then the corners they touch
            wx, wy = x + (px - w / 2 + 0.5) * CELL, y + (py - h / 2 + 0.5) * CELL
            cx = int(round((wx - terrain.offset_x) / CORNER))
            cy = int(round((wy - terrain.offset_y) / CORNER))
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
