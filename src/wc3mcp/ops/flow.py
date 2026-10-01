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
from .pathing import CELL, CORNER, NOTE, corner_of, map_value, walkable

GOLD_MINE = "ngol"          # the neutral gold mine; a start's own mine and its expansions are all this unit
CREEP_OWNER = 24            # neutral hostile: the owner of a creep camp
NEAR_START = 1600.0         # a mine this close to a start is that player's own, not an expansion
NORMS_VERSION = 2           # bump when the mining below changes, so old caches are ignored
MELEE_PREFIX = "war3.w3mod:maps/"
SAMPLE = 40                 # shipped maps mined per player count; the norms move very little beyond that
DERIVED_WARNING = ("terrain pathing is derived (the map changed since the last World Editor save): cliffs and water "
                   "follow what the editor keeps, but only an editor save (editor_map open + save) writes "
                   "war3map.wpm; re-check the ways that matter after that save before building on them")


def _grid(project, catalog, corners: bool = True):
    """(terrain, walkability grid on the corners (None when corners is false), the placed objects, the start
    locations by owner)."""
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
            blockers.append((kind, type_id, o.x, o.y, o.angle))
    if not starts and scene.info:
        starts = {p.id: (p.start_x, p.start_y) for p in scene.info.players}
    grid = walkable(scene.terrain, catalog, blockers, map_value(project, catalog)) if corners else None
    return scene, grid, blockers, starts


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
    mines = [(x, y) for kind, type_id, x, y, *_ in blockers if kind == "unit" and type_id == GOLD_MINE]
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


