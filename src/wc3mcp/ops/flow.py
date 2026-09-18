"""How a map plays, in numbers: how far players actually walk to each other and to their expansions, how narrow the
way between them gets, how much of the ground they can reach at all - and how those numbers compare with the melee
maps the game itself ships, which is the only honest yardstick available offline.

Distances are walking distances over the pathing grid (ops/pathing.py), never straight lines, because a straight line
across a cliff is not a distance a player can use.
"""
import json
import math
import statistics
from collections import deque

from .. import config
from ..errors import ToolError
from ..formats import doo, unitsdoo, w3e, w3i
from ..mpq.reader import Archive, MpqError
from .pathing import CORNER, NOTE, corner_of, walkable

GOLD_MINE = "ngol"          # the neutral gold mine; a start's own mine and its expansions are all this unit
CREEP_OWNER = 24            # neutral hostile: the owner of a creep camp
NEAR_START = 1600.0         # a mine this close to a start is that player's own, not an expansion
NORMS_VERSION = 2           # bump when the mining below changes, so old caches are ignored
MELEE_PREFIX = "war3.w3mod:maps/"
SAMPLE = 40                 # shipped maps mined per player count; the norms move very little beyond that


def _grid(project, catalog):
    """(terrain, walkability grid, the placed objects, the start locations by owner)."""
    from .placed import _Map, _id

    scene = _Map(project, catalog)
    if scene.terrain is None:
        raise ToolError("no_terrain", "this map has no war3map.w3e", hint="terrain_get shows the terrain")
    blockers, starts = [], {}
    for o in list(scene.doodads.doodads) + list(scene.units.units):
        kind, type_id = scene.kind_of(o), _id(o.id)
        if kind == "start_location":
            starts[o.owner] = (o.x, o.y)
        else:
            blockers.append((kind, type_id, o.x, o.y))
    if not starts and scene.info:
        starts = {p.id: (p.start_x, p.start_y) for p in scene.info.players}
    return scene, walkable(scene.terrain, catalog, blockers), blockers, starts


def _distances(grid, start) -> dict:
    """Walking distance in corners from one corner to every corner it can reach."""
    height, width = len(grid), len(grid[0])
    seen = {}
    queue = deque()
    for dx in range(-2, 3):          # a start may stand on its own mine: begin from the free ground around it
        for dy in range(-2, 3):
            x, y = start[0] + dx, start[1] + dy
            if 0 <= x < width and 0 <= y < height and grid[y][x] and (x, y) not in seen:
                seen[(x, y)] = 0
                queue.append((x, y))
    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < width and 0 <= ny < height and grid[ny][nx] and (nx, ny) not in seen:
                seen[(nx, ny)] = seen[(x, y)] + 1
                queue.append((nx, ny))
    return seen


def _nearest(reached: dict, terrain, points) -> tuple[float | None, tuple[float, float] | None]:
    """The closest of `points` by walking distance. A gold mine's own corners are blocked by its footprint, so the
    distance is measured to the free ground around it."""
    best, where = None, None
    for x, y in points:
        cx, cy = corner_of(terrain, x, y)
        steps = min((reached[(cx + dx, cy + dy)] for dx in range(-3, 4) for dy in range(-3, 4)
                     if (cx + dx, cy + dy) in reached), default=None)
        if steps is not None and (best is None or steps < best):
            best, where = steps, (x, y)
    return (None if best is None else best * CORNER), where


def _corridor(grid, path) -> tuple[float, tuple[int, int] | None]:
    """The narrowest walkable corridor across a path, and where it is: a choke point in world units."""
    height, width = len(grid), len(grid[0])
    narrowest, at = None, None
    for i, (x, y) in enumerate(path):
        ax, ay = path[min(i + 1, len(path) - 1)]
        dx, dy = ax - x, ay - y
        nx, ny = (0, 1) if abs(dx) >= abs(dy) else (1, 0)      # measure across the direction of travel
        span = 1
        for sign in (1, -1):
            step = 1
            while True:
                cx, cy = x + nx * step * sign, y + ny * step * sign
                if not (0 <= cx < width and 0 <= cy < height) or not grid[cy][cx]:
                    break
                span += 1
                step += 1
        if narrowest is None or span < narrowest:
            narrowest, at = span, (x, y)
    return (0.0 if narrowest is None else narrowest * CORNER), at


def _route(grid, reached: dict, start, goal) -> list:
    """The corners of one shortest walk from goal back to start, using the distance field of start."""
    if goal not in reached:
        return []
    path, here = [goal], goal
    while reached[here] > 0:
        x, y = here
        nxt = min(((nx, ny) for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)) if (nx, ny) in reached),
                  key=lambda c: reached[c], default=None)
        if nxt is None or reached[nxt] >= reached[here]:
            break
        path.append(nxt)
        here = nxt
    return list(reversed(path))


