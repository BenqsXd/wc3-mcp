"""map_new: a new melee-ready map written from scratch with the file versions the current World Editor saves
(w3i 39, w3e 12, doodads/units 13/11, regions 7, cameras 3, sounds 3), a flat terrain, one start location per
player, the default "Melee Initialization" trigger, a script built from those files and the minimap image."""
import json
import math
import shutil
from pathlib import Path

from .. import config, pathguard
from ..errors import ToolError
from ..formats import doo, imp, mmp, unitsdoo, w3c, w3e, w3i, w3r, w3s, wct, wpm, wtg
from ..formats.wts import TriggerStrings
from ..mpq.writer import write_archive
from ..project.workspace import MapProject
from ..script import build
from . import script as script_ops
from .terrain import VARIATIONS, minimap
from .triggers import triggers_edit

SIZES = range(32, 481, 32)  # total tiles per side, as the editor's New Map dialog offers them
MARGINS = (6, 6, 4, 8)  # left, right, bottom, top tiles outside the playable area
CAMERA_INSET = (512, 256)  # camera bounds sit this far inside the playable area (x, y)
WATER_LEVEL = 0x2200
MAP_FLAGS = 0x3D814  # melee, masked areas partially visible, shore waves, item classes, water tint, accurate chances
RACE_SKIN = 0x40
WCT_COMMENT = ("Enter map-specific custom script code below.  This text will be included in the map script after "
               "variables are declared and before any trigger code.")
MELEE_ACTIONS = ("MeleeStartingVisibility", "MeleeStartingHeroLimit", "MeleeGrantHeroItems", "MeleeStartingResources",
                 "MeleeClearExcessUnits", "MeleeStartingUnits", "MeleeStartingAI", "MeleeInitVictoryDefeat")


def _game_version() -> list[int]:
    try:
        lines = (config.install_root() / ".build.info").read_text("utf-8").splitlines()
        columns = [c.split("!")[0] for c in lines[0].split("|")]
        row = next(dict(zip(columns, line.split("|"))) for line in lines[1:] if line.split("|")[1:2] == ["1"])
        return [int(x) for x in row["Version"].split(".")]
    except (OSError, StopIteration, KeyError, ValueError, IndexError):
        return [3, 0, 0, 24268]


def _bad(field: str, message: str) -> ToolError:
    return ToolError("bad_value", f"{field}: {message}", hint="map_new(path, width, height, tileset, players)", path=field)


