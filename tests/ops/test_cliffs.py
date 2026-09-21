"""terrain_edit keeps neighbouring cliff levels at most two apart, as the World Editor does when it loads a map, so
what the tools read before an editor save is what the editor keeps."""
import numpy as np
import pytest

from corpus import HAVE_INSTALL, _storage
from wc3mcp.formats import w3e
from wc3mcp.gamedata.catalog import Catalog
from wc3mcp.ops import flow
from wc3mcp.ops.newmap import new_map
from wc3mcp.ops.terrain import cliff_levels, steep_pairs, terrain_edit, terrain_get

pytestmark = pytest.mark.skipif(not HAVE_INSTALL, reason="needs the Warcraft III install")


@pytest.fixture(scope="module")
def catalog():
    return Catalog(_storage(), balance="Custom_V1")


def _map(tmp_path, catalog):
    return new_map(str(tmp_path / "C.w3x"), catalog, width=64, height=64, tileset="D", players=2, fill_tile="Ddrt")


def _steep(project) -> int:
    return steep_pairs(cliff_levels(w3e.parse(project.read("war3map.w3e"))))


def test_a_carved_corridor_keeps_its_level_and_the_rock_steps_down_outside(tmp_path, catalog):
    p = _map(tmp_path, catalog)
    result = terrain_edit(p, catalog, [{"op": "cliff", "level": 7},
                                       {"op": "cliff", "rect": [-896, -2048, 896, 2048], "level": 2}])
    row = terrain_get(p, [-1408, 0, 1408, 0], ["cliff_level"])["layers"]["cliff_level"][0]
    assert row == [7, 7, 6, 4] + [2] * 15 + [4, 6, 7, 7]
    assert result["cliffs"][0]["blended"] == 0
    assert result["cliffs"][1]["corners"] == 15 * 33 and result["cliffs"][1]["blended"] > 0
    assert _steep(p) == 0


def test_a_two_tile_doorway_stays_open(tmp_path, catalog):
    p = _map(tmp_path, catalog)
    terrain_edit(p, catalog, [{"op": "cliff", "level": 7},
                              {"op": "cliff", "rect": [-2048, -1024, -512, 1024], "level": 2},
                              {"op": "cliff", "rect": [512, -1024, 2048, 1024], "level": 2},
                              {"op": "cliff", "rect": [-512, -128, 512, 128], "level": 2}])
    target = flow.connect(p, catalog, [[-1280, 0]], [[1280, 0]])["targets"][0]
    assert target["reachable"] and target["gap"] >= 256


def test_raising_a_plateau_ramps_the_ground_around_it_up(tmp_path, catalog):
    p = _map(tmp_path, catalog)
    terrain_edit(p, catalog, [{"op": "cliff", "rect": [-512, -512, 512, 512], "level": 8}])
    row = terrain_get(p, [-1024, 0, 1024, 0], ["cliff_level"])["layers"]["cliff_level"][0]
    assert row == [2, 2, 4, 6] + [8] * 9 + [6, 4, 2, 2]


def test_old_steep_steps_elsewhere_are_lowered_and_reported(tmp_path, catalog):
    p = _map(tmp_path, catalog)
    t = w3e.parse(p.read("war3map.w3e"))
    for cx in range(30, 35):            # a 7|2 wall written straight into the file, as 1.2 did
        for cy in range(t.height):
            w3e.set_corner(t, cx, cy, layer=7)
    p.write("war3map.w3e", w3e.serialize(t))
    result = terrain_edit(p, catalog, [{"op": "paint", "x": -2000, "y": -2000, "radius": 200, "tile": "Ddkr"}])
    assert any("more than 2 cliff levels" in w for w in result["warnings"])
    assert _steep(p) == 0