def flow_report(project, catalog, area=None) -> dict:
    """Walking distances between the starts, to the mines and the expansions, the chokes on the way, the room around
    each start, and what is cut off. Straight-line numbers would flatter a map; these are what a player walks."""
    scene, grid, blockers, starts = _grid(project, catalog)
    terrain = scene.terrain
    mines = [(x, y) for kind, type_id, x, y in blockers if kind == "unit" and type_id == GOLD_MINE]
    playable = scene.playable() or scene.whole()
    free = sum(sum(row) for row in grid)
    out: dict = {"starts": {}, "start_pairs": [], "gold_mines": len(mines), "corner_units": CORNER, "note": NOTE}
    fields = {owner: _distances(grid, corner_of(terrain, *xy)) for owner, xy in starts.items()}
    for owner, xy in sorted(starts.items()):
        reached = fields[owner]
        own, _at = _nearest(reached, terrain, [m for m in mines if math.dist(m, xy) <= NEAR_START])
        expansion, where = _nearest(reached, terrain, [m for m in mines if math.dist(m, xy) > NEAR_START])
        room = sum(1 for (cx, cy), steps in reached.items() if steps * CORNER <= 1500)
        out["starts"][str(owner)] = {
            "at": [round(xy[0]), round(xy[1])],
            "own_mine_distance": None if own is None else round(own),
            "nearest_expansion": None if expansion is None else round(expansion),
            "expansion_at": None if where is None else [round(where[0]), round(where[1])],
            "walkable_within_1500": room,
            "reaches": len(reached)}
    owners = sorted(starts)
    for i, a in enumerate(owners):
        for b in owners[i + 1:]:
            steps = fields[a].get(corner_of(terrain, *starts[b]))
            pair = {"players": [a, b], "distance": None if steps is None else round(steps * CORNER)}
            if steps is not None:
                route = _route(grid, fields[a], corner_of(terrain, *starts[a]), corner_of(terrain, *starts[b]))
                width, at = _corridor(grid, route)
                pair["choke"] = round(width)
                if at:
                    x, y = terrain.offset_x + at[0] * CORNER, terrain.offset_y + at[1] * CORNER
                    pair["choke_at"] = [round(x), round(y)]
            out["start_pairs"].append(pair)
    reachable = set().union(*fields.values()) if fields else set()
    pockets = _pockets(grid, reachable, terrain)
    out["walkable_corners"] = free
    out["reachable_from_starts"] = len(reachable)
    out["reachable_share"] = round(len(reachable) / free, 3) if free else 0.0
    out["pockets"] = [{"corners": size, "at": [round(x), round(y)]} for size, x, y in pockets[:5]]
    if playable:
        out["playable_area"] = [round(v) for v in playable]
    out["reading"] = ("distance and choke are world units a unit walks; a choke under about 400 is a one-unit-wide "
                      "pass, 400-900 a lane, above 1500 open ground. pockets are walkable areas no start reaches on "
                      "foot: on a melee map most of them are creep camps ringed by trees, which open once the trees "
                      "come down, so read them together with what stands in them")
    return out


def _pockets(grid, reachable: set, terrain) -> list:
    """Walkable areas no start can reach, biggest first, each with a world position inside it."""
    height, width = len(grid), len(grid[0])
    seen, out = set(reachable), []
    for y in range(height):
        for x in range(width):
            if not grid[y][x] or (x, y) in seen:
                continue
            queue, group = deque([(x, y)]), []
            seen.add((x, y))
            while queue:
                cx, cy = queue.popleft()
                group.append((cx, cy))
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < width and 0 <= ny < height and grid[ny][nx] and (nx, ny) not in seen:
                        seen.add((nx, ny))
                        queue.append((nx, ny))
            out.append((len(group), terrain.offset_x + group[0][0] * CORNER, terrain.offset_y + group[0][1] * CORNER))
    return sorted(out, reverse=True)


# ---- the shipped melee maps as a yardstick ---------------------------------------------------------------------
def _measure(archive, catalog) -> dict | None:
    """The metrics of one map, read straight from its archive. None when it is not a melee-shaped map."""
    try:
        terrain = w3e.parse(archive.read("war3map.w3e"))
        info = w3i.parse(archive.read("war3map.w3i"))
        units = unitsdoo.parse(archive.read("war3mapUnits.doo"))
    except (MpqError, Exception):   # noqa: BLE001 - a shipped map may be protected or use a format this codec skips
        return None
    doodads = None
    try:
        doodads = doo.parse(archive.read("war3map.doo"))
    except Exception:   # noqa: BLE001
        pass
    starts = [(u.x, u.y) for u in units.units if u.id == b"sloc"]
    if len(starts) < 2:
        return None
    mines = [(u.x, u.y) for u in units.units if u.id.decode("latin-1") == GOLD_MINE]
    creeps = [u for u in units.units if u.owner == CREEP_OWNER and u.id != b"sloc"]
    corners = terrain.width * terrain.height
    c = info.camera_complements
    playable = ((terrain.width - 1 - c[0] - c[1]) * 128) * ((terrain.height - 1 - c[2] - c[3]) * 128)
    pairs = [math.dist(a, b) for i, a in enumerate(starts) for b in starts[i + 1:]]
    own = [min((math.dist(s, m) for m in mines), default=0.0) for s in starts]
    return {"players": len(starts),
            "mines_per_player": len(mines) / len(starts),
            "start_distance": statistics.median(pairs) if pairs else 0.0,
            "own_mine_distance": statistics.median(own) if own else 0.0,
            "creeps": len(creeps),
            "creeps_per_player": len(creeps) / len(starts),
            "playable_per_player": playable / len(starts),
            "tiles": len(terrain.tiles),
            "doodad_density": (len(doodads.doodads) if doodads else 0) / (corners / 1000),
            "units_density": len(units.units) / (corners / 1000)}


