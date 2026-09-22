"""Editor round trip of a tool-built calibration map (pytest -m editor): the World Editor keeps what terrain_edit
writes, and the tools' derived pathing matches the war3map.wpm the editor computes. The w3e diff is the instrument
that found the cliff rule: any field the editor rewrites is a rule the tools lack."""
from pathlib import Path

import numpy as np
import pytest

from corpus import _storage
from wc3mcp.desktop import editor as ed
from wc3mcp.formats import w3e, wpm
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.mpq.reader import Archive
from wc3mcp.ops import flow, pathing
from wc3mcp.ops.newmap import new_map
from wc3mcp.ops.terrain import terrain_edit
from wc3mcp.ops.triggers import triggers_edit
from wc3mcp.project.workspace import MapProject

FIELDS = ("height", "water_level", "texture", "ramp", "blight", "water", "boundary", "cliff_texture", "layer")
FIXTURE = Path(__file__).parents[1] / "script" / "data" / "no_triggers.j"
CROSSING = (-256, -2688, 256, -2048)     # a dry crossing made over a river bed


def w3e_diff(a: w3e.Terrain, b: w3e.Terrain) -> dict:
    """field -> how many corners differ."""
    out = {}
    for cy in range(a.height):
        for cx in range(a.width):
            ca, cb = w3e.corner(a, cx, cy), w3e.corner(b, cx, cy)
            for f in FIELDS:
                if ca[f] != cb[f]:
                    out[f] = out.get(f, 0) + 1
    return out


def build(target: Path, catalog) -> w3e.Terrain:
    p = new_map(str(target), catalog, width=64, height=64, tileset="D", players=2, fill_tile="Ddrt")
    terrain_edit(p, catalog, [
        {"op": "cliff", "level": 7},
        {"op": "cliff", "rect": [-2048, -1024, -512, 1024], "level": 2},
        {"op": "cliff", "rect": [512, -1024, 2048, 1024], "level": 2},
        {"op": "cliff", "rect": [-512, -128, 512, 128], "level": 2},                 # a two-tile door
        {"op": "cliff", "path": [[-2048, 2048], [0, 2048], [0, 2944]], "width": 640, "level": 3},
        {"op": "cliff", "rect": [-2048, -2944, 2048, -1792], "level": 2},            # the water room
        {"op": "river", "path": [[-2048, -2368], [2048, -2368]], "width": 512, "walkable": False},
        {"op": "plateau", "rect": list(CROSSING)},
        {"op": "water", "rect": list(CROSSING), "level": None},
    ], quiet=["tile_pathing", "derived_files"])
    triggers_edit(p, catalog, [{"op": "delete", "what": "trigger", "name": "Melee Initialization"}])
    before = w3e.parse(p.read("war3map.w3e"))
    p.save()
    p.close()
    return before


@pytest.mark.editor
def test_the_editor_keeps_the_tools_terrain_and_pathing_agrees(tmp_path):
    editor = ed.Editor()
    if editor.status()["running"]:
        pytest.skip("a World Editor is already running")
    catalog = Catalog(_storage(), balance="Custom_V1")
    target = tmp_path / "Calibration.w3x"
    before = build(target, catalog)
    try:
        editor.launch(target)
        assert editor.save()["saved"]
    finally:
        editor.quit(discard=True)
    arc = Archive.open(target)
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_bytes(arc.read("war3map.j"))
    after = w3e.parse(arc.read("war3map.w3e"))
    changed = w3e_diff(before, after)
    assert changed.get("layer", 0) == 0, changed          # the editor kept every settled cliff level

    saved = wpm.parse(arc.read("war3map.wpm"))
    walk_saved = np.array([not (c & 2) for c in saved.cells]).reshape(saved.height, saved.width)
    walk_derived = pathing.terrain_cells(after, catalog)
    margin = 4 * 8    # compare inside the playable area: 8 tiles in from every edge covers the camera complements
    inside = (slice(margin, -margin), slice(margin, -margin))
    disagree = (walk_saved[inside] != walk_derived[inside]).mean()
    assert disagree <= 0.005, f"derived and saved pathing disagree on {disagree:.2%} of the cells"

    project = MapProject.open(target)
    try:
        door = flow.connect(project, catalog, [[-1280, 0]], [[1280, 0]])
        assert door["terrain_source"] == "war3map.wpm" and door["targets"][0]["reachable"]
    finally:
        project.close(discard=True)