def _places(scene, project, terrain, width: int, height: int, what, name: str,
            starts: dict) -> list[tuple[str, list[int]]]:
    """[(label, the cells it covers)] for a list of places: [x, y] points, region names or "start:N"."""
    from ..formats import w3r
    from .triggers import _read

    if not isinstance(what, list) or not what:
        raise ToolError("bad_value", f"{name}: expected a list of [x, y] points, region names or \"start:N\"",
                        path=name)
    regions = None
    out = []
    for k, place in enumerate(what):
        where = f"{name}[{k}]"
        if isinstance(place, list) and len(place) == 2 and all(isinstance(v, (int, float)) for v in place):
            box, label = (place[0], place[1], place[0], place[1]), f"({place[0]:g}, {place[1]:g})"
        elif isinstance(place, str) and place.startswith("start:"):
            owner = place[6:]
            known = {str(k): v for k, v in starts.items()}   # the start markers, else the map info's starts
            if owner not in known:
                raise ToolError("not_found", f"{where}: no start location of player {owner}", path=where,
                                hint=f"the map's starts: {sorted(known, key=int)}")
            x, y = known[owner]
            box, label = (x, y, x, y), place
        elif isinstance(place, str):
            if regions is None:
                data = _read(project, "war3map.w3r")
                regions = {g.name: g for g in (w3r.parse(data).regions if data else [])}
            key = place[len("gg_rct_"):] if place.startswith("gg_rct_") else place
            found = regions.get(key) or next((g for n, g in regions.items()
                                              if n.replace(" ", "_") == key), None)
            if found is None:
                raise ToolError("not_found", f"{where}: no region {place!r}", path=where,
                                hint="elements_list kind=region lists them")
            box, label = (found.left, found.bottom, found.right, found.top), place
        else:
            raise ToolError("bad_value", f"{where}: expected [x, y], a region name or \"start:N\"", path=where)
        c0 = min(max(int((box[0] - terrain.offset_x) // CELL), 0), width - 1)
        r0 = min(max(int((box[1] - terrain.offset_y) // CELL), 0), height - 1)
        c1 = min(max(int((box[2] - terrain.offset_x) // CELL), c0), width - 1)
        r1 = min(max(int((box[3] - terrain.offset_y) // CELL), r0), height - 1)
        out.append((label, [r * width + c for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)]))
    return out


ESCAPE = 24   # cells searched around a place on blocked ground (a building, a mine, a tree) for ground to stand on


def _standing(free: bytearray, width: int, covered: list[int]) -> list[int]:
    """The walkable cells of a place, or, when it lies on a footprint or other blocked ground, the nearest walkable
    ring around it (the ground a unit walks up to)."""
    own = [s for s in covered if free[s]]
    if own:
        return own
    ring, seen = set(covered), set(covered)
    for _step in range(ESCAPE):
        ring = {n for s in ring for n in (s - 1, s + 1, s - width, s + width)
                if 0 <= n < len(free) and n not in seen and abs(n % width - s % width) <= 1}
        seen |= ring
        found = [s for s in ring if free[s]]
        if found:
            return found
    return []


def connect(project, catalog, origins, targets) -> dict:
    """Whether a ground unit walks from any origin to each target on the game's 32-unit cells, how far, and the
    narrowest gap on the way: the proof that a wall is closed (every target unreachable: sealed) or where it leaks."""
    from .pathing import CELL_NOTE, cell_gap, cell_route, cells, flood

    scene, _grid_unused, blockers, starts = _grid(project, catalog, corners=False)
    terrain = scene.terrain
    free, width, height, source = cells(project, terrain, catalog, blockers, map_value(project, catalog))
    sources = _places(scene, project, terrain, width, height, origins, "origins", starts)
    goals = _places(scene, project, terrain, width, height, targets, "targets", starts)

    def xy(s: int) -> list[int]:
        return [round(terrain.offset_x + (s % width + 0.5) * CELL), round(terrain.offset_y + (s // width + 0.5) * CELL)]

    open_seeds = [s for _label, covered in sources for s in _standing(free, width, covered)]
    if not open_seeds:
        raise ToolError("bad_value", f"no origin has walkable ground within {ESCAPE * CELL} units: "
                        f"{[label for label, _ in sources]}", path="origins",
                        hint="an origin in deep water, on a cliff, outside the playable area or deep inside a "
                             "forest has nowhere to walk from; pick a point on open ground")
    dist = flood(free, width, height, open_seeds)
    out = {"cell_units": CELL, "terrain_source": source, "note": CELL_NOTE,
           "origins": [label for label, _ in sources], "targets": []}
    for label, covered in goals:
        reached = [s for s in _standing(free, width, covered) if dist[s] >= 0]
        row = {"target": label, "reachable": bool(reached)}
        if reached:
            goal = min(reached, key=lambda s: dist[s])
            route = cell_route(dist, width, goal)
            gap, at = cell_gap(free, width, route)
            row.update(distance=dist[goal] * CELL, gap=gap * CELL, gap_at=xy(at) if at is not None else None,
                       route=[xy(s) for s in route[::max(1, len(route) // 12)]] + [xy(route[-1])])
        out["targets"].append(row)
    out["sealed"] = not any(t["reachable"] for t in out["targets"])
    out["reading"] = ("sealed means no target can be walked to from any origin. For a reachable target, gap is the "
                      "narrowest free width across the shortest walk (world units) and gap_at where it is: where a "
                      "wall meant to be closed leaks, that is the hole. route samples the walk")
    if source == "derived":
        out["warning"] = DERIVED_WARNING
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
    mines = [(x, y) for kind, type_id, x, y, *_ in blockers if kind == "unit" and type_id == GOLD_MINE]
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


def areas(project, catalog, min_cells: int = 16, grid_step: int | None = None) -> dict:
    """The walkable areas of the map: ground cells a unit can walk between, each area labelled, largest first.
    grid_step (in 32-unit cells) adds a label grid at that resolution as run-length rows, south to north."""
    from .pathing import cells

    scene, _grid_unused, blockers, _starts = _grid(project, catalog, corners=False)
    terrain = scene.terrain
    free, width, height, source = cells(project, terrain, catalog, blockers, map_value(project, catalog))
    # union-find over the free runs of each row (4-connected, as units path on the cells)
    parent: list[int] = []

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    runs, previous = [], []
    for y in range(height):
        row, x, base = [], 0, y * width
        while x < width:
            if free[base + x]:
                start = x
                while x < width and free[base + x]:
                    x += 1
                label = len(parent)
                parent.append(label)
                for s, e, other in previous:   # a run above that overlaps joins this one
                    if s < x and start < e:
                        ra, rb = find(label), find(other)
                        if ra != rb:
                            parent[rb] = ra
                row.append((start, x, label))
            else:
                x += 1
        runs.append(row)
        previous = row
    sizes: dict[int, list] = {}
    for y, row in enumerate(runs):
        for s, e, label in row:
            root = find(label)
            entry = sizes.setdefault(root, [0, s, y, e - 1, y, s, y])
            entry[0] += e - s
            entry[1], entry[2] = min(entry[1], s), min(entry[2], y)
            entry[3], entry[4] = max(entry[3], e - 1), max(entry[4], y)
    ranked = sorted((r for r in sizes.items() if r[1][0] >= min_cells), key=lambda r: -r[1][0])
    number = {root: i + 1 for i, (root, _) in enumerate(ranked)}

    def world(cx: float, cy: float) -> list[int]:
        return [round(terrain.offset_x + cx * CELL), round(terrain.offset_y + cy * CELL)]

    out = {"cell_units": CELL, "terrain_source": source, "count": len(ranked),
           "smaller_hidden": sum(1 for v in sizes.values() if v[0] < min_cells),
           "areas": [{"area": number[root], "cells": v[0], "square_units": v[0] * CELL * CELL,
                      "rect": world(v[1], v[2]) + world(v[3] + 1, v[4] + 1),
                      "sample": world(v[5] + 0.5, v[6] + 0.5)} for root, v in ranked[:50]],
           "note": "areas are the ground a unit can walk between (32-unit cells, terrain plus every placed object's "
                   "footprint); area numbers go by size, and sample is one walkable point inside each"}
    if grid_step:
        step = max(1, int(grid_step))
        label_of = [0] * (width * height)
        for y, row in enumerate(runs):
            for s, e, label in row:
                n = number.get(find(label), 0)
                if n:
                    label_of[y * width + s:y * width + e] = [n] * (e - s)
        rows = []
        for y in range(step // 2, height, step):
            values = [label_of[y * width + x] for x in range(step // 2, width, step)]
            packed: list[list[int]] = []
            for v in values:
                if packed and packed[-1][0] == v:
                    packed[-1][1] += 1
                else:
                    packed.append([v, 1])
            rows.append(packed)
        out["grid"] = {"step_units": step * CELL, "origin": world(step / 2, step / 2), "rows": rows,
                       "format": "rows south to north, each [area, count] pairs west to east; 0 is not walkable"}
    return out


# ---- line of sight --------------------------------------------------------------------------------------------
SIGHT_STEP = 16      # world units between samples along a sight line: half a pathing cell, so no tree slips between
OPEN_CLEAR = 128     # an open spot keeps this far from every living destructible's centre
OPEN_SPACING = 64    # open spots listed at least this far apart, so units placed on them do not overlap
SIGHT_NOTE = ("a unit sees no ground on a higher cliff level than its own, and no further across it; a living "
              "destructible with an occlusion height (trees, rocks, gates, line-of-sight blockers) blocks the line "
              "within its pathing footprint's half-width. Heights inside one cliff level, flying units and vision "
              "range are not modelled")


class _Sight:
    """Cliff levels and the living sight-blocking destructibles of a map, for line-of-sight questions."""

    def __init__(self, scene, catalog):
        from .placed import _id

        self.terrain, self.scene = scene.terrain, scene
        self.solid, self.occluders = [], {}      # every living destructible; the sight blockers by 128-unit tile
        for o in scene.doodads.doodads:
            if o.life <= 0 or scene.kind_of(o) != "destructible":
                continue
            type_id = _id(o.id)
            self.solid.append((o.x, o.y))
            try:
                height = float(catalog.field("destructible", type_id, "boch") or 0)   # occlusion height
            except ValueError:
                height = 0.0
            if height <= 0:
                continue
            found = catalog.pathing_pixels(str(catalog.field("destructible", type_id, "bptx") or ""))
            reach = max(found[0], found[1]) * CELL / 2 if found else CORNER / 2
            key = (int(o.x // CORNER), int(o.y // CORNER))
            self.occluders.setdefault(key, []).append((o.x, o.y, reach, type_id))

    def level(self, x: float, y: float) -> int:
        t = self.terrain
        cx, cy = corner_of(t, x, y)
        return t.cliffs[cy * t.width + cx] & 15

    def blocker(self, a, b) -> dict | None:
        """The first thing that hides b from a unit standing at a, or None when b is in sight."""
        own = self.level(*a)
        steps = max(1, int(math.dist(a, b) // SIGHT_STEP))
        for k in range(1, steps + 1):
            f = k / steps
            x, y = a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
            level = self.level(x, y)
            if level > own:
                return {"kind": "cliff", "level": level, "at": [round(x), round(y)]}
            tx, ty = int(x // CORNER), int(y // CORNER)
            for i in (-1, 0, 1):
                for j in (-1, 0, 1):
                    for ox, oy, reach, type_id in self.occluders.get((tx + i, ty + j), ()):
                        # a tree the viewer or the target stands against hides neither of them
                        if math.dist((x, y), (ox, oy)) < reach <= min(math.dist(a, (ox, oy)), math.dist(b, (ox, oy))):
                            return {"kind": "destructible", "type": type_id,
                                    "name": self.scene.name("destructible", type_id),
                                    "at": [round(ox), round(oy)], "hit_at": [round(x), round(y)]}
        return None


def _point(value, name: str) -> tuple[float, float]:
    if isinstance(value, list) and len(value) == 2 and all(isinstance(v, (int, float)) for v in value):
        return float(value[0]), float(value[1])
    raise ToolError("bad_value", f"{name}: expected [x, y]", path=name)


def sight(project, catalog, line=None, open_near=None) -> dict:
    """Whether one point sees another (line = [x1, y1, x2, y2] or [[x1, y1], [x2, y2]]), and/or open ground near a
    point (open_near = [x, y, r] or [x, y, r, n]): walkable, on the point's own cliff level and walkable area, clear
    of destructibles, and in sight of it."""
    scene, _grid_unused, blockers, _starts = _grid(project, catalog, corners=False)
    look = _Sight(scene, catalog)
    out: dict = {"note": SIGHT_NOTE}
    if line is not None:
        if isinstance(line, list) and len(line) == 4:
            line = [line[:2], line[2:]]
        if not isinstance(line, list) or len(line) != 2:
            raise ToolError("bad_value", "sight: expected [x1, y1, x2, y2] or [[x1, y1], [x2, y2]]", path="sight")
        a, b = _point(line[0], "sight[0]"), _point(line[1], "sight[1]")
        seen, back = look.blocker(a, b), look.blocker(b, a)
        out["sight"] = {"from": [round(a[0]), round(a[1])], "to": [round(b[0]), round(b[1])],
                        "from_level": look.level(*a), "to_level": look.level(*b),
                        "distance": round(math.dist(a, b)), "visible": seen is None, "blocked_by": seen,
                        "visible_back": back is None, **({"blocked_back_by": back} if back else {})}
    if open_near is not None:
        out["open_near"] = _open_near(project, catalog, blockers, look, open_near)
    return out


def _open_near(project, catalog, blockers, look, spec) -> dict:
    from .pathing import cells, flood

    if not (isinstance(spec, list) and len(spec) in (3, 4) and all(isinstance(v, (int, float)) for v in spec)
            and spec[2] > 0):
        raise ToolError("bad_value", "open_near: expected [x, y, r] or [x, y, r, n] with r > 0", path="open_near")
    x, y, r = float(spec[0]), float(spec[1]), float(spec[2])
    n = int(spec[3]) if len(spec) == 4 else 10
    terrain = look.terrain
    free, width, height, source = cells(project, terrain, catalog, blockers, map_value(project, catalog))
    col, row = int((x - terrain.offset_x) // CELL), int((y - terrain.offset_y) // CELL)
    home = [row * width + col] if 0 <= col < width and 0 <= row < height else []
    seeds = _standing(free, width, home)
    if not seeds:
        raise ToolError("bad_value", f"open_near: no walkable ground within {ESCAPE * CELL} units of ({x:g}, {y:g})",
                        path="open_near")
    dist = flood(free, width, height, seeds)      # the walkable area of (x, y): spots elsewhere cannot be walked to
    level = look.level(x, y)
    solid: dict = {}
    for ox, oy in look.solid:
        solid.setdefault((int(ox // CORNER), int(oy // CORNER)), []).append((ox, oy))
    found = []
    span = int(r // CELL) + 1
    for j in range(max(row - span, 1), min(row + span + 1, height - 1)):
        for i in range(max(col - span, 1), min(col + span + 1, width - 1)):
            s = j * width + i
            if dist[s] < 0:
                continue
            px, py = terrain.offset_x + (i + 0.5) * CELL, terrain.offset_y + (j + 0.5) * CELL
            d = math.dist((x, y), (px, py))
            if d > r or look.level(px, py) != level:
                continue
            if not all(free[s + dj * width + di] for dj in (-1, 0, 1) for di in (-1, 0, 1)):
                continue      # beside a cliff, a footprint or deep water: not open ground
            tx, ty = int(px // CORNER), int(py // CORNER)
            if any(math.dist((px, py), p) < OPEN_CLEAR for a in (-1, 0, 1) for b in (-1, 0, 1)
                   for p in solid.get((tx + a, ty + b), ())):
                continue
            if look.blocker((x, y), (px, py)) is None:
                found.append((d, px, py, dist[s]))
    found.sort()
    spots = []
    for d, px, py, steps in found:
        if len(spots) >= n:
            break
        if all(math.dist((px, py), (sx, sy)) >= OPEN_SPACING for sx, sy, *_ in spots):
            spots.append((px, py, d, steps))
    out = {"at": [round(x), round(y)], "level": level, "radius": round(r), "found": len(found),
           "spots": [{"at": [round(px), round(py)], "distance": round(d), "walk": steps * CELL}
                     for px, py, d, steps in spots],
           "terrain_source": source,
           "reading": (f"found counts the 32-unit cells within radius that are walkable from (x, y), on its cliff "
                       f"level, with free cells all around, at least {OPEN_CLEAR} from a destructible and in sight of "
                       f"(x, y); spots are the nearest of them, {OPEN_SPACING} or more apart; walk is the walking "
                       f"distance from (x, y)")}
    if source == "derived":
        out["warning"] = DERIVED_WARNING
    return out