def _norms(catalog, players: int, sample: int = SAMPLE) -> dict:
    """p10, median and p90 of every metric over the shipped melee maps with this many start locations. Mined once
    per install and kept in the cache folder, because reading forty archives is not a per-call cost."""
    cache = config.home() / "cache" / f"melee-norms-{players}-v{NORMS_VERSION}.json"
    if cache.is_file():
        try:
            return json.loads(cache.read_text("utf-8"))
        except (OSError, ValueError):
            pass
    names = sorted(p for p in catalog.storage.names()
                   if p.lower().startswith(MELEE_PREFIX) and p.lower().endswith((".w3m", ".w3x")))
    rows, read = [], 0
    for name in names:
        if len(rows) >= sample:
            break
        data = catalog.storage.read(name)
        if data is None:
            continue
        read += 1
        try:
            row = _measure(Archive(data), catalog)
        except Exception:   # noqa: BLE001 - one unreadable shipped map must not stop the norms
            continue
        if row and row["players"] == players:
            rows.append(row)
    norms = {"players": players, "maps": len(rows), "read": read, "metrics": {}}
    for key in ("mines_per_player", "start_distance", "own_mine_distance", "creeps", "creeps_per_player",
                "playable_per_player", "tiles", "doodad_density", "units_density"):
        values = sorted(row[key] for row in rows)
        if not values:
            continue
        norms["metrics"][key] = {"p10": _quantile(values, 0.1), "median": _quantile(values, 0.5),
                                 "p90": _quantile(values, 0.9)}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(norms), "utf-8")
    return norms


def _quantile(values: list, q: float) -> float:
    if not values:
        return 0.0
    i = min(len(values) - 1, max(0, int(round(q * (len(values) - 1)))))
    return round(values[i], 2)


def melee_check(project, catalog, sample: int = SAMPLE) -> dict:
    """Measure the open map the way the shipped melee maps are measured, and report each metric against their range.
    Every number here comes from those maps: nothing is a rule of thumb."""
    scene, grid, blockers, starts = _grid(project, catalog)
    terrain = scene.terrain
    units = scene.units
    mines = [(x, y) for kind, type_id, x, y in blockers if kind == "unit" and type_id == GOLD_MINE]
    creeps = [o for o in units.units if o.owner == CREEP_OWNER and o.id != b"sloc"]
    if len(starts) < 2:
        raise ToolError("bad_value", "a melee map needs at least two start locations",
                        hint="placed_edit adds one: {\"op\": \"add\", \"kind\": \"start_location\", \"owner\": 0}")
    corners = terrain.width * terrain.height
    playable = scene.playable() or scene.whole() or [0, 0, 0, 0]
    area = (playable[2] - playable[0]) * (playable[3] - playable[1])
    positions = list(starts.values())
    pairs = [math.dist(a, b) for i, a in enumerate(positions) for b in positions[i + 1:]]
    own = [min((math.dist(s, m) for m in mines), default=0.0) for s in positions]
    mine = {"mines_per_player": len(mines) / len(starts),
            "start_distance": statistics.median(pairs) if pairs else 0.0,
            "own_mine_distance": statistics.median(own) if own else 0.0,
            "creeps": float(len(creeps)),
            "creeps_per_player": len(creeps) / len(starts),
            "playable_per_player": area / len(starts),
            "tiles": float(len(terrain.tiles)),
            "doodad_density": len(scene.doodads.doodads) / (corners / 1000),
            "units_density": len(units.units) / (corners / 1000)}
    norms = _norms(catalog, len(starts), sample)
    metrics = {}
    for key, value in mine.items():
        band = norms["metrics"].get(key)
        row = {"value": round(value, 2)}
        if band:
            row.update(band)
            row["verdict"] = ("below" if value < band["p10"] else "above" if value > band["p90"] else "inside")
        metrics[key] = row
    flow = flow_report(project, catalog)
    return {"players": len(starts), "metrics": metrics,
            "norms": {"maps": norms["maps"], "players": norms["players"],
                      "source": "the melee maps shipped with this install (" + MELEE_PREFIX + "*)"},
            "reach": {"share": flow["reachable_share"], "pockets": len(flow["pockets"])},
            "start_pairs": flow["start_pairs"],
            "reading": ("p10 and p90 are the shipped maps' range for maps with the same number of players, so "
                        '"inside" means this map looks like them on that measure; units are world units, and '
                        "density is objects per 1000 terrain corners")}