def _files(catalog, name: str, width: int, height: int, tileset: str, author: str, players: int,
           lua: bool = False) -> tuple[dict, w3i.MapInfo]:
    tiles = [t.encode("latin-1") for t in catalog.ids("tile") if t[0] == tileset]
    cliffs = [c.encode("latin-1") for c in catalog.ids("cliff") if c[1] == tileset][:2]
    if not tiles:
        raise _bad("tileset", f"no ground tiles for tileset {tileset!r} (data_search kind=tile)")
    corners_x, corners_y = width + 1, height + 1
    ox, oy = -width * 64.0, -height * 64.0
    n = corners_x * corners_y
    terrain = w3e.Terrain(12, tileset, 0, tiles, cliffs, corners_x, corners_y, ox, oy, [0x2000] * n, [WATER_LEVEL] * n,
                          [0] * n, [VARIATIONS[(i * 7 + i // corners_x * 13) % len(VARIATIONS)] for i in range(n)],
                          [15 << 4 | 2] * n)
    left, right, bottom, top = MARGINS
    play = (ox + left * 128, oy + bottom * 128, ox + (width - right) * 128, oy + (height - top) * 128)
    cells_x, cells_y = width * 4, height * 4
    pathing = bytearray(0xCE for _ in range(cells_x * cells_y))
    for cy in range(bottom * 4, (height - top) * 4):
        pathing[cy * cells_x + left * 4:cy * cells_x + (width - right) * 4] = bytes([0x40]) * ((width - left - right) * 4)

    strings = TriggerStrings()
    info = w3i.MapInfo(39, map_version=1, editor_version=7000, game_version=_game_version())
    names = [strings.add(f"Player {k + 1}") for k in range(players)]
    force = strings.add("Force 1")
    info.name, info.players_recommended = f"TRIGSTR_{strings.add(name)}", f"TRIGSTR_{strings.add('Any')}"
    info.description, info.author = f"TRIGSTR_{strings.add('Nondescript')}", f"TRIGSTR_{strings.add(author)}"
    ix, iy = CAMERA_INSET
    bounds = (play[0] + ix, play[1] + iy, play[2] - ix, play[3] - iy)
    info.camera_bounds = [bounds[0], bounds[1], bounds[2], bounds[3], bounds[0], bounds[3], bounds[2], bounds[1]]
    info.camera_complements = [left, right, bottom, top]
    info.playable_width, info.playable_height = width - left - right, height - top - bottom
    info.flags, info.tileset, info.script_language = MAP_FLAGS, ord(tileset), int(lua)
    info.fog_start_z, info.fog_end_z, info.fog_density = 3000.0, 5000.0, 0.5
    cx, cy = (play[0] + play[2]) / 2, (play[1] + play[3]) / 2
    radius = 0.35 * min(play[2] - play[0], play[3] - play[1])
    units = unitsdoo.UnitFile(13, 11)
    for k in range(players):
        a = math.pi / 4 + 2 * math.pi * k / players
        x, y = round((cx + radius * math.cos(a)) / 32) * 32.0, round((cy + radius * math.sin(a)) / 32) * 32.0
        info.players.append(w3i.Player(k, 1, 1, RACE_SKIN, f"TRIGSTR_{names[k]}", x, y, 0, 0))
        units.units.append(unitsdoo.Unit(b"sloc", 0, x, y, 0.0, math.radians(270), [1.0, 1.0, 1.0], b"sloc", 2, k,
                                         gold=0, target_acquisition=0.0, hero_level=0, random_flag=0,
                                         random_data=b"\x01\x00\x00\x00", editor_id=k))
    info.forces.append(w3i.Force(0, 0xFFFFFFFF, f"TRIGSTR_{force}"))
    tf = wtg.TriggerFile(elements=[wtg.Category(wtg.ROOT, 0, name)])
    tf.counters[0] = (1, [])
    files = {
        "war3map.w3i": w3i.serialize(info), "war3map.w3e": w3e.serialize(terrain),
        "war3map.shd": bytes(cells_x * cells_y), "war3map.wpm": wpm.serialize(wpm.PathingMap(0, cells_x, cells_y, pathing)),
        "war3map.mmp": mmp.serialize(mmp.Minimap()), "war3map.doo": doo.serialize(doo.DoodadFile(13, 11)),
        "war3mapUnits.doo": unitsdoo.serialize(units), "war3map.w3r": w3r.serialize(w3r.RegionFile(7)),
        "war3map.w3c": w3c.serialize(w3c.CameraFile(3)), "war3map.w3s": w3s.serialize(w3s.SoundFile(3)),
        "war3map.imp": imp.serialize(imp.ImportList()), "war3map.wts": strings.serialize(),
        "war3map.wtg": wtg.serialize(tf), "war3map.wct": wct.serialize(wct.CustomText(comment=WCT_COMMENT)),
        "conversation.json": json.dumps({"stringTablePath": "war3map.wts", "conversation": {}}, indent=4).encode(),
    }
    return files, info


def new_map(path, catalog, width: int = 64, height: int = 64, tileset: str = "L", name: str = "Just another Warcraft III map",
            author: str = "Unknown", players: int = 2, script_language: str = "jass", format: str = "mpq") -> MapProject:
    target = pathguard.ensure_writable(path)
    if target.exists():
        raise ToolError("exists", f"{target} already exists", hint="choose a new path, or map_open the existing map")
    for field, value in (("width", width), ("height", height)):
        if not isinstance(value, int) or value not in SIZES:
            raise _bad(field, f"expected a size from {SIZES.start} to {SIZES.stop - 1} in steps of {SIZES.step}")
    if not isinstance(tileset, str) or len(tileset) != 1:
        raise _bad("tileset", "expected a tileset letter such as L (Lordaeron Summer) or V (Village)")
    if not isinstance(players, int) or isinstance(players, bool) or not 1 <= players <= 24:
        raise _bad("players", "expected 1 to 24")
    if script_language not in ("jass", "lua") or format not in ("mpq", "folder"):
        raise _bad("format" if script_language in ("jass", "lua") else "script_language", "expected jass or lua / mpq or folder")
    files, _ = _files(catalog, name, width, height, tileset, author, players, script_language == "lua")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        if format == "folder":
            for file, data in files.items():
                (target / file).parent.mkdir(parents=True, exist_ok=True)
                (target / file).write_bytes(data)
        else:
            target.write_bytes(write_archive(files))
        project = MapProject.open(target)
        triggers_edit(project, catalog, [
            {"op": "category", "name": "Initialization"},
            {"op": "trigger", "name": "Melee Initialization", "category": "Initialization",
             "description": "Default melee game initialization for all players",
             "events": [{"fn": "MapInitializationEvent"}], "actions": [{"fn": fn} for fn in MELEE_ACTIONS]}])
        tf, ct = script_ops._load(project, catalog.trigger_data)
        if script_language == "lua":
            project.write("war3map.lua", script_ops.lua_script(project, catalog, tf, ct).encode("utf-8"))
        else:
            objects, scene = script_ops._Objects(project, catalog), script_ops._world(project, catalog)
            text = build.new_script(tf, ct, catalog.trigger_data, scene, script_ops._placed(project, catalog, objects),
                                    script_ops._mapinfo(project, catalog, objects, scene.terrain))
            project.write("war3map.j", text.encode("utf-8"))
        project.write("war3mapMap.blp", minimap(project, catalog))
        project.save(force=True)
        return project
    except BaseException:
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        else:
            target.unlink(missing_ok=True)
        raise
